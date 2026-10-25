import { groupConversationsByDate, getPrivacyChipInfo, formatModelDisplayName } from "/static/js/utils.js";

// Main application state
const state = {
  conversations: [],
  currentConversationId: null,
  activeModel: "bonsai-2:9b",
  privacyMode: "standard", // standard, local_only, private
  thinkHarder: false,
  detailed: false,
  isGenerating: false,
  abortController: null,
  isLoadingModel: false,
  theme: "dark",
  isDemoMode: false
};

// DOM references
let dom = {};

document.addEventListener("DOMContentLoaded", async () => {
  document.documentElement.setAttribute("data-theme", "dark");
  state.theme = "dark";

  initDomReferences();
  setupEventListeners();
  await checkDemoModeAndLoad();
});

function initDomReferences() {
  dom = {
    sidebar: document.getElementById("sidebar"),
    sidebarToggleBtn: document.getElementById("sidebar-toggle-btn"),
    newChatBtn: document.getElementById("new-chat-btn"),
    searchInput: document.getElementById("search-input"),
    sidebarConversations: document.getElementById("sidebar-conversations"),
    chatTitle: document.getElementById("chat-title"),
    topPrivacyChip: document.getElementById("top-privacy-chip"),
    topPrivacyText: document.getElementById("top-privacy-text"),
    topModelChip: document.getElementById("top-model-chip"),
    topModelText: document.getElementById("top-model-text"),
    statusDot: document.getElementById("status-dot"),
    emptyStateView: document.getElementById("empty-state-view"),
    messagesContainer: document.getElementById("messages-container"),
    promptInput: document.getElementById("prompt-input"),
    composerPlusBtn: document.getElementById("composer-plus-btn"),
    composerPlusMenu: document.getElementById("composer-plus-menu"),
    menuToggleThink: document.getElementById("menu-toggle-think"),
    menuToggleDetailed: document.getElementById("menu-toggle-detailed"),
    menuThinkCheck: document.getElementById("menu-think-check"),
    menuDetailedCheck: document.getElementById("menu-detailed-check"),
    chipThinkHarder: document.getElementById("chip-think-harder"),
    chipDetailed: document.getElementById("chip-detailed"),
    removeChipThink: document.getElementById("remove-chip-think"),
    removeChipDetailed: document.getElementById("remove-chip-detailed"),
    composerPrivacyChip: document.getElementById("composer-privacy-chip"),
    composerPrivacyLabel: document.getElementById("composer-privacy-label"),
    privacyDropdownMenu: document.getElementById("privacy-dropdown-menu"),
    composerModelChip: document.getElementById("composer-model-chip"),
    composerModelLabel: document.getElementById("composer-model-label"),
    modelDropdownMenu: document.getElementById("model-dropdown-menu"),
    sendButton: document.getElementById("send-button"),
    sendIcon: document.getElementById("send-icon"),
    stopIcon: document.getElementById("stop-icon")
  };
}

function setupEventListeners() {
  // Sidebar Toggle
  dom.sidebarToggleBtn?.addEventListener("click", () => {
    dom.sidebar.classList.toggle("collapsed");
  });

  // New Chat
  dom.newChatBtn?.addEventListener("click", startNewChat);

  // Search filter
  dom.searchInput?.addEventListener("input", (e) => {
    filterConversations(e.target.value);
  });

  // Plus menu toggle
  dom.composerPlusBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    dom.privacyDropdownMenu?.classList.add("hidden");
    dom.modelDropdownMenu?.classList.add("hidden");
    dom.composerPlusMenu?.classList.toggle("hidden");
  });

  // Think harder menu item
  dom.menuToggleThink?.addEventListener("click", () => {
    state.thinkHarder = !state.thinkHarder;
    updateModeChips();
    dom.composerPlusMenu?.classList.add("hidden");
  });

  // Detailed menu item
  dom.menuToggleDetailed?.addEventListener("click", () => {
    state.detailed = !state.detailed;
    updateModeChips();
    dom.composerPlusMenu?.classList.add("hidden");
  });

  // Removable chips
  dom.removeChipThink?.addEventListener("click", () => {
    state.thinkHarder = false;
    updateModeChips();
  });
  dom.removeChipDetailed?.addEventListener("click", () => {
    state.detailed = false;
    updateModeChips();
  });

  // Privacy dropdown
  dom.composerPrivacyChip?.addEventListener("click", (e) => {
    e.stopPropagation();
    dom.composerPlusMenu?.classList.add("hidden");
    dom.modelDropdownMenu?.classList.add("hidden");
    dom.privacyDropdownMenu?.classList.toggle("hidden");
  });

  // Privacy option selection
  dom.privacyDropdownMenu?.querySelectorAll(".privacy-option-item").forEach(item => {
    item.addEventListener("click", (e) => {
      const mode = item.getAttribute("data-privacy-mode");
      if (mode) {
        setPrivacyMode(mode);
      }
      dom.privacyDropdownMenu.classList.add("hidden");
    });
  });

  // Model dropdown
  dom.composerModelChip?.addEventListener("click", (e) => {
    e.stopPropagation();
    dom.composerPlusMenu?.classList.add("hidden");
    dom.privacyDropdownMenu?.classList.add("hidden");
    dom.modelDropdownMenu?.classList.toggle("hidden");
  });

  dom.modelDropdownMenu?.querySelectorAll(".dropdown-item").forEach(item => {
    item.addEventListener("click", () => {
      const model = item.getAttribute("data-model");
      if (model) {
        selectModel(model);
      }
      dom.modelDropdownMenu.classList.add("hidden");
    });
  });

  // Close menus when clicking outside
  document.addEventListener("click", () => {
    dom.composerPlusMenu?.classList.add("hidden");
    dom.privacyDropdownMenu?.classList.add("hidden");
    dom.modelDropdownMenu?.classList.add("hidden");
  });

  // Keyboard Shortcuts
  window.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key.toLowerCase() === "k") {
      e.preventDefault();
      dom.searchInput?.focus();
    } else if (e.ctrlKey && e.key.toLowerCase() === "n") {
      e.preventDefault();
      startNewChat();
    } else if (e.ctrlKey && e.key.toLowerCase() === "b") {
      e.preventDefault();
      dom.sidebar.classList.toggle("collapsed");
    } else if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "p") {
      e.preventDefault();
      cyclePrivacyMode();
    }
  });

  // Auto-expand textarea
  dom.promptInput?.addEventListener("input", () => {
    dom.promptInput.style.height = "auto";
    dom.promptInput.style.height = Math.min(dom.promptInput.scrollHeight, 180) + "px";
  });

  dom.promptInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  });

  dom.sendButton?.addEventListener("click", () => {
    if (state.isGenerating) {
      handleStopGeneration();
    } else {
      handleSendMessage();
    }
  });
}

async function checkDemoModeAndLoad() {
  try {
    const res = await fetch("/api/demo/status");
    if (res.ok) {
      const data = await res.json();
      state.isDemoMode = data.demo_mode;
    }
  } catch (err) {
    state.isDemoMode = false;
  }

  await loadInitialInfo();
  await loadConversations();
}

async function loadInitialInfo() {
  try {
    const endpoint = state.isDemoMode ? "/api/demo/info" : "/api/info";
    const res = await fetch(endpoint);
    if (res.ok) {
      const info = await res.json();
      if (info.default_model) {
        selectModel(info.default_model);
      }
    }
  } catch (e) {
    console.warn("Could not load initial app info:", e);
  }
}

async function loadConversations() {
  try {
    const endpoint = state.isDemoMode ? "/api/demo/conversations" : "/api/conversations";
    const res = await fetch(endpoint);
    if (res.ok) {
      state.conversations = await res.json();
      renderConversationsList(state.conversations);
    }
  } catch (e) {
    console.warn("Could not load conversations:", e);
  }
}

function renderConversationsList(convs) {
  if (!dom.sidebarConversations) return;
  dom.sidebarConversations.innerHTML = "";

  const groups = groupConversationsByDate(convs);
  const sections = [
    { label: "Today", items: groups.today },
    { label: "Yesterday", items: groups.yesterday },
    { label: "Previous 7 days", items: groups.previous7Days },
    { label: "Older", items: groups.older }
  ];

  sections.forEach(sec => {
    if (sec.items.length === 0) return;

    const groupHeading = document.createElement("div");
    groupHeading.className = "group-title";
    groupHeading.textContent = sec.label;
    dom.sidebarConversations.appendChild(groupHeading);

    sec.items.forEach(c => {
      const item = document.createElement("div");
      item.className = `conv-item ${c.id === state.currentConversationId ? 'active' : ''}`;
      item.dataset.id = c.id;

      const title = document.createElement("span");
      title.className = "conv-title";
      title.textContent = (c.pinned ? "📌 " : "") + (c.title || "Untitled");

      const actions = document.createElement("div");
      actions.className = "conv-actions";

      // Pin button
      const pinBtn = document.createElement("button");
      pinBtn.className = "conv-action-btn";
      pinBtn.title = c.pinned ? "Unpin" : "Pin";
      pinBtn.textContent = "📌";
      pinBtn.onclick = (e) => {
        e.stopPropagation();
        togglePinConversation(c.id, !c.pinned);
      };

      // Delete button
      const delBtn = document.createElement("button");
      delBtn.className = "conv-action-btn";
      delBtn.title = "Delete conversation";
      delBtn.textContent = "🗑️";
      delBtn.onclick = (e) => {
        e.stopPropagation();
        confirmDeleteConversation(c.id);
      };

      actions.appendChild(pinBtn);
      actions.appendChild(delBtn);

      item.appendChild(title);
      item.appendChild(actions);

      item.onclick = () => selectConversation(c.id);
      dom.sidebarConversations.appendChild(item);
    });
  });
}

function filterConversations(query) {
  const q = query.trim().toLowerCase();
  if (!q) {
    renderConversationsList(state.conversations);
    return;
  }
  const filtered = state.conversations.filter(c => (c.title || "").toLowerCase().includes(q));
  renderConversationsList(filtered);
}

function startNewChat() {
  state.currentConversationId = null;
  if (dom.chatTitle) dom.chatTitle.value = "New chat";
  if (dom.emptyStateView) dom.emptyStateView.classList.remove("hidden");
  if (dom.messagesContainer) {
    dom.messagesContainer.classList.add("hidden");
    dom.messagesContainer.innerHTML = "";
  }
  if (dom.promptInput) {
    dom.promptInput.value = "";
    dom.promptInput.focus();
  }
  renderConversationsList(state.conversations);
}

async function selectConversation(id) {
  state.currentConversationId = id;
  const conv = state.conversations.find(c => c.id === id);
  if (conv && dom.chatTitle) {
    dom.chatTitle.value = conv.title || "Untitled";
    setPrivacyMode(conv.is_private ? "private" : "standard");
  }

  try {
    const endpoint = state.isDemoMode ? `/api/demo/conversations/${id}` : `/api/conversations/${id}`;
    const res = await fetch(endpoint);
    if (res.ok) {
      const fullConv = await res.json();
      renderMessages(fullConv.messages || []);
    }
  } catch (err) {
    console.error("Failed to load conversation details:", err);
  }

  renderConversationsList(state.conversations);
}

function renderMessages(messages) {
  if (!messages || messages.length === 0) {
    dom.emptyStateView?.classList.remove("hidden");
    dom.messagesContainer?.classList.add("hidden");
    return;
  }

  dom.emptyStateView?.classList.add("hidden");
  dom.messagesContainer?.classList.remove("hidden");
  dom.messagesContainer.innerHTML = "";

  messages.forEach(msg => {
    const row = document.createElement("div");
    row.className = "message-row";

    if (msg.role === "user") {
      const bubble = document.createElement("div");
      bubble.className = "user-bubble";
      bubble.textContent = msg.content;
      row.appendChild(bubble);
    } else {
      const body = document.createElement("div");
      body.className = "assistant-body";
      body.textContent = msg.content;

      const meta = document.createElement("div");
      meta.className = "assistant-meta-row";
      meta.innerHTML = `
        <span class="badge badge-local">${msg.model || state.activeModel}</span>
        <span class="badge badge-local">${msg.backend || 'local'}</span>
        ${msg.verified ? '<span class="badge badge-verified">✓ verified</span>' : ''}
      `;

      row.appendChild(body);
      row.appendChild(meta);
    }

    dom.messagesContainer.appendChild(row);
  });
}

function updateModeChips() {
  if (state.thinkHarder) {
    dom.chipThinkHarder?.classList.remove("hidden");
    if (dom.menuThinkCheck) dom.menuThinkCheck.textContent = "✓";
  } else {
    dom.chipThinkHarder?.classList.add("hidden");
    if (dom.menuThinkCheck) dom.menuThinkCheck.textContent = "";
  }

  if (state.detailed) {
    dom.chipDetailed?.classList.remove("hidden");
    if (dom.menuDetailedCheck) dom.menuDetailedCheck.textContent = "✓";
  } else {
    dom.chipDetailed?.classList.add("hidden");
    if (dom.menuDetailedCheck) dom.menuDetailedCheck.textContent = "";
  }
}

function setPrivacyMode(mode) {
  state.privacyMode = mode;
  const info = getPrivacyChipInfo(mode);

  if (dom.topPrivacyChip) {
    dom.topPrivacyChip.className = `status-chip ${info.colorClass}`;
    if (dom.topPrivacyText) dom.topPrivacyText.textContent = info.label;
  }

  if (dom.composerPrivacyChip) {
    dom.composerPrivacyChip.className = `status-chip ${info.colorClass}`;
    if (dom.composerPrivacyLabel) dom.composerPrivacyLabel.textContent = info.label;
  }
}

function cyclePrivacyMode() {
  const modes = ["standard", "local_only", "private"];
  const nextIdx = (modes.indexOf(state.privacyMode) + 1) % modes.length;
  setPrivacyMode(modes[nextIdx]);
}

function selectModel(modelName) {
  state.activeModel = modelName;
  const label = formatModelDisplayName(modelName, state.isLoadingModel);
  if (dom.topModelText) dom.topModelText.textContent = label;
  if (dom.composerModelLabel) dom.composerModelLabel.textContent = label;
}

async function togglePinConversation(convId, pinned) {
  if (state.isDemoMode) {
    const c = state.conversations.find(item => item.id === convId);
    if (c) c.pinned = pinned ? 1 : 0;
    renderConversationsList(state.conversations);
    return;
  }

  try {
    const res = await fetch(`/api/conversations/${convId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned })
    });
    if (res.ok) {
      await loadConversations();
    }
  } catch (err) {
    console.error("Failed to update pinned state:", err);
  }
}

async function confirmDeleteConversation(convId) {
  if (!confirm("Are you sure you want to delete this conversation?")) {
    return;
  }

  if (state.isDemoMode) {
    state.conversations = state.conversations.filter(c => c.id !== convId);
    if (state.currentConversationId === convId) startNewChat();
    renderConversationsList(state.conversations);
    return;
  }

  try {
    const res = await fetch(`/api/conversations/${convId}`, { method: "DELETE" });
    if (res.ok) {
      if (state.currentConversationId === convId) startNewChat();
      await loadConversations();
    }
  } catch (err) {
    console.error("Failed to delete conversation:", err);
  }
}

function handleSendMessage() {
  const text = dom.promptInput?.value.trim();
  if (!text) return;
  alert(`Sending message: "${text}" with model: ${state.activeModel}, privacy: ${state.privacyMode}`);
}

function handleStopGeneration() {
  state.isGenerating = false;
  dom.sendIcon?.classList.remove("hidden");
  dom.stopIcon?.classList.add("hidden");
  dom.sendButton?.classList.remove("stop-btn");
}
