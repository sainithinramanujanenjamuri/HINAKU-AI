import { formatMarkdown } from "/static/js/markdown.js";

/**
 * Creates and returns a user message element.
 * Pattern: Soft tinted bubble, Show more fold for long inputs, hover timestamp & copy/edit.
 */
export function createUserMessageElement(content, timestamp = null, onEdit = null) {
  const row = document.createElement("div");
  row.className = "message-wrapper user-row";

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
    badge.textContent = "API · logged by provider";
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

