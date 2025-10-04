"""
Flask backend for a simple chat interface that connects to a local
Ollama instance running at a custom host.  The server exposes two
endpoints: one for chatting with the large language model and one
for uploading attachments.  Conversation state is stored in memory
so that the model can maintain context between turns.  Attachments
are saved to the ``uploads`` folder and returned to the client with
their filenames and data URIs for display.  This backend is
intended for demonstration purposes and should not be used in
production without adding proper authentication and security.

To start the server run::

    pip install flask flask_cors requests
    python server.py

The server will serve the chat interface at http://localhost:5000/.
"""

import base64
import os
from pathlib import Path
from typing import List, Dict

from flask import Flask, jsonify, render_template, request, send_from_directory, session, redirect, url_for
from flask_cors import CORS
import requests
import json
from werkzeug.security import generate_password_hash, check_password_hash


APP_ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = APP_ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


app = Flask(__name__, static_folder=str(APP_ROOT / "static"), template_folder=str(APP_ROOT / "templates"))
# Allow cross‑origin requests so that the frontend can be served from the
# same Flask app.  In a production environment you may want to restrict
# origins appropriately.
CORS(app)

# In‑memory history of chat messages.  Each entry is a dict with
# ``role`` and ``content`` keys following the OpenAI format.
conversation_history: List[Dict[str, str]] = []

# Base URL of the LLM service.  By default this points to the remote
# LiteLLM proxy hosted at ollama4k.nubacom.mx.  You can change it to
# another OpenAI-compatible service (e.g. your own Ollama server) by
# defining the OLLAMA_BASE_URL environment variable.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama4k.nubacom.mx")
# Name of the model to use.  For LiteLLM proxies this should match the
# model identifier exposed by the proxy (e.g. "gpt-oss-20b").  Override via
# the OLLAMA_MODEL environment variable.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss-20b")
# Optional API key for services that require authentication (e.g. LiteLLM
# proxy with API keys).  If not set, no Authorization header will be sent.
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY")

# Path to the users data file.  This file stores user credentials and
# their conversation histories.  Each entry in the JSON array has
# ``username``, ``password_hash``, ``role`` and ``conversations`` keys.
USERS_FILE = APP_ROOT / "users.json"

# Flask secret key for session management.  In production, override
# this via the FLASK_SECRET environment variable.
app.secret_key = os.environ.get("FLASK_SECRET", "super-secret-key")

# ---------------------------------------------------------------------------
# Helper functions for user management
#
def load_users():
    """Load the list of users from the JSON file.

    Returns an empty list if the file does not exist or cannot be parsed.
    """
    if USERS_FILE.exists():
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_users(users):
    """Persist the list of users to the JSON file."""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def get_user(username):
    """Retrieve a user record by username, or None if not found."""
    users = load_users()
    for u in users:
        if u.get("username") == username:
            return u
    return None


def update_user(updated_user):
    """Replace an existing user record with an updated one and save.

    This helper iterates through the users list, finds the entry with
    matching username and replaces it with ``updated_user``.  It then
    writes the entire list back to disk.
    """
    users = load_users()
    for idx, u in enumerate(users):
        if u.get("username") == updated_user.get("username"):
            users[idx] = updated_user
            save_users(users)
            return
    # If not found, append as new user
    users.append(updated_user)
    save_users(users)


@app.route("/")
def index() -> str:
    """Serve the main chat interface HTML.

    If the user is not authenticated, redirect to the login page.  The
    chat interface requires a logged‑in user to provide context for
    conversation history and personalisation.
    """
    # Redirect unauthenticated users to the login page
    if not session.get("username"):
        return redirect(url_for("login"))
    return render_template("index.html")


@app.route("/uploads/<path:filename>")
def uploaded_file(filename: str):
    """Serve an uploaded file from the uploads directory."""
    return send_from_directory(UPLOAD_DIR, filename)


# ---------------------------------------------------------------------------
# Authentication and user management routes
#

@app.route("/login", methods=["GET", "POST"])
def login():
    """Render and process the login form.

    On a GET request, this returns the login template.  On a POST
    request, it validates the submitted credentials against the stored
    users file.  If the login succeeds, it stores the username and
    role in the session and redirects to the chat interface.  On
    failure, it re‑renders the form with an error message.
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_user(username)
        if user and check_password_hash(user.get("password_hash", ""), password):
            # Successful login
            session["username"] = username
            session["role"] = user.get("role", "user")
            session["current_conversation"] = None
            return redirect(url_for("index"))
        else:
            # Invalid credentials
            return render_template("login.html", error="Credenciales incorrectas"), 401
    # GET request
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Render and process the user registration form.

    On POST, create a new user if the username is not already taken.
    The password is hashed before being stored.  New accounts are
    assigned the 'user' role by default.  After successful registration
    the user is redirected to the login page.
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if not username or not password:
            return render_template("register.html", error="Usuario y contraseña son obligatorios")
        if password != confirm:
            return render_template("register.html", error="Las contraseñas no coinciden")
        if get_user(username):
            return render_template("register.html", error="El usuario ya existe")
        # Create new user record
        password_hash = generate_password_hash(password)
        new_user = {
            "username": username,
            "password_hash": password_hash,
            "role": "user",
            "conversations": []
        }
        users = load_users()
        users.append(new_user)
        save_users(users)
        return redirect(url_for("login"))
    # GET request
    return render_template("register.html")


@app.route("/logout")
def logout():
    """Log the user out by clearing the session and redirecting to login."""
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
def admin_panel():
    """Render the admin panel listing all users.

    Only users with role 'admin' may access this view.  Non‑admins are
    redirected to the main chat interface.  The admin page shows a
    simple table of users and allows deletion via POST to the delete
    route.
    """
    if session.get("role") != "admin":
        return redirect(url_for("index"))
    users = load_users()
    return render_template("admin.html", users=users)


@app.route("/admin/delete/<username>", methods=["POST"])
def delete_user(username):
    """Delete a user account.  Only admins may perform this action."""
    if session.get("role") != "admin":
        return redirect(url_for("index"))
    users = load_users()
    users = [u for u in users if u.get("username") != username]
    save_users(users)
    # If the deleted user was logged in, also clear their session
    if session.get("username") == username:
        session.clear()
    return redirect(url_for("admin_panel"))


# ---------------------------------------------------------------------------
# Conversation management routes
#
@app.route("/api/conversations", methods=["GET"])
def api_conversations():
    """Return a list of conversation summaries for the current user.

    Each summary includes an ``id`` and a ``title`` derived from the
    first user message in the conversation.  Conversations are stored
    under the logged‑in user's record in the users file.
    """
    if not session.get("username"):
        return jsonify({"error": "No autenticado"}), 401
    user = get_user(session["username"])
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404
    summaries = []
    conversations = user.get("conversations", [])
    for idx, convo in enumerate(conversations):
        title = "Nueva conversación"
        for msg in convo.get("messages", []):
            if msg.get("role") == "user":
                # Use first line as title
                title = msg.get("content", "").split("\n")[0][:50]
                break
        summaries.append({"id": idx, "title": title or f"Conversación {idx+1}"})
    return jsonify({"conversations": summaries})


@app.route("/api/conversations/<int:index>", methods=["GET"])
def api_get_conversation(index: int):
    """Load a specific conversation for the current user.

    This endpoint returns the list of message objects (role and content)
    for the selected conversation and loads them into the in‑memory
    ``conversation_history`` so that subsequent chat calls continue
    from that context.  The selected conversation index is stored in
    the session under ``current_conversation``.
    """
    if not session.get("username"):
        return jsonify({"error": "No autenticado"}), 401
    user = get_user(session["username"])
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404
    conversations = user.get("conversations", [])
    if index < 0 or index >= len(conversations):
        return jsonify({"error": "Índice de conversación inválido"}), 404
    messages = conversations[index].get("messages", [])
    # Replace the in‑memory conversation history with the stored messages
    conversation_history.clear()
    conversation_history.extend(messages)
    session["current_conversation"] = index
    return jsonify({"messages": messages})


@app.route("/api/new_chat", methods=["POST"])
def api_new_chat():
    """Start a new empty conversation for the current user.

    A new conversation entry is added to the user's record.  The
    in‑memory history is cleared and the new conversation index is
    stored in the session.  Returns the index of the newly created
    conversation.
    """
    if not session.get("username"):
        return jsonify({"error": "No autenticado"}), 401
    user = get_user(session["username"])
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404
    # Append a new conversation with an empty messages list
    conversations = user.setdefault("conversations", [])
    conversations.append({"messages": []})
    new_index = len(conversations) - 1
    # Persist to disk
    update_user(user)
    # Reset in‑memory history and session pointer
    conversation_history.clear()
    session["current_conversation"] = new_index
    return jsonify({"id": new_index})


@app.route("/api/upload", methods=["POST"])
def upload() -> Dict[str, str]:
    """Handle file uploads from the client.

    The endpoint accepts multipart form data containing one or more files
    under the ``files`` field.  It returns a JSON object with an array
    of file metadata (name and data URL) that can be displayed in the
    chat.  Files are saved on disk so that they can be served back
    later if needed.
    """
    uploaded_files = request.files.getlist("files")
    result = []
    for file in uploaded_files:
        filename = file.filename
        if not filename:
            continue
        save_path = UPLOAD_DIR / filename
        # If a file with the same name exists, append a suffix
        counter = 1
        original_name, ext = os.path.splitext(filename)
        while save_path.exists():
            filename = f"{original_name}_{counter}{ext}"
            save_path = UPLOAD_DIR / filename
            counter += 1
        file.save(save_path)
        # Build a data URI so the frontend can display the file inline
        mime_type = file.mimetype or "application/octet-stream"
        with open(save_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode()
        data_url = f"data:{mime_type};base64,{b64_data}"
        result.append({"name": filename, "data_url": data_url, "url": f"/uploads/{filename}"})
    return jsonify({"files": result})


@app.route("/api/models", methods=["GET"])
def list_models():
    """Fetch the list of available models from the remote LLM service.

    This endpoint queries the OpenAI-compatible `/v1/models` endpoint.  If
    that call fails, it falls back to `/models`.  The response is a JSON
    object with a ``models`` array containing model identifiers.
    """
    headers = {}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    try:
        # Try the OpenAI-compatible path
        url = f"{OLLAMA_BASE_URL.rstrip('/')}/v1/models"
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        models = []
        # The OpenAI API returns a list under the 'data' key
        if isinstance(data, dict) and 'data' in data:
            for m in data['data']:
                # Each model dict should have an 'id'
                model_id = m.get('id') or m.get('name')
                if model_id:
                    models.append(model_id)
        else:
            # Some proxies may return plain array
            models = data
        return jsonify({"models": models})
    except Exception:
        # Fallback to /models
        try:
            url = f"{OLLAMA_BASE_URL.rstrip('/')}/models"
            resp = requests.get(url, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            models = []
            if isinstance(data, dict) and 'data' in data:
                for m in data['data']:
                    model_id = m.get('id') or m.get('name')
                    if model_id:
                        models.append(model_id)
            else:
                models = data
            return jsonify({"models": models})
        except Exception as e:
            return jsonify({"error": f"Error fetching models: {e}"}), 500


@app.route("/api/reset_history", methods=["POST"])
def reset_history() -> Dict[str, str]:
    """Reset the in-memory conversation history.

    When the user selects a different model from the UI, the client can call
    this endpoint to clear previous messages so that the new model starts
    with a fresh context.  The system message will be re‑injected on the
    next chat request.
    """
    conversation_history.clear()
    return jsonify({"status": "reset"})


@app.route("/api/chat", methods=["POST"])
def chat() -> Dict[str, str]:
    """Handle a chat message from the frontend and forward it to the model.

    Expects a JSON payload with ``message`` (the user's text) and an optional
    ``attachments`` array containing objects with ``name`` and ``data``.
    The attachments are currently appended to the user message as plain text
    references.  After calling the local Ollama API the assistant's
    response is appended to the conversation history and returned to
    the frontend.
    """
    data = request.get_json(force=True)
    user_message = data.get("message", "").strip()
    attachments = data.get("attachments", []) or []
    # The client can specify a model per request.  If omitted use the
    # default model defined in the environment.
    selected_model = data.get("model", OLLAMA_MODEL)
    # Build a content string that includes references to attached files
    content = user_message
    for att in attachments:
        # Simply reference the filename in the prompt.  If the model
        # supported image or file inputs directly you could include the
        # base64 here.  For demonstration we just note the file name.
        content += f"\n[adjunto: {att.get('name')}]"
    if not content:
        return jsonify({"error": "Message is empty"}), 400
    # If this is the first user turn, prime the conversation with a system
    # message instructing the model to reply only in the language of the user
    # and avoid adding translations unless explicitly asked.  This helps to
    # prevent the model from including English translations when the user
    # communicates in Spanish.
    if not conversation_history:
        conversation_history.append({
            "role": "system",
            "content": (
                "Eres un asistente servicial. Responde siempre en el idioma que "
                "utilice el usuario y no incluyas traducciones a otros idiomas "
                "a menos que el usuario lo solicite explícitamente."
            ),
        })
    # Append the user's message to the conversation history
    conversation_history.append({"role": "user", "content": content})
    # Prepare the payload for the LLM chat API.  See
    # https://ollama.com/blog/openai-compatibility for the request format.
    payload = {
        "model": selected_model,
        "messages": conversation_history,
        # ask for a single response.  You could set stream=True to get
        # streaming responses, but for simplicity we'll keep it False.
        "stream": False,
    }
    try:
        # Compose the OpenAI-compatible chat completions URL.  For LiteLLM
        # proxies this will be something like https://proxy.example/v1/chat/completions.
        api_url = f"{OLLAMA_BASE_URL.rstrip('/')}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if OLLAMA_API_KEY:
            # Use Bearer token authentication if an API key is provided
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
        response = requests.post(api_url, json=payload, headers=headers, timeout=300)
        response.raise_for_status()
        data = response.json()
        # Extract the assistant message from the choices list (OpenAI format)
        assistant_content = data["choices"][0]["message"]["content"]
    except Exception as first_error:
        # Fallback to legacy /api/chat endpoint used by older Ollama versions.
        try:
            legacy_url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
            headers = {"Content-Type": "application/json"}
            if OLLAMA_API_KEY:
                headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
            resp = requests.post(legacy_url, json=payload, headers=headers, timeout=300)
            resp.raise_for_status()
            data = resp.json()
            assistant_content = data.get("message") or data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not assistant_content:
                assistant_content = "No se recibió contenido del servicio LLM."
        except Exception as e:
            assistant_content = f"Error contacting LLM service: {e}""\n"f"(initial error: {first_error})"
    # Append the assistant's response to the history
    conversation_history.append({"role": "assistant", "content": assistant_content})

    # Persist the updated history to the user's conversations
    if session.get("username"):
        user = get_user(session["username"])
        if user:
            # Determine which conversation we are working on.  If none
            # exists yet, create a new one.
            conv_idx = session.get("current_conversation")
            if conv_idx is None:
                # Create a new conversation entry
                conv_idx = len(user.get("conversations", []))
                user.setdefault("conversations", []).append({"messages": []})
                session["current_conversation"] = conv_idx
            # Copy the current in-memory history into the persistent store
            conversations = user.setdefault("conversations", [])
            # Ensure list is long enough
            while len(conversations) <= conv_idx:
                conversations.append({"messages": []})
            conversations[conv_idx]["messages"] = list(conversation_history)
            # Save the user record back to disk
            update_user(user)
    return jsonify({"message": assistant_content})


if __name__ == "__main__":
    # Ensure there is at least one admin user when starting the server.
    # If the users file is empty or missing, create a default admin
    # account with username 'admin' and password 'admin'.  In a real
    # application you should change this password immediately and
    # implement secure account provisioning.
    def ensure_admin_user():
        users = load_users()
        if not users:
            # Create a default admin account
            pwd_hash = generate_password_hash("admin")
            admin_user = {
                "username": "admin",
                "password_hash": pwd_hash,
                "role": "admin",
                "conversations": []
            }
            save_users([admin_user])
    ensure_admin_user()
    # In development mode enable debug for auto reload
    app.run(host='0.0.0.0', port=5000, debug=True)