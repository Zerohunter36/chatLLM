// Client-side script to handle chat UI interactions, file uploads and
// voice input. Uses the Fetch API to talk to the Flask backend.
document.addEventListener('DOMContentLoaded', () => {
  // Core UI elements
  const chatArea         = document.getElementById('chat-area');
  const messageInput     = document.getElementById('message-input');
  const messageForm      = document.getElementById('message-form');
  const fileInput        = document.getElementById('file-input');
  const uploadBtn        = document.getElementById('upload-btn');
  const voiceBtn         = document.getElementById('voice-btn');
  const modelSelect      = document.getElementById('model-select');

  // New UI elements
  const sidebar          = document.getElementById('sidebar');
  const newChatBtn       = document.getElementById('new-chat-btn');
  const conversationList = document.getElementById('conversation-list');
  const mainArea         = document.getElementById('main-area');
  const greetingSection  = document.getElementById('greeting');
  const chatContainer    = document.getElementById('chat-container');
  const toggleSidebarBtn = document.getElementById('toggle-sidebar');
  const suggestionButtons= document.querySelectorAll('.suggestion');
  // Backdrop for mobile overlay
  const backdrop         = document.getElementById('mobile-backdrop');

  // Temporary list of attachments selected by the user. Each entry
  // contains a `name`, `data_url` and optional `url` returned from /api/upload.
  let attachmentsToSend = [];

  // Currently selected model. Will be populated after fetching models.
  let currentModel = null;

  // Element used to display a typing/thinking indicator while waiting
  // for the assistant's response. When non-null, this will be a DOM
  // element appended to the chat area. Helper functions defined below
  // manage its lifecycle. The indicator shows a placeholder message
  // (e.g. "Pensando...") so users know the model is processing.
  let typingIndicator = null;
  // Interval ID for updating the typing indicator with animated dots
  let typingInterval = null;

  /**
   * Display a temporary typing indicator at the end of the chat. If one
   * already exists, it will be removed before a new one is appended. The
   * indicator mimics a message from the assistant and uses a special
   * CSS class to differentiate it visually.
   */
  function showTypingIndicator() {
    removeTypingIndicator();
    typingIndicator = document.createElement('div');
    typingIndicator.classList.add('message', 'assistant', 'typing');
    // Base text without dots; will be updated in an interval
    const baseText = 'Pensando';
    typingIndicator.textContent = baseText + '.';
    chatArea.appendChild(typingIndicator);
    scrollToBottom();
    // Animate the dots periodically
    let dotCount = 1;
    typingInterval = setInterval(() => {
      dotCount = (dotCount + 1) % 4; // cycle through 0–3 dots
      typingIndicator.textContent = baseText + '.'.repeat(dotCount || 1);
    }, 500);
  }

  /**
   * Remove the existing typing indicator from the chat area if present.
   */
  function removeTypingIndicator() {
    if (typingIndicator) {
      typingIndicator.remove();
      typingIndicator = null;
    }
    if (typingInterval) {
      clearInterval(typingInterval);
      typingInterval = null;
    }
  }

  // Conversations state fetched from the server. Each entry has an `id` and `title`.
  // Messages are not stored here; they are retrieved on demand.
  let conversations = [];
  let currentConversationIndex = -1;

  // Scroll chat area to the bottom
  function scrollToBottom() {
    chatArea.scrollTop = chatArea.scrollHeight;
  }

  /**
   * Append a new message element to the chat area.
   * Optionally include attachments (images, videos or other files).
   * @param {string} role Either 'user' or 'assistant'.
   * @param {string} text Message content to display.
   * @param {Array<{name: string, data_url: string, url?: string}>} attachments
   */
  function appendMessage(role, text, attachments = []) {
    const msgDiv = document.createElement('div');
    msgDiv.classList.add('message', role);
    msgDiv.textContent = text;
    if (attachments.length) {
      const attsDiv = document.createElement('div');
      attsDiv.classList.add('attachments');
      attachments.forEach(att => {
        const attDiv = document.createElement('div');
        attDiv.classList.add('attachment');
        if (att.data_url && att.data_url.startsWith('data:image')) {
          const img = document.createElement('img');
          img.src = att.data_url;
          img.alt = att.name;
          attDiv.appendChild(img);
        } else if (att.data_url && att.data_url.startsWith('data:video')) {
          const video = document.createElement('video');
          video.src = att.data_url;
          video.controls = true;
          attDiv.appendChild(video);
        } else {
          const link = document.createElement('a');
          link.href = att.url || att.data_url;
          link.download = att.name;
          link.textContent = att.name;
          link.style.color = '#0d274d';
          link.style.textDecoration = 'underline';
          attDiv.appendChild(link);
        }
        attsDiv.appendChild(attDiv);
      });
      msgDiv.appendChild(attsDiv);
    }
    chatArea.appendChild(msgDiv);
    scrollToBottom();
    // Update current conversation summary
    if (currentConversationIndex >= 0 && role === 'user') {
      const conv = conversations.find(c => c.id === currentConversationIndex);
      if (conv && (!conv.title || conv.title === 'Nueva conversación')) {
        conv.title = text.substring(0, 30);
        renderConversationList();
      }
    }
  }

  /**
   * Fetch available models from the backend and populate the dropdown.
   */
  async function populateModels() {
    try {
      const res = await fetch('/api/models');
      if (!res.ok) throw new Error('Error fetching models');
      const data = await res.json();
      const models = data.models || [];
      modelSelect.innerHTML = '';
      models.forEach(model => {
        const opt = document.createElement('option');
        opt.value = model;
        opt.textContent = model;
        modelSelect.appendChild(opt);
      });
      if (models.length > 0) {
        currentModel = models[0];
        modelSelect.value = currentModel;
      }
      modelSelect.addEventListener('change', (e) => {
        currentModel = e.target.value;
        // Reset the conversation on the server when changing models
        fetch('/api/reset_history', { method: 'POST' })
          .then(() => {
            appendMessage('assistant', `Modelo cambiado a ${currentModel}`);
          })
          .catch(() => {
            appendMessage('assistant', 'Modelo cambiado pero no se pudo reiniciar la conversación en el servidor.');
          });
      });
    } catch (err) {
      console.error(err);
      modelSelect.innerHTML = '<option value="">Sin modelos</option>';
    }
  }

  /**
   * Fetch the list of conversations from the server and update the sidebar list.
   * Each conversation summary has an `id` and `title`.
   */
  async function fetchConversations() {
    try {
      const res = await fetch('/api/conversations');
      if (!res.ok) throw new Error('Error fetching conversations');
      const data = await res.json();
      conversations = data.conversations || [];
      if (conversations.length > 0 && (currentConversationIndex === -1 || currentConversationIndex === undefined)) {
        currentConversationIndex = conversations[0].id;
      }
      renderConversationList();
    } catch (err) {
      console.error(err);
      conversations = [];
      renderConversationList();
    }
  }

  // Handle file upload button click
  uploadBtn.addEventListener('click', () => fileInput.click());

  // When files are selected, send them to the backend to get data URLs
  fileInput.addEventListener('change', async (event) => {
    const files = Array.from(event.target.files);
    if (!files.length) return;
    const formData = new FormData();
    files.forEach(f => formData.append('files', f));
    try {
      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData
      });
      if (!res.ok) throw new Error('Error uploading files');
      const data = await res.json();
      if (data.files) {
        attachmentsToSend.push(...data.files);
        appendMessage('user', '[Archivos adjuntos preparados]', data.files);
      }
      fileInput.value = '';
    } catch (err) {
      console.error(err);
      alert('Hubo un problema al subir los archivos');
    }
  });

  // Speech recognition
  let recognition;
  if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.lang = 'es-MX';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      messageInput.value += transcript + ' ';
    };
    recognition.onerror = (event) => {
      console.error(event.error);
    };
  }
  voiceBtn.addEventListener('click', () => {
    if (!recognition) {
      alert('Tu navegador no soporta reconocimiento de voz');
      return;
    }
    recognition.start();
  });

  // Handle form submission to send a message
  messageForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = messageInput.value.trim();
    if (!text && attachmentsToSend.length === 0) {
      return;
    }
    // If this is the first message of a new chat, show chat container
    if (chatContainer.classList.contains('hidden')) {
      greetingSection.classList.add('hidden');
      chatContainer.classList.remove('hidden');
      if (currentConversationIndex === -1 || currentConversationIndex === undefined) {
        conversations.push({ id: null, title: '', messages: [] });
        currentConversationIndex = conversations.length - 1;
      }
    }
    // Append the user's message to the chat area
    appendMessage('user', text, attachmentsToSend);
    // Show a typing indicator so the user knows the assistant is processing
    showTypingIndicator();
    const payload = {
      message: text,
      attachments: attachmentsToSend.map(att => ({ name: att.name, data_url: att.data_url, url: att.url })),
      model: currentModel
    };
    messageInput.value = '';
    attachmentsToSend = [];
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error('Error from chat API');
      const data = await res.json();
      // Remove typing indicator before showing the real response
      removeTypingIndicator();
      if (data.message) {
        appendMessage('assistant', data.message);
      }
    } catch (err) {
      console.error(err);
      // Remove typing indicator in case of error
      removeTypingIndicator();
      appendMessage('assistant', 'Hubo un error al contactar al modelo');
    }
  });

  // Handle new chat button
  if (newChatBtn) {
    newChatBtn.addEventListener('click', () => {
      fetch('/api/new_chat', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
          // Clear current chat and attachments
          chatArea.innerHTML = '';
          attachmentsToSend = [];
          // Remove any typing indicator that might still be displayed
          removeTypingIndicator();
          // Show the greeting and hide the chat container
          greetingSection.classList.remove('hidden');
          chatContainer.classList.add('hidden');
          currentConversationIndex = data.id;
          fetchConversations();
        });
    });
  }

  // Sidebar visibility toggle with responsive behaviour
  const setInitialSidebarState = () => {
    if (window.innerWidth <= 768) {
      sidebar.classList.remove('collapsed');
      sidebar.classList.remove('open');
      if (backdrop) backdrop.classList.remove('show');
    } else {
      sidebar.classList.remove('open');
      sidebar.classList.remove('collapsed');
      if (backdrop) backdrop.classList.remove('show');
    }
  };
  setInitialSidebarState();

  if (toggleSidebarBtn) {
    toggleSidebarBtn.addEventListener('click', () => {
      if (window.innerWidth <= 768) {
        const open = sidebar.classList.toggle('open');
        if (backdrop) backdrop.classList.toggle('show', open);
      } else {
        sidebar.classList.toggle('collapsed');
      }
    });
  }

  // Close sidebar when clicking outside in mobile view
  if (backdrop) {
    backdrop.addEventListener('click', () => {
      sidebar.classList.remove('open');
      backdrop.classList.remove('show');
    });
  }

  // Populate suggestions events
  suggestionButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      messageInput.value = btn.textContent;
      messageInput.focus();
    });
  });

  // Render conversation list and attach click handlers
  function renderConversationList() {
    conversationList.innerHTML = '';
    conversations.forEach((conv) => {
      const li = document.createElement('li');
      li.dataset.id = conv.id;
      if (conv.id === currentConversationIndex) {
        li.classList.add('active');
      }
      // Title span showing first user message or default
      const titleSpan = document.createElement('span');
      titleSpan.classList.add('conv-title');
      titleSpan.textContent = conv.title || 'Nueva conversación';
      // Delete button with icon
      const deleteBtn = document.createElement('button');
      deleteBtn.classList.add('delete-btn');
      const delImg = document.createElement('img');
      delImg.src = '/static/icons/trash.png';
      delImg.alt = 'Eliminar';
      deleteBtn.appendChild(delImg);
      // Attach deletion handler
      deleteBtn.addEventListener('click', async (e) => {
        // Prevent triggering the conversation selection
        e.stopPropagation();
        const convId = conv.id;
        if (!confirm('¿Eliminar conversación?')) return;
        try {
          const res = await fetch(`/api/conversations/${convId}/delete`, { method: 'POST' });
          const data = await res.json();
          if (data.success) {
            // If current conversation was deleted, reset the view
            if (currentConversationIndex === convId) {
              chatArea.innerHTML = '';
              removeTypingIndicator();
              greetingSection.classList.remove('hidden');
              chatContainer.classList.add('hidden');
              currentConversationIndex = -1;
            }
            // Refresh conversations list from server
            fetchConversations();
          }
        } catch (err) {
          console.error(err);
        }
      });
      // Click handler to load conversation
      li.addEventListener('click', async () => {
        const convId = conv.id;
        try {
          const res = await fetch(`/api/conversations/${convId}`);
          if (!res.ok) throw new Error('Error loading conversation');
          const data = await res.json();
          chatArea.innerHTML = '';
          removeTypingIndicator();
          data.messages.forEach(msg => {
            const role = msg.role === 'assistant' ? 'assistant' : 'user';
            appendMessage(role, msg.content);
          });
          greetingSection.classList.add('hidden');
          chatContainer.classList.remove('hidden');
          currentConversationIndex = convId;
          renderConversationList();
          if (window.innerWidth <= 768 && backdrop) {
            sidebar.classList.remove('open');
            backdrop.classList.remove('show');
          }
        } catch (err) {
          console.error(err);
        }
      });
      // Assemble and append
      li.appendChild(titleSpan);
      li.appendChild(deleteBtn);
      conversationList.appendChild(li);
    });
  }

  // Recalculate sidebar state on resize
  window.addEventListener('resize', setInitialSidebarState);

  // Fetch models and conversations on load
  populateModels();
  fetchConversations();
});