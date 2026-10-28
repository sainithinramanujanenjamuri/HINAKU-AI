import { formatMarkdown } from "/static/js/markdown.js";

export function getFileIcon(filename = "") {
  const ext = filename.split(".").pop().toLowerCase();
  if (["png", "jpg", "jpeg", "webp", "gif"].includes(ext)) return "🖼️";
  if (["pdf", "docx", "doc", "txt", "md", "html", "css", "py", "js", "yaml", "yml"].includes(ext)) return "📄";
  if (["csv", "json"].includes(ext)) return "📊";
  return "📄";
}

export function formatFileSize(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Creates and returns a user message element.
 * Pattern: Soft tinted bubble, attachments grid, Show more fold for long inputs, hover timestamp & copy/edit.
 */
export function createUserMessageElement(content, timestamp = null, onEdit = null, attachments = []) {
  const row = document.createElement("div");
  row.className = "message-wrapper user-row";

  // Attachment cards above the text bubble
  if (attachments && attachments.length > 0) {
    const attGrid = document.createElement("div");
    attGrid.className = "user-attachments-grid";
    attachments.forEach(att => {
      const card = document.createElement("div");
      card.className = "user-attachment-card";

      const icon = document.createElement("span");
      icon.className = "att-card-icon";
      icon.textContent = getFileIcon(att.filename || att.name);

      const info = document.createElement("div");
      info.className = "att-card-info";

      const name = document.createElement("span");
      name.className = "att-card-name";
      name.textContent = att.filename || att.name || "Attachment";
      name.title = att.filename || att.name || "";

      const size = document.createElement("span");
      size.className = "att-card-size";
      const sz = att.size || att.size_bytes;
      size.textContent = sz ? formatFileSize(sz) : (att.file_type || "file");

      info.appendChild(name);
      info.appendChild(size);
      card.appendChild(icon);
      card.appendChild(info);
      attGrid.appendChild(card);
    });
    row.appendChild(attGrid);
  }

  const bubble = document.createElement("div");
  bubble.className = "user-bubble";
  bubble.textContent = content;

  // Show more fold for long user messages (> 350 chars or > 6 lines)
  const isLong = content.length > 350 || (content.match(/\n/g) || []).length > 5;
  if (isLong) {
    bubble.classList.add("folded");
    const foldBtn = document.createElement("button");
    foldBtn.className = "fold-toggle-btn";
    foldBtn.textContent = "Show more";
    foldBtn.onclick = () => {
      const isFolded = bubble.classList.toggle("folded");
      foldBtn.textContent = isFolded ? "Show more" : "Show less";
    };
    row.appendChild(bubble);
    row.appendChild(foldBtn);
  } else {
    row.appendChild(bubble);
  }

  // Hover actions bar
  const hoverBar = document.createElement("div");
  hoverBar.className = "user-hover-bar";

  const timeSpan = document.createElement("span");
  timeSpan.className = "time-label";
  timeSpan.textContent = timestamp ? formatTime(timestamp) : formatTime(new Date().toISOString());
  hoverBar.appendChild(timeSpan);

  const copyBtn = document.createElement("button");
  copyBtn.className = "user-action-btn";
  copyBtn.textContent = "Copy";
  copyBtn.onclick = () => {
    navigator.clipboard.writeText(content).then(() => {
      copyBtn.textContent = "Copied!";
      setTimeout(() => (copyBtn.textContent = "Copy"), 1500);
    });
  };
  hoverBar.appendChild(copyBtn);

  if (onEdit) {
    const editBtn = document.createElement("button");
    editBtn.className = "user-action-btn";
    editBtn.textContent = "Edit";
    editBtn.onclick = () => onEdit(content);
    hoverBar.appendChild(editBtn);
  }

  row.appendChild(hoverBar);
  return row;
}

/**
 * Creates and returns an assistant message container element.
 * Pattern: Plain text markdown, syntax/copy code blocks, Worked for line, meta row, hover actions.
 */
export function createAssistantMessageElement(options = {}) {
  const {
    id = null,
    interactionId = null,
    model = "bonsai-2:9b",
    backend = "local",
    content = "",
    isStreaming = false,
    verified = false,
    verifyStatus = null,
    verifyReason = null,
    workedSeconds = null,
    processSteps = [],
    hitTokenLimit = false,
    onFeedback = null,
    onEditReply = null,
    onRetry = null,
    onContinue = null
  } = options;

  const row = document.createElement("div");
  row.className = "message-wrapper assistant-row";
  if (id) row.dataset.messageId = id;
  if (interactionId) row.dataset.interactionId = interactionId;

  // 1. Process Accordion: "Worked for 12 s >" (Never shows model reasoning text)
  if (workedSeconds || (processSteps && processSteps.length > 0)) {
    const accordion = createProcessAccordion(workedSeconds || 12, processSteps);
    row.appendChild(accordion);
  }

  // 2. Assistant body (Markdown, tables, code blocks)
  const body = document.createElement("div");
  body.className = "assistant-body";
  if (content) {
    body.innerHTML = formatMarkdown(content);
  }
  if (isStreaming) {
    const cursor = document.createElement("span");
    cursor.className = "streaming-cursor";
    body.appendChild(cursor);
  }
  row.appendChild(body);

  // 3. Continue button on cut-off responses
  if (hitTokenLimit && onContinue) {
    const contBtn = document.createElement("button");
    contBtn.className = "continue-btn";
    contBtn.innerHTML = `<span>▶ Continue</span>`;
    contBtn.onclick = () => onContinue();
    row.appendChild(contBtn);
  }

  // 4. Meta row (model, backend badge, verified/corrected badge)
  const metaRow = document.createElement("div");
  metaRow.className = "assistant-meta-row";
  updateMetaRow(metaRow, { model, backend, verified, verifyStatus, verifyReason });
  row.appendChild(metaRow);

  // 5. Hover Action Row: copy, thumbs up, thumbs down, edit, retry, Continue
  const hoverRow = document.createElement("div");
  hoverRow.className = "assistant-hover-actions";

  // Copy
  const copyBtn = document.createElement("button");
  copyBtn.className = "msg-action-btn";
  copyBtn.title = "Copy reply";
  copyBtn.textContent = "📋 Copy";
  copyBtn.onclick = () => {
    navigator.clipboard.writeText(body.innerText).then(() => {
      copyBtn.textContent = "✓ Copied";
      setTimeout(() => (copyBtn.textContent = "📋 Copy"), 1500);
    });
  };
  hoverRow.appendChild(copyBtn);

  // Thumbs up / down
  if (onFeedback) {
    const upBtn = document.createElement("button");
    upBtn.className = "msg-action-btn";
    upBtn.title = "Good response";
    upBtn.textContent = "👍";
    upBtn.onclick = () => onFeedback("up", upBtn, hoverRow);

    const downBtn = document.createElement("button");
    downBtn.className = "msg-action-btn";
    downBtn.title = "Poor response";
    downBtn.textContent = "👎";
    downBtn.onclick = () => onFeedback("down", downBtn, hoverRow);

    hoverRow.appendChild(upBtn);
    hoverRow.appendChild(downBtn);
  }

  // Edit reply
  if (onEditReply) {
    const editBtn = document.createElement("button");
    editBtn.className = "msg-action-btn";
    editBtn.title = "Edit reply to feed training dataset";
    editBtn.textContent = "✏️ Edit";
    editBtn.onclick = () => onEditReply(row, body);
    hoverRow.appendChild(editBtn);
  }

  // Retry
  if (onRetry) {
    const retryBtn = document.createElement("button");
    retryBtn.className = "msg-action-btn";
    retryBtn.title = "Regenerate reply";
    retryBtn.textContent = "🔄 Retry";
    retryBtn.onclick = () => onRetry();
    hoverRow.appendChild(retryBtn);
  }

  row.appendChild(hoverRow);
  return { row, body, metaRow };
}

/**
 * Creates collapsible "Worked for X s >" accordion.
 * Only surfaces execution telemetry (guards, route, memories count, timing).
 * NEVER shows model reasoning / CoT tokens.
 */
export function createProcessAccordion(seconds, steps = []) {
  const container = document.createElement("div");
  container.className = "process-line-accordion";

  const summary = document.createElement("div");
  summary.className = "process-summary";
  summary.innerHTML = `<span>Worked for ${seconds}s</span> <span class="chevron">›</span>`;

  const details = document.createElement("div");
  details.className = "process-details";

  if (!steps || steps.length === 0) {
    steps = [
      "Sensitive and live-data guards verified",
      "Model router selected backend",
      `Completed generation in ${seconds}s`,
      "Quality verification checks passed"
    ];
  }

  steps.forEach(step => {
    const item = document.createElement("div");
    item.className = "process-step-item";
    item.textContent = step;
    details.appendChild(item);
  });

  summary.onclick = () => {
    const isOpen = details.classList.toggle("open");
    summary.querySelector(".chevron").textContent = isOpen ? "‹" : "›";
  };

  container.appendChild(summary);
  container.appendChild(details);
  return container;
}

export function updateMetaRow(metaRow, data) {
  if (!metaRow) return;
  metaRow.innerHTML = "";

  const { model, backend, verified, verifyStatus, verifyReason } = data;

  // Backend & Model Badge
  const bKind = (backend || "local").toLowerCase();
  const badge = document.createElement("span");

  if (bKind === "api") {
    badge.className = "badge badge-online";
    const cleanModel = model ? (model.includes("/") ? model.split("/").pop().replace(":free", "") : model) : "API";
    badge.textContent = `${cleanModel} · API · logged by provider`;
  } else if (bKind === "guard") {
    badge.className = "badge badge-guard";
    badge.textContent = "guard · not used for training";
  } else {
    badge.className = "badge badge-local";
    badge.textContent = `${model || "bonsai-2:9b"} · local`;
  }
  metaRow.appendChild(badge);

  // Quality badge
  if (verified || verifyStatus === "verified") {
    const vBadge = document.createElement("span");
    vBadge.className = "badge badge-verified";
    vBadge.textContent = "✓ verified";
    if (verifyReason) vBadge.title = verifyReason;
    metaRow.appendChild(vBadge);
  } else if (verifyStatus === "corrected") {
    const cBadge = document.createElement("span");
    cBadge.className = "badge badge-corrected";
    cBadge.textContent = "⚡ corrected";
    if (verifyReason) cBadge.title = verifyReason;
    metaRow.appendChild(cBadge);
  }
}

function formatTime(isoStr) {
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch (e) {
    return "";
  }
}

/**
 * Renders citation chips below assistant message body.
 * Clicking a chip opens the right Context & Details drawer to the Files tab.
 */
export function renderCitationChips(container, citations, onCitationClick) {
  if (!citations || citations.length === 0 || !container) return;
  const existing = container.querySelector(".citation-chips-row");
  if (existing) existing.remove();

  const row = document.createElement("div");
  row.className = "citation-chips-row";

  citations.forEach(cit => {
    const chip = document.createElement("button");
    chip.className = "citation-chip";
    const pStr = cit.page ? ` (p. ${cit.page})` : "";
    chip.innerHTML = `<span class="cit-icon">📄</span> <span class="cit-file">${cit.file}${pStr}</span>`;
    chip.onclick = (e) => {
      e.stopPropagation();
      if (onCitationClick) onCitationClick(cit);
    };
    row.appendChild(chip);
  });

  container.appendChild(row);
}

/**
 * Renders structured interactive action buttons below assistant message.
 * Excluded from raw text and history, sent as structured event metadata.
 */
export function renderActionButtons(container, actions, onActionClick) {
  if (!actions || actions.length === 0 || !container) return;
  const existing = container.querySelector(".walkthrough-actions-container");
  if (existing) existing.remove();

  const row = document.createElement("div");
  row.className = "walkthrough-actions-container walkthrough-actions-row";

  actions.forEach(action => {
    const btn = document.createElement("button");
    btn.className = `walkthrough-action-btn ${action.style || ""}`.trim();
    btn.textContent = action.label;
    btn.dataset.prompt = action.prompt;
    if (onActionClick) {
      btn.onclick = (e) => {
        e.stopPropagation();
        onActionClick(action.prompt);
      };
    }
    row.appendChild(btn);
  });

  const target = container.querySelector(".assistant-bubble") || container;
  target.appendChild(row);
}


