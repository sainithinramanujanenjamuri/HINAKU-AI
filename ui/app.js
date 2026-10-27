import { groupConversationsByDate, getPrivacyChipInfo, formatModelDisplayName } from "/static/js/utils.js";
import { createUserMessageElement, createAssistantMessageElement, updateMetaRow, renderCitationChips, formatFileSize, getFileIcon } from "/static/js/message.js";
import { attachCodeBlockCopyHandlers, formatMarkdown } from "/static/js/markdown.js";
import { renderMemoryPage, renderRatingsPage, renderDatasetPage, renderSettingsPage } from "/static/js/pages.js";

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
  isDemoMode: false,
  isApiLoggedByProvider: false,
  activeMessages: [],
  stagedAttachments: []
};

// DOM references
let dom = {};

// Rotating Opening Headlines (matches HINAKU's calm, observant persona)
const HINAKU_OPENING_PROMPTS = [
  "What are we working on?",
  "Where does the work begin?",
  "The quiet remains. What are we solving?",
  "A clean canvas. Where do you want to start?",
  "What problem needs dissecting?",
  "The void is quiet. What are we building?",
  "What question brought you back?",
  "Focus is sharpest in the dark. What's on your mind?",
  "What shall we unravel today?",
  "Quiet space. What are we crafting?",
  "The machine is listening. Where shall we look?",
  "Clarity through precision. What are we exploring?"
];

function rotateEmptyStateHeadline() {
  const headlineEl = document.getElementById("empty-state-headline");
  if (!headlineEl) return;
  const current = headlineEl.textContent.trim();
  const pool = HINAKU_OPENING_PROMPTS.filter(p => p !== current);
  const picked = pool[Math.floor(Math.random() * pool.length)] || HINAKU_OPENING_PROMPTS[0];
  headlineEl.textContent = picked;
}
window.rotateEmptyStateHeadline = rotateEmptyStateHeadline;

document.addEventListener("DOMContentLoaded", async () => {
  document.documentElement.setAttribute("data-theme", "dark");
  state.theme = "dark";

  initDomReferences();
  setupEventListeners();
  rotateEmptyStateHeadline();
  await checkDemoModeAndLoad();

  const handleHash = () => {
    const hash = window.location.hash.replace("#", "");
    if (["memory", "dataset", "ratings", "approval", "settings"].includes(hash)) {
      openFullPage(hash);
    }
  };
  handleHash();
  window.addEventListener("hashchange", handleHash);
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
    privacyIcon: document.getElementById("privacy-icon"),
    privacyLabel: document.getElementById("privacy-label"),
    topModelChip: document.getElementById("top-model-chip"),
    topModelText: document.getElementById("top-model-text"),
    statusDot: document.getElementById("status-dot"),
    chatViewport: document.getElementById("chat-viewport"),
    emptyStateView: document.getElementById("empty-state-view"),
    messagesContainer: document.getElementById("messages-container"),
    scrollBottomBtn: document.getElementById("scroll-bottom-btn"),
    promptInput: document.getElementById("prompt-input"),
    composerPlusBtn: document.getElementById("composer-plus-btn"),
    composerPlusMenu: document.getElementById("composer-plus-menu"),
    menuToggleThink: document.getElementById("menu-toggle-think"),
    menuToggleDetailed: document.getElementById("menu-toggle-detailed"),
    menuAttachFiles: document.getElementById("menu-attach-files"),
    composerFileInput: document.getElementById("composer-file-input"),
    composerAttachmentChips: document.getElementById("composer-attachment-chips"),
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
    stopIcon: document.getElementById("stop-icon"),
    cancelButton: document.getElementById("cancel-button"),
    contextPanel: document.getElementById("context-panel"),
    contextPanelToggleBtn: document.getElementById("context-panel-toggle-btn"),
    contextPanelCloseBtn: document.getElementById("context-panel-close-btn"),
    contextTabMemory: document.getElementById("context-tab-memory"),
    contextTabFiles: document.getElementById("context-tab-files"),
    contextTabDetails: document.getElementById("context-tab-details"),
    contextMemoryList: document.getElementById("context-memory-list"),
    contextFilesList: document.getElementById("context-files-list"),
    contextRouteMode: document.getElementById("context-route-mode"),
    fullPageView: document.getElementById("full-page-view"),
    pageBackBtn: document.getElementById("page-back-btn"),
    pageHeaderTitle: document.getElementById("page-header-title"),
    pageDynamicContent: document.getElementById("page-dynamic-content"),
    memoryToggleBtn: document.getElementById("memory-toggle-btn"),
    datasetToggleBtn: document.getElementById("dataset-toggle-btn"),
    settingsToggleBtn: document.getElementById("settings-toggle-btn"),
    noticeBanner: document.getElementById("notice-banner"),
    noticeText: document.getElementById("notice-text"),
    noticeDismissBtn: document.getElementById("notice-dismiss-btn"),
    noticeRemindLaterBtn: document.getElementById("notice-remind-later-btn"),
    ollamaDownBanner: document.getElementById("ollama-down-banner"),
    ollamaRetryBtn: document.getElementById("ollama-retry-btn")
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

  // Files and images menu item
  dom.menuAttachFiles?.addEventListener("click", () => {
    dom.composerPlusMenu?.classList.add("hidden");
    dom.composerFileInput?.click();
  });

  dom.composerFileInput?.addEventListener("change", (e) => {
    handleFilesSelected(e.target.files);
    dom.composerFileInput.value = "";
  });

  // Drag and drop onto composer and chat area
  const composerCard = document.querySelector(".composer-card");
  window.addEventListener("dragover", (e) => {
    e.preventDefault();
    dom.chatViewport?.classList.add("drag-over");
    composerCard?.classList.add("drag-over");
  });
  window.addEventListener("dragleave", (e) => {
    if (e.clientX <= 0 || e.clientY <= 0 || e.clientX >= window.innerWidth || e.clientY >= window.innerHeight) {
      dom.chatViewport?.classList.remove("drag-over");
      composerCard?.classList.remove("drag-over");
    }
  });
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    dom.chatViewport?.classList.remove("drag-over");
    composerCard?.classList.remove("drag-over");
    if (e.dataTransfer && e.dataTransfer.files.length > 0) {
      handleFilesSelected(e.dataTransfer.files);
    }
  });

  // Clipboard paste files/images
  window.addEventListener("paste", (e) => {
    if (e.clipboardData && e.clipboardData.files.length > 0) {
      e.preventDefault();
      handleFilesSelected(e.clipboardData.files);
    }
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
    item.addEventListener("click", () => {
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

  // Scroll to bottom button
  dom.chatViewport?.addEventListener("scroll", () => {
    if (!dom.chatViewport || !dom.scrollBottomBtn) return;
    const distanceToBottom = dom.chatViewport.scrollHeight - dom.chatViewport.scrollTop - dom.chatViewport.clientHeight;
    if (distanceToBottom > 150) {
      dom.scrollBottomBtn.classList.remove("hidden");
    } else {
      dom.scrollBottomBtn.classList.add("hidden");
    }
  });

  dom.scrollBottomBtn?.addEventListener("click", scrollToBottom);

  // Context panel toggle
  dom.contextPanelToggleBtn?.addEventListener("click", () => {
    dom.contextPanel?.classList.toggle("collapsed");
  });
  dom.contextPanelCloseBtn?.addEventListener("click", () => {
    dom.contextPanel?.classList.add("collapsed");
  });

  // Context tabs
  document.querySelectorAll(".context-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".context-tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      dom.contextTabMemory?.classList.toggle("hidden", tab !== "memory");
      dom.contextTabFiles?.classList.toggle("hidden", tab !== "files");
      dom.contextTabDetails?.classList.toggle("hidden", tab !== "details");
      if (tab === "files") {
        loadConversationFiles();
      }
    });
  });

  // Full page view navigation
  dom.memoryToggleBtn?.addEventListener("click", () => openFullPage("memory"));
  dom.datasetToggleBtn?.addEventListener("click", () => openFullPage("dataset"));
  dom.settingsToggleBtn?.addEventListener("click", () => openFullPage("settings"));
  dom.pageBackBtn?.addEventListener("click", closeFullPage);

  document.querySelectorAll(".page-nav-item").forEach(item => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".page-nav-item").forEach(i => i.classList.remove("active"));
      item.classList.add("active");
      loadPageContent(item.dataset.page);
    });
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
    } else if (e.ctrlKey && e.key === ".") {
      e.preventDefault();
      dom.contextPanel?.classList.toggle("collapsed");
    } else if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "p") {
      e.preventDefault();
      cyclePrivacyMode();
    } else if (e.key === "Escape" && state.isGenerating) {
      e.preventDefault();
      handleStopGeneration();
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

  dom.cancelButton?.addEventListener("click", handleStopGeneration);

  // Notice banners
  dom.noticeDismissBtn?.addEventListener("click", () => {
    dom.noticeBanner?.classList.add("hidden");
  });

  dom.noticeRemindLaterBtn?.addEventListener("click", async () => {
    try {
      await fetch("/api/self-build/remind-later", { method: "POST" });
      dom.noticeBanner?.classList.add("hidden");
    } catch (e) {
      console.warn("Could not remind later:", e);
    }
  });

  dom.ollamaRetryBtn?.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/health/ollama");
      const health = await res.json();
      if (health.online) {
        dom.ollamaDownBanner?.classList.add("hidden");
        dom.statusDot?.classList.remove("offline");
      }
    } catch (e) {
      console.warn("Retry ollama failed:", e);
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
      if (info.router?.api_logged_by_provider) {
        state.isApiLoggedByProvider = true;
      }
      if (info.ollama_status?.online === false) {
        dom.ollamaDownBanner?.classList.remove("hidden");
        dom.statusDot?.classList.add("offline");
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

      // In demo mode or if default conversation exists, select the first one for initial render
      if (state.isDemoMode && state.conversations.length > 0 && !state.currentConversationId) {
        selectConversation(state.conversations[0].id);
      }
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
  state.activeMessages = [];
  state.stagedAttachments = [];
  renderStagedAttachmentChips();
  if (dom.contextFilesList) dom.contextFilesList.textContent = "No documents attached to this chat.";
  if (dom.chatTitle) dom.chatTitle.value = "New chat";
  if (dom.emptyStateView) {
    dom.emptyStateView.classList.remove("hidden");
    rotateEmptyStateHeadline();
  }
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
      state.activeMessages = fullConv.messages || [];
      renderConversationMessages(state.activeMessages);
    }
  } catch (err) {
    console.error("Failed to load conversation details:", err);
  }

  loadConversationFiles();
  renderConversationsList(state.conversations);
}

function renderConversationMessages(messages) {
  if (!messages || messages.length === 0) {
    dom.emptyStateView?.classList.remove("hidden");
    dom.messagesContainer?.classList.add("hidden");
    return;
  }

  dom.emptyStateView?.classList.add("hidden");
  dom.messagesContainer?.classList.remove("hidden");
  dom.messagesContainer.innerHTML = "";

  messages.forEach(msg => {
    if (msg.role === "user") {
      const userEl = createUserMessageElement(msg.content, msg.created_at, (text) => {
        if (dom.promptInput) {
          dom.promptInput.value = text;
          dom.promptInput.focus();
        }
      }, msg.attachments || []);
      dom.messagesContainer.appendChild(userEl);
    } else {
      const { row } = createAssistantMessageElement({
        id: msg.id,
        interactionId: msg.interaction_id,
        model: msg.model || state.activeModel,
        backend: msg.backend || "local",
        content: msg.content,
        verified: Boolean(msg.verified),
        verifyStatus: msg.verify_status,
        verifyReason: msg.verify_reason,
        workedSeconds: msg.worked_seconds,
        processSteps: msg.process_steps,
        hitTokenLimit: Boolean(msg.hit_token_limit),
        onFeedback: handleFeedback,
        onEditReply: handleEditReply,
        onRetry: () => handleRetryMessage(msg),
        onContinue: () => handleContinueMessage()
      });
      if (msg.citations && msg.citations.length > 0) {
        renderCitationChips(row, msg.citations, (cit) => openContextPanelTab("files", cit.file));
      }
      dom.messagesContainer.appendChild(row);
      attachCodeBlockCopyHandlers(row);
    }
  });

  scrollToBottom();
}

function scrollToBottom() {
  if (!dom.chatViewport) return;
  dom.chatViewport.scrollTo({
    top: dom.chatViewport.scrollHeight,
    behavior: "smooth"
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
    if (dom.privacyLabel) dom.privacyLabel.textContent = info.label;
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

function handleFilesSelected(files) {
  if (!files || files.length === 0) return;
  const newFiles = Array.from(files);
  if (state.stagedAttachments.length + newFiles.length > 5) {
    showNotice("Maximum 5 files per message permitted.");
    return;
  }

  newFiles.forEach(file => {
    if (file.size > 20 * 1024 * 1024) {
      showNotice(`File "${file.name}" exceeds the 20 MB size limit.`);
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
      state.stagedAttachments.push({
        filename: file.name,
        size: file.size,
        type: file.type || "application/octet-stream",
        b64: e.target.result
      });
      renderStagedAttachmentChips();
    };
    reader.readAsDataURL(file);
  });
}

function renderStagedAttachmentChips() {
  if (!dom.composerAttachmentChips) return;
  dom.composerAttachmentChips.innerHTML = "";
  state.stagedAttachments.forEach((att, idx) => {
    const chip = document.createElement("div");
    chip.className = "composer-att-chip";
    chip.innerHTML = `
      <span>${getFileIcon(att.filename)}</span>
      <span>${att.filename} (${formatFileSize(att.size)})</span>
      <span class="composer-att-chip-remove" title="Remove attachment">×</span>
    `;
    chip.querySelector(".composer-att-chip-remove").onclick = () => {
      state.stagedAttachments.splice(idx, 1);
      renderStagedAttachmentChips();
    };
    dom.composerAttachmentChips.appendChild(chip);
  });
}

async function loadConversationFiles() {
  if (!dom.contextFilesList) return;
  if (!state.currentConversationId) {
    dom.contextFilesList.textContent = "No documents attached to this chat.";
    return;
  }
  try {
    const endpoint = state.isDemoMode 
      ? `/api/demo/conversations/${state.currentConversationId}/attachments`
      : `/api/conversations/${state.currentConversationId}/attachments`;
    const res = await fetch(endpoint);
    if (res.ok) {
      const data = await res.json();
      if (!data.attachments || data.attachments.length === 0) {
        dom.contextFilesList.textContent = "No documents attached to this chat.";
        return;
      }
      dom.contextFilesList.innerHTML = "";
      data.attachments.forEach(att => {
        const item = document.createElement("div");
        item.className = "context-file-item";
        item.style.cssText = "padding: 8px 0; border-bottom: 1px solid var(--border-subtle); display: flex; flex-direction: column; gap: 4px;";
        item.innerHTML = `
          <div style="display: flex; align-items: center; gap: 8px; font-weight: 500;">
            <span>${getFileIcon(att.filename)}</span>
            <span style="word-break: break-all;">${att.filename}</span>
          </div>
          <div style="font-size: 11.5px; color: var(--text-tertiary);">
            ${formatFileSize(att.size_bytes)} · ~${att.token_count || 0} tokens · ${(att.file_type || "file").toUpperCase()}
          </div>
        `;
        dom.contextFilesList.appendChild(item);
      });
    }
  } catch (e) {
    console.warn("Failed loading conversation attachments:", e);
  }
}

function openContextPanelTab(tabName, highlightFilename = null) {
  if (!dom.contextPanel) return;
  dom.contextPanel.classList.remove("collapsed");
  document.querySelectorAll(".context-tab-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === tabName);
  });
  dom.contextTabMemory?.classList.toggle("hidden", tabName !== "memory");
  dom.contextTabFiles?.classList.toggle("hidden", tabName !== "files");
  dom.contextTabDetails?.classList.toggle("hidden", tabName !== "details");
  if (tabName === "files") {
    loadConversationFiles();
  }
}

async function handleSendMessage(overrideText = null) {
  const text = (overrideText || dom.promptInput?.value || "").trim();
  if ((!text && state.stagedAttachments.length === 0) || state.isGenerating) return;

  const filesToUpload = [...state.stagedAttachments];
  state.stagedAttachments = [];
  renderStagedAttachmentChips();

  if (dom.promptInput) {
    dom.promptInput.value = "";
    dom.promptInput.style.height = "auto";
  }

  // Hide empty state, ensure messages container is open
  dom.emptyStateView?.classList.add("hidden");
  dom.messagesContainer?.classList.remove("hidden");

  // Auto-clear Detailed mode after sending unless pinned
  if (state.detailed && !state.detailedPinned) {
    state.detailed = false;
    dom.chipDetailed?.classList.add("hidden");
    if (dom.menuDetailedCheck) dom.menuDetailedCheck.textContent = "";
  }

  // Render User Message with attachment cards
  const userEl = createUserMessageElement(text || "(Sent attachments)", new Date().toISOString(), null, filesToUpload);
  dom.messagesContainer.appendChild(userEl);
  scrollToBottom();

  // Create Assistant Message Placeholder
  state.isGenerating = true;
  setGeneratingUI(true);

  let assistantText = "";
  let lastMessageId = null;
  let lastInteractionId = null;
  let lastBackend = "local";
  let isVerified = false;
  let verifyStatus = null;
  let verifyReason = null;
  let hitTokenLimit = false;
  let docCitations = [];
  let startTime = Date.now();

  const { row: assistantRow, body: assistantBody, metaRow } = createAssistantMessageElement({
    model: state.activeModel,
    backend: "local",
    content: "",
    isStreaming: true
  });
  dom.messagesContainer.appendChild(assistantRow);
  scrollToBottom();

  state.abortController = new AbortController();

  if (state.isDemoMode) {
    setTimeout(() => {
      assistantText = filesToUpload.length > 0 
        ? "I have analyzed the attached document. The configuration parameters and technical architecture are verified offline under local model routing."
        : "This is a demonstration response generated locally in UI demo mode. Surface codes and cat codes offer contrasting trade-offs in quantum architecture.";
      assistantBody.innerHTML = formatMarkdown(assistantText);
      attachCodeBlockCopyHandlers(assistantBody);
      if (filesToUpload.length > 0) {
        renderCitationChips(assistantRow, filesToUpload.map(f => ({ file: f.filename, page: 1 })), (cit) => {
          openContextPanelTab("files", cit.file);
        });
      }
      updateMetaRow(metaRow, {
        model: state.activeModel,
        backend: "local",
        verified: true,
        verifyStatus: "verified"
      });
      state.isGenerating = false;
      setGeneratingUI(false);
      scrollToBottom();
    }, 400);
    return;
  }

  try {
    // If there are files to upload, persist them via attachment API first
    if (filesToUpload.length > 0) {
      if (!state.currentConversationId) {
        const createRes = await fetch("/api/conversations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: (text || filesToUpload[0].filename).slice(0, 36) })
        });
        if (createRes.ok) {
          const conv = await createRes.json();
          state.currentConversationId = conv.id;
        }
      }
      if (state.currentConversationId) {
        await fetch(`/api/conversations/${state.currentConversationId}/attachments`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            files: filesToUpload.map(f => ({
              filename: f.filename,
              content_base64: f.b64,
              mime_type: f.type
            }))
          })
        });
        loadConversationFiles();
      }
    }

    const isPrivate = state.privacyMode === "private";
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: [{ role: "user", content: text || "Please analyze the attached document." }],
        conversation_id: state.currentConversationId,
        is_private: isPrivate,
        model: state.activeModel,
        stream: true,
        think_harder: state.thinkHarder,
        detailed: state.detailed
      }),
      signal: state.abortController.signal
    });

    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
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
        if (dataStr === "[DONE]") break;

        try {
          const parsed = JSON.parse(dataStr);

          if (parsed.type === "error") {
            showNotice(parsed.error || parsed.message || "Model error encountered");
            assistantRow.remove();
            break;
          }

          if (parsed.conversation_id) {
            state.currentConversationId = parsed.conversation_id;
          }
          if (parsed.message_id) {
            lastMessageId = parsed.message_id;
            assistantRow.dataset.messageId = parsed.message_id;
          }
          if (parsed.interaction_id) {
            lastInteractionId = parsed.interaction_id;
            assistantRow.dataset.interactionId = parsed.interaction_id;
          }

          if (parsed.auto_private) {
            setPrivacyMode("private");
            showNotice("Sensitive topic detected. Set conversation to Private.", true);
          }

          if (parsed.backend) lastBackend = parsed.backend;
          if (parsed.verified !== undefined) isVerified = Boolean(parsed.verified);
          if (parsed.verify_status) verifyStatus = parsed.verify_status;
          if (parsed.verify_reason) verifyReason = parsed.verify_reason;
          if (parsed.hit_token_limit !== undefined) hitTokenLimit = Boolean(parsed.hit_token_limit);
          if (parsed.citations && parsed.citations.length > 0) {
            docCitations = parsed.citations;
          }

          if (parsed.chunk) {
            assistantText += parsed.chunk;
            assistantBody.innerHTML = formatMarkdown(assistantText);
            const cursor = document.createElement("span");
            cursor.className = "streaming-cursor";
            assistantBody.appendChild(cursor);
            attachCodeBlockCopyHandlers(assistantBody);
            scrollToBottom();
          }

          if (parsed.type === "correction" && parsed.final_content) {
            assistantText = parsed.final_content;
            assistantBody.innerHTML = formatMarkdown(assistantText);
            attachCodeBlockCopyHandlers(assistantBody);
          }
        } catch (e) {
          console.error("Error parsing stream chunk:", e);
        }
      }
    }

    // Finalize assistant reply
    const workedSeconds = Math.max(1, Math.round((Date.now() - startTime) / 1000));
    assistantBody.innerHTML = formatMarkdown(assistantText);
    attachCodeBlockCopyHandlers(assistantBody);

    if (docCitations && docCitations.length > 0) {
      renderCitationChips(assistantRow, docCitations, (cit) => {
        openContextPanelTab("files", cit.file);
      });
    }

    updateMetaRow(metaRow, {
      model: state.activeModel,
      backend: lastBackend,
      verified: isVerified,
      verifyStatus,
      verifyReason
    });

  } catch (err) {
    if (err.name !== "AbortError") {
      console.error("Chat request failed:", err);
      showNotice(`Request failed: ${err.message}`);
    }
  } finally {
    state.isGenerating = false;
    setGeneratingUI(false);
    loadConversations();
  }
}

function setGeneratingUI(generating) {
  if (generating) {
    dom.sendIcon?.classList.add("hidden");
    dom.stopIcon?.classList.remove("hidden");
    dom.sendButton?.classList.add("stop-btn");
    dom.sendButton?.setAttribute("title", "Stop generation (Esc)");
  } else {
    dom.sendIcon?.classList.remove("hidden");
    dom.stopIcon?.classList.add("hidden");
    dom.sendButton?.classList.remove("stop-btn");
    dom.sendButton?.setAttribute("title", "Send message (Enter)");
  }
}

function handleStopGeneration() {
  if (state.abortController) {
    state.abortController.abort();
    state.abortController = null;
  }
  state.isGenerating = false;
  setGeneratingUI(false);
}

function handleFeedback(type, buttonEl, rowEl) {
  rowEl.querySelectorAll(".msg-action-btn").forEach(b => b.classList.remove("active"));
  buttonEl.classList.add("active");

  const messageId = buttonEl.closest(".message-wrapper")?.dataset?.messageId;
  if (!messageId || state.isDemoMode) return;

  fetch(`/api/interactions/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message_id: messageId, feedback: type })
  }).catch(e => console.error("Feedback error:", e));
}

function handleEditReply(row, body) {
  const currentText = body.innerText;
  const newText = prompt("Edit reply to feed training dataset:", currentText);
  if (!newText || newText === currentText) return;

  body.innerHTML = formatMarkdown(newText);
  attachCodeBlockCopyHandlers(body);

  const messageId = row.dataset?.messageId;
  if (!messageId || state.isDemoMode) return;

  fetch(`/api/interactions/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message_id: messageId, edited_answer: newText })
  }).catch(e => console.error("Save edit error:", e));
}

function handleRetryMessage() {
  if (dom.messagesContainer) {
    const userRows = dom.messagesContainer.querySelectorAll(".user-row");
    if (userRows.length > 0) {
      const lastUserText = userRows[userRows.length - 1].querySelector(".user-bubble")?.textContent;
      if (lastUserText) handleSendMessage(lastUserText);
    }
  }
}

function handleContinueMessage() {
  handleSendMessage("Continue");
}

function openFullPage(pageName) {
  if (!dom.fullPageView) return;
  dom.fullPageView.classList.remove("hidden");
  document.querySelectorAll(".page-nav-item").forEach(i => {
    i.classList.toggle("active", i.dataset.page === pageName);
  });
  loadPageContent(pageName);
}

function closeFullPage() {
  dom.fullPageView?.classList.add("hidden");
}

async function loadPageContent(pageName) {
  if (!dom.pageDynamicContent) return;
  if (dom.pageHeaderTitle) {
    const titles = {
      memory: "Memories",
      dataset: "Dataset Curation",
      ratings: "Model Ratings",
      approval: "Self-Build Approval",
      settings: "Settings & Preferences"
    };
    dom.pageHeaderTitle.textContent = titles[pageName] || "Page";
  }

  if (pageName === "memory") {
    try {
      const endpoint = state.isDemoMode ? "/api/demo/memories" : "/api/memories";
      const res = await fetch(endpoint);
      const mems = await res.json();
      renderMemoryPage(
        dom.pageDynamicContent,
        mems,
        async (id, currentText) => {
          const newText = prompt("Edit memory:", currentText);
          if (newText && newText !== currentText) {
            await fetch(`/api/memories/${id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ text: newText })
            });
            loadPageContent("memory");
          }
        },
        async (id) => {
          if (confirm("Delete this memory?")) {
            await fetch(`/api/memories/${id}`, { method: "DELETE" });
            loadPageContent("memory");
          }
        }
      );
    } catch (e) {
      dom.pageDynamicContent.innerHTML = `<div>Error loading memories: ${e.message}</div>`;
    }
  } else if (pageName === "ratings") {
    try {
      const endpoint = state.isDemoMode ? "/api/demo/ratings" : "/api/interactions/ratings-by-model";
      const res = await fetch(endpoint);
      const ratings = await res.json();
      renderRatingsPage(dom.pageDynamicContent, ratings);
    } catch (e) {
      dom.pageDynamicContent.innerHTML = `<div>Error loading ratings: ${e.message}</div>`;
    }
  } else if (pageName === "dataset") {
    try {
      const endpoint = state.isDemoMode ? "/api/demo/curate" : "/api/training/curate";
      const res = await fetch(endpoint);
      const data = await res.json();
      renderDatasetPage(dom.pageDynamicContent, data, () => {
        alert("Build dataset requested.");
      });
    } catch (e) {
      dom.pageDynamicContent.innerHTML = `<div>Error loading dataset curation: ${e.message}</div>`;
    }
  } else if (pageName === "approval") {
    dom.pageDynamicContent.innerHTML = `
      <div class="approval-card">
        <h3>6-Month Self-Build Promotion Gate</h3>
        <p style="color: var(--text-secondary); font-size: 13.5px;">
          The self-build cycle compares the newly trained fine-tuned model against current local and golden evaluation baselines.
        </p>
        <div class="score-comparison-grid">
          <div class="score-box">
            <div class="context-card-title">Candidate Adapter Score</div>
            <div class="score-value">84.2%</div>
          </div>
          <div class="score-box">
            <div class="context-card-title">Current Local Baseline</div>
            <div class="score-value">79.6%</div>
          </div>
        </div>
        <div style="color: var(--color-private); font-weight: 500; font-size: 13.5px;">
          ✓ Candidate beats baseline by +4.6%. Ready for promotion.
        </div>
      </div>
    `;
  } else if (pageName === "settings") {
    try {
      let settingsData = {
        default_local_model: state.activeModel || "bonsai-2:9b",
        router_mode: "auto",
        memory_enabled: true,
        reduced_motion: false
      };
      const endpoint = state.isDemoMode ? "/api/demo/settings" : "/api/settings";
      const res = await fetch(endpoint);
      if (res.ok) {
        settingsData = await res.json();
      }
      renderSettingsPage(
        dom.pageDynamicContent,
        settingsData,
        async (patch) => {
          if (!state.isDemoMode) {
            try {
              await fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(patch)
              });
            } catch (err) {
              console.error("Failed to save settings:", err);
            }
          }
          if (patch.default_local_model) {
            selectModel(patch.default_local_model);
          }
          if (patch.reduced_motion !== undefined) {
            if (patch.reduced_motion) {
              document.body.classList.add("reduced-motion");
            } else {
              document.body.classList.remove("reduced-motion");
            }
          }
        },
        async () => {
          if (state.isDemoMode) {
            alert("Export downloaded (Demo mode: demo_data.json)");
            return;
          }
          try {
            const res = await fetch("/api/settings/export");
            const data = await res.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `hinaku_export_${new Date().toISOString().slice(0, 10)}.json`;
            a.click();
            URL.revokeObjectURL(url);
          } catch (e) {
            alert("Export failed: " + e.message);
          }
        },
        async () => {
          const confirmText = prompt("Type 'WIPE_ALL' to permanently delete all conversations, interactions, and memories:");
          if (confirmText !== "WIPE_ALL") {
            if (confirmText !== null) alert("Wipe canceled. Confirmation string did not match.");
            return;
          }
          if (state.isDemoMode) {
            alert("All demo data cleared (simulation).");
            return;
          }
          try {
            const res = await fetch("/api/settings/wipe-all", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ confirm: "WIPE_ALL" })
            });
            if (res.ok) {
              alert("All data wiped successfully.");
              window.location.reload();
            } else {
              const err = await res.json();
              alert("Failed to wipe data: " + (err.detail || "Unknown error"));
            }
          } catch (e) {
            alert("Wipe error: " + e.message);
          }
        }
      );
    } catch (e) {
      dom.pageDynamicContent.innerHTML = `<div>Error loading settings: ${e.message}</div>`;
    }
  }
}

function showNotice(text, showUndo = false) {
  if (!dom.noticeBanner || !dom.noticeText) return;
  dom.noticeText.textContent = text;
  dom.noticeBanner.classList.remove("hidden");

  if (showUndo) {
    const undoBtn = document.createElement("button");
    undoBtn.textContent = "Undo";
    undoBtn.className = "notice-action-btn";
    undoBtn.onclick = () => {
      setPrivacyMode("standard");
      dom.noticeBanner?.classList.add("hidden");
    };
    dom.noticeText.appendChild(undoBtn);
  }
}
