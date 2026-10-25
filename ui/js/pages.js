/**
 * Full page manager for Memory, Dataset, Ratings, and Training Approval
 */

export function renderMemoryPage(container, memories, onEdit, onDelete) {
  if (!container) return;
  container.innerHTML = "";

  const title = document.createElement("h2");
  title.className = "page-title";
  title.textContent = "What HINAKU remembers";
  container.appendChild(title);

  const sub = document.createElement("p");
  sub.style.cssText = "color: var(--text-secondary); margin: 6px 0 20px 0; font-size: 13.5px;";
  sub.textContent = "Personal facts and preferences extracted locally and injected into context.";
  container.appendChild(sub);

  const list = document.createElement("div");
  list.className = "memory-list";

  if (!memories || memories.length === 0) {
    list.innerHTML = `<div style="color: var(--text-tertiary); font-style: italic;">No memories recorded yet.</div>`;
    container.appendChild(list);
    return;
  }

  memories.forEach(mem => {
    const card = document.createElement("div");
    card.className = "memory-item-card";

    const content = document.createElement("div");
    content.className = "memory-text";
    content.innerHTML = `
      <div>${mem.text}</div>
      <div class="memory-meta">Recorded: ${new Date(mem.created_at).toLocaleDateString()}</div>
    `;

    const actions = document.createElement("div");
    actions.className = "memory-actions";

    const editBtn = document.createElement("button");
    editBtn.className = "user-action-btn";
    editBtn.textContent = "✏️ Edit";
    editBtn.onclick = () => onEdit(mem.id, mem.text);

    const delBtn = document.createElement("button");
    delBtn.className = "user-action-btn";
    delBtn.textContent = "🗑️ Delete";
    delBtn.onclick = () => onDelete(mem.id);

    actions.appendChild(editBtn);
    actions.appendChild(delBtn);

    card.appendChild(content);
    card.appendChild(actions);
    list.appendChild(card);
  });

  container.appendChild(list);
}

export function renderRatingsPage(container, ratings) {
  if (!container) return;
  container.innerHTML = "";

  const title = document.createElement("h2");
  title.className = "page-title";
  title.textContent = "Model Ratings & Feedback";
  container.appendChild(title);

  const sub = document.createElement("p");
  sub.style.cssText = "color: var(--text-secondary); margin: 6px 0 20px 0; font-size: 13.5px;";
  sub.textContent = "Feedback scores and response timings across local and online model backends.";
  container.appendChild(sub);

  const table = document.createElement("table");
  table.className = "data-table";
  table.innerHTML = `
    <thead>
      <tr>
        <th>Model</th>
        <th>Backend</th>
        <th>👍 Up</th>
        <th>👎 Down</th>
        <th>Upvote %</th>
        <th>Avg Latency</th>
      </tr>
    </thead>
    <tbody>
      ${ratings.map(r => `
        <tr>
          <td><strong>${r.model}</strong></td>
          <td><span class="badge ${r.backend === 'api' ? 'badge-online' : 'badge-local'}">${r.backend}</span></td>
          <td>${r.thumbs_up}</td>
          <td>${r.thumbs_down}</td>
          <td>${r.upvote_pct}%</td>
          <td>${r.avg_latency_ms} ms</td>
        </tr>
      `).join("")}
    </tbody>
  `;

  container.appendChild(table);
}

export function renderDatasetPage(container, datasetData, onBuild) {
  if (!container) return;
  container.innerHTML = "";

  const title = document.createElement("h2");
  title.className = "page-title";
  title.textContent = "Dataset Curation & Review";
  container.appendChild(title);

  const sub = document.createElement("p");
  sub.style.cssText = "color: var(--text-secondary); margin: 6px 0 20px 0; font-size: 13.5px;";
  sub.textContent = "Interaction pairs curated from thumbs-up and edited replies for the 6-month self-build cycle.";
  container.appendChild(sub);

  const stats = document.createElement("div");
  stats.className = "score-comparison-grid";
  stats.innerHTML = `
    <div class="score-box">
      <div class="context-card-title">Curated Candidates</div>
      <div class="score-value">${datasetData.candidate_count || 0}</div>
    </div>
    <div class="score-box">
      <div class="context-card-title">Minimum Required</div>
      <div class="score-value">${datasetData.min_required || 200}</div>
    </div>
  `;
  container.appendChild(stats);

  const list = document.createElement("div");
  list.className = "memory-list";
  list.style.marginTop = "20px";

  (datasetData.candidates || []).forEach(cand => {
    const card = document.createElement("div");
    card.className = "memory-item-card";
    card.innerHTML = `
      <div class="memory-text">
        <div style="font-weight: 500; margin-bottom: 4px;">User: ${cand.user_prompt}</div>
        <div style="color: var(--text-secondary);">HINAKU: ${cand.answer}</div>
      </div>
      <div><span class="badge badge-local">${cand.model}</span></div>
    `;
    list.appendChild(card);
  });

  container.appendChild(list);
}

export function renderSettingsPage(container, settingsData, onSave, onExport, onWipe) {
  if (!container) return;
  container.innerHTML = "";

  const title = document.createElement("h2");
  title.className = "page-title";
  title.textContent = "Settings & Preferences";
  container.appendChild(title);

  const sub = document.createElement("p");
  sub.style.cssText = "color: var(--text-secondary); margin: 6px 0 20px 0; font-size: 13.5px;";
  sub.textContent = "Configure local model inference, memory extraction, privacy safeguards, and hotkeys.";
  container.appendChild(sub);

  const section = document.createElement("div");
  section.className = "settings-section";

  // 1. Model & Engine Card
  section.innerHTML = `
    <div class="settings-card">
      <div class="settings-card-header">
        <span class="settings-card-title">Local Model & Router</span>
        <span class="settings-card-desc">Select the default offline model and routing behavior.</span>
      </div>
      <div class="settings-row">
        <div class="settings-label-group">
          <span class="settings-label">Default Local Model</span>
          <span class="settings-sublabel">Loaded in VRAM on startup with keep_alive</span>
        </div>
        <select id="setting-page-model" class="settings-select">
          <option value="bonsai-2:9b">bonsai-2:9b (default)</option>
          <option value="gemma3:4b">gemma3:4b</option>
          <option value="qwen3.5:4b">qwen3.5:4b</option>
        </select>
      </div>
      <div class="settings-row">
        <div class="settings-label-group">
          <span class="settings-label">Router Mode</span>
          <span class="settings-sublabel">Auto routes complex queries to API (except private chats)</span>
        </div>
        <select id="setting-page-router" class="settings-select">
          <option value="auto">Auto (Hybrid)</option>
          <option value="local_only">Local only (Never calls API)</option>
          <option value="api_only">API only</option>
        </select>
      </div>
    </div>

    <!-- 2. Memory & Privacy Card -->
    <div class="settings-card">
      <div class="settings-card-header">
        <span class="settings-card-title">Memory & Privacy</span>
        <span class="settings-card-desc">Control fact extraction and local data storage.</span>
      </div>
      <div class="settings-row">
        <div class="settings-label-group">
          <span class="settings-label">Enable Memory Extraction</span>
          <span class="settings-sublabel">Extracts durable facts locally after each turn</span>
        </div>
        <label class="toggle-switch">
          <input type="checkbox" id="setting-page-memory" ${settingsData?.memory_enabled !== false ? 'checked' : ''}>
          <span class="toggle-slider"></span>
        </label>
      </div>
      <div class="settings-row">
        <div class="settings-label-group">
          <span class="settings-label">Reduced Motion</span>
          <span class="settings-sublabel">Disables ambient particle motion and fast-forwards transitions</span>
        </div>
        <label class="toggle-switch">
          <input type="checkbox" id="setting-page-motion" ${settingsData?.reduced_motion ? 'checked' : ''}>
          <span class="toggle-slider"></span>
        </label>
      </div>
    </div>

    <!-- 3. Keyboard Shortcuts Card -->
    <div class="settings-card">
      <div class="settings-card-header">
        <span class="settings-card-title">Keyboard Shortcuts</span>
        <span class="settings-card-desc">Quick desktop keybindings for swift navigation.</span>
      </div>
      <div class="shortcut-table">
        <div class="shortcut-row">
          <span>Search conversations</span>
          <kbd class="kbd-badge">Ctrl + K</kbd>
        </div>
        <div class="shortcut-row">
          <span>New conversation</span>
          <kbd class="kbd-badge">Ctrl + N</kbd>
        </div>
        <div class="shortcut-row">
          <span>Toggle Sidebar</span>
          <kbd class="kbd-badge">Ctrl + B</kbd>
        </div>
        <div class="shortcut-row">
          <span>Toggle Context Panel</span>
          <kbd class="kbd-badge">Ctrl + .</kbd>
        </div>
        <div class="shortcut-row">
          <span>Cycle Privacy Mode</span>
          <kbd class="kbd-badge">Ctrl + Shift + P</kbd>
        </div>
        <div class="shortcut-row">
          <span>Stop Generation</span>
          <kbd class="kbd-badge">Esc</kbd>
        </div>
        <div class="shortcut-row">
          <span>Send Message / Newline</span>
          <span><kbd class="kbd-badge">Enter</kbd> / <kbd class="kbd-badge">Shift + Enter</kbd></span>
        </div>
      </div>
    </div>

    <!-- 4. Data Export & Full Wipe -->
    <div class="settings-card">
      <div class="settings-card-header">
        <span class="settings-card-title">Data Storage & Reset</span>
        <span class="settings-card-desc">Export your interactions or permanently wipe all databases.</span>
      </div>
      <div class="danger-button-row">
        <button id="btn-page-export" class="action-btn-secondary">Export All Data</button>
        <button id="btn-page-wipe" class="action-btn-danger">Wipe All Data</button>
      </div>
    </div>
  `;

  container.appendChild(section);

  // Hook up event handlers
  const modelSelect = section.querySelector("#setting-page-model");
  if (modelSelect && settingsData?.default_local_model) {
    modelSelect.value = settingsData.default_local_model;
    modelSelect.onchange = () => onSave({ default_local_model: modelSelect.value });
  }

  const routerSelect = section.querySelector("#setting-page-router");
  if (routerSelect && settingsData?.router_mode) {
    routerSelect.value = settingsData.router_mode;
    routerSelect.onchange = () => onSave({ router_mode: routerSelect.value });
  }

  const memoryToggle = section.querySelector("#setting-page-memory");
  if (memoryToggle) {
    memoryToggle.onchange = () => onSave({ memory_enabled: memoryToggle.checked });
  }

  const motionToggle = section.querySelector("#setting-page-motion");
  if (motionToggle) {
    motionToggle.onchange = () => onSave({ reduced_motion: motionToggle.checked });
  }

  const exportBtn = section.querySelector("#btn-page-export");
  if (exportBtn && onExport) {
    exportBtn.onclick = onExport;
  }

  const wipeBtn = section.querySelector("#btn-page-wipe");
  if (wipeBtn && onWipe) {
    wipeBtn.onclick = onWipe;
  }
}

