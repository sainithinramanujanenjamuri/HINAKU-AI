// HINAKU UI Client with Model Router, Private Chat & Backend Badges
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
  const privateToggleBtn = document.getElementById("private-toggle-btn");
  const privacyIcon = document.getElementById("privacy-icon");
  const privacyLabel = document.getElementById("privacy-label");

  let currentConversationId = null;
  let isCurrentChatPrivate = false;
  let isGenerating = false;
  let activeAbortController = null;
  let isApiLoggedByProvider = false;

  // Initialize marked settings
  if (window.marked) {
    marked.setOptions({
      breaks: true,
      gfm: true
    });
  }

  function formatMarkdown(text) {
    if (!text) return "";
    // Preprocess: ensure bold heading directly after a list item renders as its own paragraph
    const normalized = text.replace(/((?:^|\n)[ \t]*(?:[-*+]|\d+\.)[^\n]+)\n([ \t]*\*\*[^*]+?\*\*.*)/g, "$1\n\n$2");
    return window.marked ? marked.parse(normalized) : normalized;
  }

  function updateFooterBackend(backend) {
    const footerEl = document.getElementById("footer-backend");
    if (!footerEl) return;
    if (!backend) {
      footerEl.textContent = "Local inference";
      return;
    }
    const b = backend.toLowerCase();
    if (b === "guard") {
      footerEl.textContent = "guard (local)";
    } else {
      footerEl.textContent = b === "api" ? "API" : "local";
    }
  }

  function getBackendBadgeText(backend, model) {
    const bKind = (backend || "local").toLowerCase();
    if (bKind === "guard") {
      return "security guard · local";
    }
    const mName = model ? model.split("/").pop() : "local";
    if (bKind === "api") {
      return isApiLoggedByProvider ? "API · logged by provider" : `${mName} · API`;
    }
    return `${mName} · local`;
  }

  function updateNoticeBanner(visible, message) {
    if (!noticeBanner || !noticeText) return;
    if (visible && message) {
      noticeText.textContent = message;
      noticeBanner.classList.remove("hidden");
    } else {
      noticeBanner.classList.add("hidden");
    }
  }

  function updatePrivacyUI(isPrivate) {
    isCurrentChatPrivate = isPrivate;
    if (isPrivate) {
      privateToggleBtn.classList.add("active");
      if (privacyIcon) privacyIcon.textContent = "🔒";
      if (privacyLabel) privacyLabel.textContent = "Private (Local)";
      privateToggleBtn.title = "Private Chat: Stays strictly on this laptop (never uses API)";
    } else {
      privateToggleBtn.classList.remove("active");
      if (privacyIcon) privacyIcon.textContent = "🔓";
      if (privacyLabel) privacyLabel.textContent = "Standard";
      privateToggleBtn.title = "Standard Chat: Uses hybrid auto router (Local + API)";
    }
  }

  // Toggle privacy button
  privateToggleBtn.addEventListener("click", async () => {
    const newState = !isCurrentChatPrivate;
    updatePrivacyUI(newState);
    if (!currentConversationId) {
      try {
        const res = await fetch("/api/conversations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_private: newState, title: "New conversation" })
        });
        if (res.ok) {
          const conv = await res.json();
          currentConversationId = conv.id;
          loadConversations();
        }
      } catch (e) {
        console.error("Failed to create private conversation:", e);
      }
    } else {
      try {
        await fetch(`/api/conversations/${currentConversationId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_private: newState })
        });
        loadConversations();
      } catch (e) {
        console.error("Failed to update privacy:", e);
      }
    }
  });

  // Fetch status info
  async function checkInfo() {
    try {
      const res = await fetch("/api/info");
      if (res.ok) {
        const data = await res.json();
        const mode = data.router?.mode || "auto";
        const localModel = data.default_model || "qwen3.5:4b";
        modelBadge.textContent = `${mode} • ${localModel}`;

        if (data.router && data.router.api_logged_by_provider !== undefined) {
          isApiLoggedByProvider = Boolean(data.router.api_logged_by_provider);
        }

        if (data.ollama_status && data.ollama_status.online) {
          statusIndicator.classList.remove("offline");
          statusIndicator.title = "Ollama online";
        } else {
          statusIndicator.classList.add("offline");
          statusIndicator.title = "Ollama offline or model not found";
        }

        if (data.persona && data.persona.is_fallback) {
          updateNoticeBanner(true, data.persona.notice);
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

        const titleWrapper = document.createElement("span");
        titleWrapper.className = "conv-title";
        if (c.is_private) {
          titleWrapper.innerHTML = `<span style="font-size: 11px; margin-right: 4px;">🔒</span>${escapeHtml(c.title || "Untitled")}`;
        } else {
          titleWrapper.textContent = c.title || "Untitled";
        }
        titleWrapper.title = c.title || "Untitled";

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

        item.appendChild(titleWrapper);
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

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
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
      updatePrivacyUI(Boolean(conv.is_private));
      messagesContainer.innerHTML = "";

      if (conv.messages && conv.messages.length > 0) {
        let lastAssistantBackend = null;
        conv.messages.forEach((m) => {
          renderMessage(m.role, m.content, false, m.model, m.backend);
          if (m.role === "assistant" && m.backend) {
            lastAssistantBackend = m.backend;
          }
        });
        updateFooterBackend(lastAssistantBackend || "local");
      } else {
        renderIntroMessage();
        updateFooterBackend("local");
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
          <span class="backend-tag local">local</span>
        </div>
        <div class="message-body">
          I am HINAKU. I am listening.
        </div>
      </div>
    `;
    updateFooterBackend("local");
  }

  function startNewChat() {
    if (isGenerating) return;
    currentConversationId = null;
    updatePrivacyUI(false);
    renderIntroMessage();
    updateFooterBackend("local");
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

  function renderMessage(role, content, isStreaming = false, model = null, backend = null) {
    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${role}`;

    const metaDiv = document.createElement("div");
    metaDiv.className = "message-meta";

    if (role === "user") {
      metaDiv.textContent = "You";
    } else {
      const nameSpan = document.createElement("span");
      nameSpan.className = "sender-name";
      nameSpan.textContent = "HINAKU";
      metaDiv.appendChild(nameSpan);

      const tag = document.createElement("span");
      const bKind = (backend || "local").toLowerCase();
      tag.className = `backend-tag ${bKind}`;
      tag.dataset.tag = "backend";
      tag.textContent = getBackendBadgeText(backend, model);
      metaDiv.appendChild(tag);
    }
    msgDiv.appendChild(metaDiv);

    const bodyDiv = document.createElement("div");
    bodyDiv.className = "message-body";

    if (role === "assistant") {
      if (content) {
        bodyDiv.innerHTML = formatMarkdown(content);
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
    return { msgDiv, metaDiv, bodyDiv };
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
    const { metaDiv, bodyDiv } = renderMessage("assistant", "", true, "routing...", "local");

    activeAbortController = new AbortController();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [{ role: "user", content: text }],
          conversation_id: currentConversationId,
          is_private: isCurrentChatPrivate,
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
            if (parsed.notice) {
              updateNoticeBanner(true, parsed.notice);
            }
            if (parsed.logged_by_provider !== undefined) {
              isApiLoggedByProvider = Boolean(parsed.logged_by_provider);
            }
            if (parsed.backend) {
              updateFooterBackend(parsed.backend);
              const bTag = metaDiv.querySelector("[data-tag='backend']");
              if (bTag) {
                const bKind = parsed.backend.toLowerCase();
                bTag.className = `backend-tag ${bKind}`;
                bTag.textContent = getBackendBadgeText(parsed.backend, parsed.model);
              }
            }
            if (parsed.chunk) {
              assistantText += parsed.chunk;
              bodyDiv.innerHTML = formatMarkdown(assistantText);
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

  // --- Memory Drawer Logic ---
  const memoryDrawer = document.getElementById("memory-drawer");
  const memoryToggleBtn = document.getElementById("memory-toggle-btn");
  const drawerCloseBtn = document.getElementById("drawer-close-btn");
  const drawerOverlay = document.getElementById("drawer-overlay");
  const reindexMemoryBtn = document.getElementById("reindex-memory-btn");
  const memorySearchInput = document.getElementById("memory-search-input");
  const memoriesContainer = document.getElementById("memories-container");

  let allMemories = [];

  async function loadMemories() {
    if (!memoriesContainer) return;
    try {
      memoriesContainer.innerHTML = '<div class="empty-state">Loading memories...</div>';
      const res = await fetch("/api/memories");
      if (res.ok) {
        allMemories = await res.json();
        renderMemories(allMemories);
      } else {
        memoriesContainer.innerHTML = '<div class="empty-state">Failed to load memories.</div>';
      }
    } catch (e) {
      memoriesContainer.innerHTML = `<div class="empty-state">Error: ${e.message}</div>`;
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/[&<>'"]/g, tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag));
  }

  function renderMemories(memories) {
    if (!memoriesContainer) return;
    if (!memories || memories.length === 0) {
      memoriesContainer.innerHTML = '<div class="empty-state">No memories recorded yet.<br><br>HINAKU extracts facts about you automatically as you converse.</div>';
      return;
    }

    memoriesContainer.innerHTML = "";
    memories.forEach(mem => {
      const card = document.createElement("div");
      card.className = "memory-card";
      card.id = `memory-${mem.id}`;

      let dateStr = "";
      try {
        dateStr = new Date(mem.updated_at || mem.created_at).toLocaleDateString(undefined, {
          month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
        });
      } catch (e) {
        dateStr = mem.updated_at || mem.created_at || "";
      }

      card.innerHTML = `
        <div class="memory-card-text" id="memory-text-${mem.id}">${escapeHtml(mem.text)}</div>
        <div class="memory-card-footer">
          <span class="memory-date">${dateStr}</span>
          <div class="memory-card-actions">
            <button class="memory-btn-icon memory-btn-edit" title="Edit memory" data-id="${mem.id}">✏️</button>
            <button class="memory-btn-icon memory-btn-delete" title="Delete memory" data-id="${mem.id}">🗑️</button>
          </div>
        </div>
      `;

      card.querySelector(".memory-btn-edit").addEventListener("click", () => editMemoryInline(mem));
      card.querySelector(".memory-btn-delete").addEventListener("click", () => deleteMemoryItem(mem.id));

      memoriesContainer.appendChild(card);
    });
  }

  function editMemoryInline(mem) {
    const card = document.getElementById(`memory-${mem.id}`);
    if (!card) return;

    card.innerHTML = `
      <textarea class="memory-edit-area" id="edit-area-${mem.id}">${escapeHtml(mem.text)}</textarea>
      <div class="memory-edit-controls">
        <button class="btn-small" id="cancel-edit-${mem.id}">Cancel</button>
        <button class="btn-small primary" id="save-edit-${mem.id}">Save</button>
      </div>
    `;

    document.getElementById(`cancel-edit-${mem.id}`).addEventListener("click", () => renderMemories(allMemories));
    document.getElementById(`save-edit-${mem.id}`).addEventListener("click", async () => {
      const newText = document.getElementById(`edit-area-${mem.id}`).value.trim();
      if (!newText) return;
      try {
        const res = await fetch(`/api/memories/${mem.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: newText })
        });
        if (res.ok) {
          const updated = await res.json();
          const idx = allMemories.findIndex(m => m.id === mem.id);
          if (idx !== -1) allMemories[idx] = updated;
          renderMemories(allMemories);
        }
      } catch (e) {
        alert("Failed to update memory: " + e.message);
      }
    });
  }

  async function deleteMemoryItem(memId) {
    if (!confirm("Permanently delete this memory?")) return;
    try {
      const res = await fetch(`/api/memories/${memId}`, { method: "DELETE" });
      if (res.ok) {
        allMemories = allMemories.filter(m => m.id !== memId);
        renderMemories(allMemories);
      }
    } catch (e) {
      alert("Failed to delete memory: " + e.message);
    }
  }

  if (memoryToggleBtn) {
    memoryToggleBtn.addEventListener("click", () => {
      const isClosed = memoryDrawer.classList.contains("closed");
      if (isClosed) {
        memoryDrawer.classList.remove("closed");
        if (drawerOverlay) drawerOverlay.classList.add("active");
        loadMemories();
      } else {
        memoryDrawer.classList.add("closed");
        if (drawerOverlay) drawerOverlay.classList.remove("active");
      }
    });
  }

  if (drawerCloseBtn) {
    drawerCloseBtn.addEventListener("click", () => {
      memoryDrawer.classList.add("closed");
      if (drawerOverlay) drawerOverlay.classList.remove("active");
    });
  }

  if (drawerOverlay) {
    drawerOverlay.addEventListener("click", () => {
      memoryDrawer.classList.add("closed");
      drawerOverlay.classList.remove("active");
    });
  }

  if (reindexMemoryBtn) {
    reindexMemoryBtn.addEventListener("click", async () => {
      reindexMemoryBtn.textContent = "Indexing...";
      reindexMemoryBtn.disabled = true;
      try {
        const res = await fetch("/api/memories/reindex", { method: "POST" });
        if (res.ok) {
          const data = await res.json();
          alert(`Re-indexed ${data.count} memories into ChromaDB.`);
          loadMemories();
        }
      } catch (e) {
        alert("Re-index failed: " + e.message);
      } finally {
        reindexMemoryBtn.textContent = "Re-index";
        reindexMemoryBtn.disabled = false;
      }
    });
  }

  if (memorySearchInput) {
    memorySearchInput.addEventListener("input", (e) => {
      const query = e.target.value.toLowerCase().trim();
      if (!query) {
        renderMemories(allMemories);
      } else {
        const filtered = allMemories.filter(m => m.text.toLowerCase().includes(query));
        renderMemories(filtered);
      }
    });
  }

  // --- Settings Modal Logic ---
  const settingsToggleBtn = document.getElementById("settings-toggle-btn");
  const settingsModal = document.getElementById("settings-modal");
  const settingsCloseBtn = document.getElementById("settings-close-btn");
  const settingMemoryEnabled = document.getElementById("setting-memory-enabled");
  const settingReducedMotion = document.getElementById("setting-reduced-motion");
  const btnExportData = document.getElementById("btn-export-data");
  const btnClearMemory = document.getElementById("btn-clear-memory");
  const btnWipeAll = document.getElementById("btn-wipe-all");
  const btnRunSelfbuild = document.getElementById("btn-run-selfbuild");
  const selfbuildStatus = document.getElementById("selfbuild-status");
  const routerRadios = document.querySelectorAll("input[name='router-mode-radio']");

  async function openSettings() {
    if (!settingsModal) return;
    settingsModal.classList.remove("hidden");
    try {
      const res = await fetch("/api/settings");
      if (res.ok) {
        const s = await res.json();
        routerRadios.forEach(r => {
          r.checked = (r.value === s.router_mode);
        });
        if (settingMemoryEnabled) settingMemoryEnabled.checked = s.memory_enabled;
        if (settingReducedMotion) {
          settingReducedMotion.checked = s.reduced_motion;
          applyReducedMotion(s.reduced_motion);
        }
      }
    } catch (e) {
      console.error("Failed to load settings:", e);
    }
  }

  function closeSettings() {
    if (settingsModal) settingsModal.classList.add("hidden");
  }

  if (settingsToggleBtn) settingsToggleBtn.addEventListener("click", openSettings);
  if (settingsCloseBtn) settingsCloseBtn.addEventListener("click", closeSettings);

  routerRadios.forEach(radio => {
    radio.addEventListener("change", async (e) => {
      if (e.target.checked) {
        await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ router_mode: e.target.value })
        });
        checkInfo();
      }
    });
  });

  if (settingMemoryEnabled) {
    settingMemoryEnabled.addEventListener("change", async (e) => {
      await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ memory_enabled: e.target.checked })
      });
    });
  }

  function applyReducedMotion(enabled) {
    if (enabled) {
      document.body.classList.add("reduced-motion");
    } else {
      document.body.classList.remove("reduced-motion");
    }
  }

  if (settingReducedMotion) {
    settingReducedMotion.addEventListener("change", async (e) => {
      const enabled = e.target.checked;
      applyReducedMotion(enabled);
      await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reduced_motion: enabled })
      });
    });
  }

  if (btnExportData) {
    btnExportData.addEventListener("click", async () => {
      try {
        const res = await fetch("/api/settings/export");
        if (res.ok) {
          const data = await res.json();
          const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          const dateStr = new Date().toISOString().slice(0, 10);
          a.href = url;
          a.download = `hinaku_export_${dateStr}.json`;
          a.click();
          URL.revokeObjectURL(url);
        }
      } catch (e) {
        alert("Export failed: " + e.message);
      }
    });
  }

  if (btnClearMemory) {
    btnClearMemory.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to clear all semantic memories? This cannot be undone.")) return;
      try {
        const res = await fetch("/api/settings/clear-memory", { method: "POST" });
        if (res.ok) {
          alert("All memories have been cleared.");
          allMemories = [];
          renderMemories([]);
        }
      } catch (e) {
        alert("Clear memory failed: " + e.message);
      }
    });
  }

  if (btnWipeAll) {
    btnWipeAll.addEventListener("click", async () => {
      const token = prompt("CAUTION: This will permanently wipe all conversations, messages, interactions, and memories.\n\nType 'WIPE_ALL' to confirm:");
      if (token !== "WIPE_ALL") return;

      try {
        const res = await fetch("/api/settings/wipe-all", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm: "WIPE_ALL" })
        });
        if (res.ok) {
          alert("All data wiped successfully. Reloading HINAKU...");
          window.location.reload();
        }
      } catch (e) {
        alert("Wipe failed: " + e.message);
      }
    });
  }

  if (btnRunSelfbuild) {
    btnRunSelfbuild.addEventListener("click", async () => {
      if (selfbuildStatus) {
        selfbuildStatus.textContent = "Starting self-build cycle...";
        selfbuildStatus.classList.remove("hidden");
      }
      try {
        const res = await fetch("/api/settings/self-build/run", { method: "POST" });
        if (res.ok) {
          const data = await res.json();
          if (selfbuildStatus) {
            selfbuildStatus.textContent = `Self-build initiated at ${data.timestamp}. ${data.message}`;
          }
        }
      } catch (e) {
        if (selfbuildStatus) {
          selfbuildStatus.textContent = `Self-build error: ${e.message}`;
        }
      }
    });
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
