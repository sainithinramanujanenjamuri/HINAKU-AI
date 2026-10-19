// HINAKU UI Client with SQLite History & Sidebar
document.addEventListener("DOMContentLoaded", () => {
  const messagesContainer = document.getElementById("messages-container");
  const promptInput = document.getElementById("prompt-input");
  const sendButton = document.getElementById("send-button");
  const modelBadge = document.getElementById("model-badge");
  const statusIndicator = document.getElementById("status-indicator");
  const noticeBanner = document.getElementById("notice-banner");
  const noticeText = document.getElementById("notice-text");
  const conversationsList = document.getElementById("conversations-list");
  const newChatBtn = document.getElementById("new-chat-btn");
  const sidebar = document.getElementById("sidebar");
  const sidebarToggleBtn = document.getElementById("sidebar-toggle-btn");
  const sidebarCloseBtn = document.getElementById("sidebar-close-btn");
  const sidebarOverlay = document.getElementById("sidebar-overlay");

  let currentConversationId = null;
  let isGenerating = false;
  let activeAbortController = null;

  // Initialize marked settings
  if (window.marked) {
    marked.setOptions({
      breaks: true,
      gfm: true
    });
  }

  function updatePersonaNotice(isFallback, notice) {
    if (!noticeBanner || !noticeText) return;
    if (isFallback) {
      noticeText.textContent = notice || "Persona file missing or empty. Using neutral fallback prompt.";
      noticeBanner.classList.remove("hidden");
    } else {
      noticeBanner.classList.add("hidden");
    }
  }

  // Fetch status info
  async function checkInfo() {
    try {
      const res = await fetch("/api/info");
      if (res.ok) {
        const data = await res.json();
        const modelName = data.default_model || "qwen3.5:4b";
        modelBadge.textContent = `${modelName} • local`;
        if (data.ollama_status && data.ollama_status.online) {
          statusIndicator.classList.remove("offline");
          statusIndicator.title = "Ollama online";
        } else {
          statusIndicator.classList.add("offline");
          statusIndicator.title = "Ollama offline or model not found";
        }
        if (data.persona) {
          updatePersonaNotice(data.persona.is_fallback, data.persona.notice);
        }
      }
    } catch (e) {
      statusIndicator.classList.add("offline");
      statusIndicator.title = "Backend unreachable";
    }
  }

  checkInfo();

  // Sidebar toggle behavior
  function toggleSidebar() {
    const isMobile = window.innerWidth <= 768;
    if (isMobile) {
      sidebar.classList.toggle("open");
      sidebarOverlay.classList.toggle("active");
    } else {
      sidebar.classList.toggle("collapsed");
    }
  }

  function closeMobileSidebar() {
    sidebar.classList.remove("open");
    sidebarOverlay.classList.remove("active");
  }

  sidebarToggleBtn.addEventListener("click", toggleSidebar);
  if (sidebarCloseBtn) sidebarCloseBtn.addEventListener("click", closeMobileSidebar);
  sidebarOverlay.addEventListener("click", closeMobileSidebar);

  // Conversations List & Management
  async function loadConversations() {
    try {
      const res = await fetch("/api/conversations");
      if (!res.ok) return;
      const convs = await res.json();

      conversationsList.innerHTML = "";
      if (convs.length === 0) {
        const empty = document.createElement("div");
        empty.style.padding = "12px 14px";
        empty.style.color = "var(--text-dim)";
        empty.style.fontSize = "12px";
        empty.textContent = "No conversations yet";
        conversationsList.appendChild(empty);
        return;
      }

      convs.forEach((c) => {
        const item = document.createElement("div");
        item.className = `conversation-item ${c.id === currentConversationId ? "active" : ""}`;
        item.dataset.id = c.id;

        const titleSpan = document.createElement("span");
        titleSpan.className = "conv-title";
        titleSpan.textContent = c.title || "Untitled";
        titleSpan.title = c.title || "Untitled";

        const actionsDiv = document.createElement("div");
        actionsDiv.className = "conv-actions";

        // Rename button
        const renameBtn = document.createElement("button");
        renameBtn.className = "conv-btn";
        renameBtn.title = "Rename conversation";
        renameBtn.innerHTML = `
          <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none">
            <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path>
          </svg>
        `;
        renameBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          startInlineRename(item, c.id, c.title);
        });

        // Delete button
        const deleteBtn = document.createElement("button");
        deleteBtn.className = "conv-btn delete-btn";
        deleteBtn.title = "Delete conversation";
        deleteBtn.innerHTML = `
          <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          </svg>
        `;
        deleteBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          if (confirm(`Permanently delete "${c.title}"?`)) {
            await deleteConversation(c.id);
          }
        });

        actionsDiv.appendChild(renameBtn);
        actionsDiv.appendChild(deleteBtn);

        item.appendChild(titleSpan);
        item.appendChild(actionsDiv);

        item.addEventListener("click", () => {
          openConversation(c.id);
        });

        conversationsList.appendChild(item);
      });
    } catch (e) {
      console.error("Failed to load conversations:", e);
    }
  }

  function startInlineRename(itemDiv, convId, currentTitle) {
    const titleSpan = itemDiv.querySelector(".conv-title");
    const actionsDiv = itemDiv.querySelector(".conv-actions");
    if (!titleSpan) return;

    actionsDiv.style.display = "none";
    const input = document.createElement("input");
    input.type = "text";
    input.className = "rename-input";
    input.value = currentTitle;

    titleSpan.replaceWith(input);
    input.focus();
    input.select();

    async function finishRename() {
      const newTitle = input.value.trim() || currentTitle;
      try {
        await fetch(`/api/conversations/${convId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: newTitle })
        });
      } catch (e) {
        console.error("Error renaming:", e);
      }
      loadConversations();
    }

    input.addEventListener("blur", finishRename);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        input.removeEventListener("blur", finishRename);
        finishRename();
      } else if (e.key === "Escape") {
        input.removeEventListener("blur", finishRename);
        loadConversations();
      }
    });
  }

  async function openConversation(convId) {
    if (isGenerating) return;
    try {
      const res = await fetch(`/api/conversations/${convId}`);
      if (!res.ok) return;
      const conv = await res.json();

      currentConversationId = conv.id;
      messagesContainer.innerHTML = "";

      if (conv.messages && conv.messages.length > 0) {
        conv.messages.forEach((m) => {
          renderMessage(m.role, m.content);
        });
      } else {
        renderIntroMessage();
      }

      loadConversations();
      closeMobileSidebar();
      promptInput.focus();
    } catch (e) {
      console.error("Error opening conversation:", e);
    }
  }

  async function deleteConversation(convId) {
    try {
      await fetch(`/api/conversations/${convId}`, { method: "DELETE" });
      if (currentConversationId === convId) {
        startNewChat();
      } else {
        loadConversations();
      }
    } catch (e) {
      console.error("Error deleting conversation:", e);
    }
  }

  function renderIntroMessage() {
    messagesContainer.innerHTML = `
      <div class="message assistant intro-message">
        <div class="message-meta">
          <span class="sender-name">HINAKU</span>
        </div>
        <div class="message-body">
          I am HINAKU. I am listening.
        </div>
      </div>
    `;
  }

  function startNewChat() {
    if (isGenerating) return;
    currentConversationId = null;
    renderIntroMessage();
    loadConversations();
    closeMobileSidebar();
    promptInput.focus();
  }

  newChatBtn.addEventListener("click", startNewChat);

  // Auto-resize input
  promptInput.addEventListener("input", () => {
    promptInput.style.height = "auto";
    promptInput.style.height = `${Math.min(promptInput.scrollHeight, 160)}px`;
  });

  promptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  sendButton.addEventListener("click", () => {
    sendMessage();
  });

  function renderMessage(role, content, isStreaming = false) {
    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${role}`;

    const metaDiv = document.createElement("div");
    metaDiv.className = "message-meta";
    metaDiv.textContent = role === "user" ? "You" : "HINAKU";
    msgDiv.appendChild(metaDiv);

    const bodyDiv = document.createElement("div");
    bodyDiv.className = "message-body";

    if (role === "assistant") {
      if (window.marked && content) {
        bodyDiv.innerHTML = marked.parse(content);
      } else {
        bodyDiv.textContent = content;
      }
      if (isStreaming) {
        const cursor = document.createElement("span");
        cursor.className = "streaming-cursor";
        bodyDiv.appendChild(cursor);
      }
      attachCopyButtons(bodyDiv);
    } else {
      bodyDiv.textContent = content;
    }

    msgDiv.appendChild(bodyDiv);
    messagesContainer.appendChild(msgDiv);
    scrollToBottom();
    return { msgDiv, bodyDiv };
  }

  function attachCopyButtons(container) {
    const preBlocks = container.querySelectorAll("pre");
    preBlocks.forEach((pre) => {
      if (!pre.querySelector(".copy-btn")) {
        const btn = document.createElement("button");
        btn.className = "copy-btn";
        btn.textContent = "Copy";
        btn.addEventListener("click", () => {
          const code = pre.querySelector("code") ? pre.querySelector("code").innerText : pre.innerText;
          navigator.clipboard.writeText(code).then(() => {
            btn.textContent = "Copied!";
            setTimeout(() => (btn.textContent = "Copy"), 2000);
          });
        });
        pre.appendChild(btn);
      }
    });
  }

  function scrollToBottom() {
    const chatContainer = document.querySelector(".chat-container");
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  async function sendMessage() {
    const text = promptInput.value.trim();
    if (!text || isGenerating) return;

    // Reset input
    promptInput.value = "";
    promptInput.style.height = "auto";
    sendButton.disabled = true;
    isGenerating = true;

    // Append user message
    renderMessage("user", text);

    // Create assistant message placeholder
    let assistantText = "";
    const { bodyDiv } = renderMessage("assistant", "", true);

    activeAbortController = new AbortController();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [{ role: "user", content: text }],
          conversation_id: currentConversationId,
          stream: true
        }),
        signal: activeAbortController.signal
      });

      if (!response.ok) {
        throw new Error(`Server returned status ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop();

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;
          const dataStr = trimmed.slice(5).trim();

          if (dataStr === "[DONE]") {
            break;
          }

          try {
            const parsed = JSON.parse(dataStr);
            if (parsed.conversation_id) {
              currentConversationId = parsed.conversation_id;
            }
            if (parsed.persona_fallback !== undefined) {
              updatePersonaNotice(parsed.persona_fallback, parsed.notice);
            }
            if (parsed.chunk) {
              assistantText += parsed.chunk;
              if (window.marked) {
                bodyDiv.innerHTML = marked.parse(assistantText);
              } else {
                bodyDiv.textContent = assistantText;
              }
              const cursor = document.createElement("span");
              cursor.className = "streaming-cursor";
              bodyDiv.appendChild(cursor);
              attachCopyButtons(bodyDiv);
              scrollToBottom();
            }
          } catch (e) {
            console.error("Failed to parse SSE line:", line, e);
          }
        }
      }

      const cursor = bodyDiv.querySelector(".streaming-cursor");
      if (cursor) cursor.remove();
      attachCopyButtons(bodyDiv);

      // Refresh sidebar so newly titled or updated conversation reflects at top
      loadConversations();

    } catch (err) {
      if (err.name !== "AbortError") {
        bodyDiv.innerHTML = `<span style="color: #ef4444;">[Error: ${err.message}]</span>`;
      }
    } finally {
      isGenerating = false;
      sendButton.disabled = false;
      promptInput.focus();
    }
  }

  // Load initial conversations
  loadConversations();

  // Subtle starfield ambient canvas
  initStarfield();

  function initStarfield() {
    const canvas = document.getElementById("starfield");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    window.addEventListener("resize", () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    });

    const starCount = 65;
    const stars = [];

    for (let i = 0; i < starCount; i++) {
      stars.push({
        x: Math.random() * width,
        y: Math.random() * height,
        radius: Math.random() * 1.2 + 0.3,
        alpha: Math.random() * 0.6 + 0.1,
        speed: Math.random() * 0.15 + 0.05
      });
    }

    function render() {
      ctx.clearRect(0, 0, width, height);

      for (let s of stars) {
        s.y -= s.speed;
        if (s.y < 0) {
          s.y = height;
          s.x = Math.random() * width;
        }

        ctx.beginPath();
        ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(180, 190, 220, ${s.alpha})`;
        ctx.fill();
      }

      requestAnimationFrame(render);
    }

    render();
  }
});
