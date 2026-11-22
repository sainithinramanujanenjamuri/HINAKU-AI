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

// =============================================================================
// Phase 1 Milestone 7: Step 4 Desktop Views (Projects, Tasks, Learning)
// =============================================================================

/**
 * Projects View
 */
export function renderProjectsPage(container, { projects = [], activeProjectId = null, onSelectActiveProject, onRefresh }) {
  if (!container) return;
  container.innerHTML = "";

  const header = document.createElement("div");
  header.className = "view-header-bar";
  header.innerHTML = `
    <div>
      <h2 class="page-title">Projects & Architecture</h2>
      <p class="page-subtitle">Domain boundaries, tech stacks, repository indexing, and architectural context.</p>
    </div>
    <div class="view-header-actions">
      <button id="btn-create-project-modal" class="action-btn-primary">+ Register Project</button>
    </div>
  `;
  container.appendChild(header);

  // Filter toolbar
  const toolbar = document.createElement("div");
  toolbar.className = "view-toolbar";
  toolbar.innerHTML = `
    <div class="search-box-inline">
      <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
      <input type="text" id="filter-projects-search" class="toolbar-input" placeholder="Search projects by name, purpose, tech...">
    </div>
    <div class="toolbar-filters">
      <select id="filter-projects-status" class="toolbar-select">
        <option value="all">All Statuses</option>
        <option value="active">Active</option>
        <option value="paused">Paused</option>
        <option value="completed">Completed</option>
        <option value="archived">Archived</option>
      </select>
      <select id="filter-projects-conf" class="toolbar-select">
        <option value="all">All Confidentiality</option>
        <option value="internal">Internal</option>
        <option value="confidential">Confidential</option>
        <option value="restricted">Restricted</option>
      </select>
    </div>
  `;
  container.appendChild(toolbar);

  // Projects list container
  const listContainer = document.createElement("div");
  listContainer.id = "projects-list-container";
  listContainer.className = "cards-grid";
  container.appendChild(listContainer);

  // Modal container for Create Project & Knowledge Details
  const subModalContainer = document.createElement("div");
  subModalContainer.id = "projects-submodal-container";
  container.appendChild(subModalContainer);

  function applyFilters() {
    const query = toolbar.querySelector("#filter-projects-search").value.trim().toLowerCase();
    const stFilter = toolbar.querySelector("#filter-projects-status").value;
    const confFilter = toolbar.querySelector("#filter-projects-conf").value;

    const filtered = projects.filter(p => {
      const matchQ = !query ||
        p.name.toLowerCase().includes(query) ||
        (p.purpose && p.purpose.toLowerCase().includes(query)) ||
        (p.tech_stack && p.tech_stack.some(t => t.toLowerCase().includes(query)));
      const matchSt = stFilter === "all" || (p.status || "").toLowerCase() === stFilter;
      const matchConf = confFilter === "all" || (p.confidentiality || "").toLowerCase() === confFilter;
      return matchQ && matchSt && matchConf;
    });

    renderProjectCards(filtered);
  }

  function renderProjectCards(items) {
    listContainer.innerHTML = "";
    if (items.length === 0) {
      listContainer.innerHTML = `
        <div class="empty-state-card">
          <span style="font-size: 24px;">📂</span>
          <div style="font-weight: 500; margin-top: 6px;">No matching projects found</div>
          <div style="color: var(--text-tertiary); font-size: 13px;">Register a new project or adjust the filter query.</div>
        </div>
      `;
      return;
    }

    items.forEach(proj => {
      const card = document.createElement("div");
      const isActive = proj.project_id === activeProjectId;
      card.className = `entity-card ${isActive ? 'entity-card-active' : ''}`;

      const confVal = (proj.confidentiality || "internal").toLowerCase();
      const confBadgeClass = `badge-conf-${confVal}`;

      card.innerHTML = `
        <div class="card-header">
          <div class="card-title-group">
            <span class="card-title">${proj.name}</span>
            <div class="card-badges">
              <span class="badge ${confBadgeClass}">${confVal}</span>
              <span class="badge badge-status-${(proj.status || 'active').toLowerCase()}">${proj.status || 'active'}</span>
              ${isActive ? '<span class="badge badge-active-indicator">✓ Active in Chat</span>' : ''}
            </div>
          </div>
        </div>
        <div class="card-body">
          <div class="card-purpose">${proj.purpose || 'No stated purpose.'}</div>
          ${proj.description ? `<div class="card-desc">${proj.description}</div>` : ''}
          <div class="card-meta-row">
            <span class="meta-label">Tech Stack:</span>
            <div class="chips-row">
              ${(proj.tech_stack && proj.tech_stack.length > 0)
                ? proj.tech_stack.map(t => `<span class="tag-chip">${t}</span>`).join('')
                : '<span style="color: var(--text-tertiary); font-size: 12px;">Not specified</span>'}
            </div>
          </div>
          <div class="card-meta-row">
            <span class="meta-label">Repo:</span>
            <span class="mono-path">${proj.repo_path || '<span style="color: var(--text-tertiary);">None configured</span>'}</span>
          </div>
        </div>
        <div class="card-footer">
          <button class="btn-select-active action-btn-secondary" title="${isActive ? 'Clear Active Project' : 'Set as Active Project for Chat'}">
            ${isActive ? 'Clear Active' : 'Set as Active'}
          </button>
          <button class="btn-knowledge action-btn-secondary">Knowledge & Details</button>
          ${proj.repo_path ? '<button class="btn-index-repo action-btn-secondary">Index Repo</button>' : ''}
          <button class="btn-delete-proj action-btn-danger">Delete</button>
        </div>
      `;

      card.querySelector(".btn-select-active").onclick = () => {
        if (isActive) {
          onSelectActiveProject(null, null, null);
        } else {
          onSelectActiveProject(proj.project_id, proj.name, proj.confidentiality);
        }
      };

      card.querySelector(".btn-knowledge").onclick = () => {
        openKnowledgeDetailsModal(proj);
      };

      const indexBtn = card.querySelector(".btn-index-repo");
      if (indexBtn) {
        indexBtn.onclick = async () => {
          indexBtn.disabled = true;
          indexBtn.textContent = "Indexing...";
          try {
            const res = await fetch(`/api/projects/${proj.project_id}/index_repo`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ max_files: 500 })
            });
            if (res.ok) {
              const resData = await res.json();
              alert(`Repository indexed successfully! ${resData.indexed_count} files recorded.`);
            } else {
              const err = await res.json();
              alert(`Repository indexing failed: ${err.detail || "Unknown error"}`);
            }
          } catch (e) {
            alert(`Error indexing repository: ${e.message}`);
          } finally {
            indexBtn.disabled = false;
            indexBtn.textContent = "Index Repo";
          }
        };
      }

      card.querySelector(".btn-delete-proj").onclick = async () => {
        if (confirm(`Delete project "${proj.name}"?`)) {
          try {
            const res = await fetch(`/api/projects/${proj.project_id}`, { method: "DELETE" });
            if (res.ok) {
              if (proj.project_id === activeProjectId) {
                onSelectActiveProject(null, null, null);
              }
              onRefresh();
            } else {
              const err = await res.json();
              alert(`Failed to delete project: ${err.detail || "Unknown error"}`);
            }
          } catch (e) {
            alert(`Error deleting project: ${e.message}`);
          }
        }
      };

      listContainer.appendChild(card);
    });
  }

  // Hook toolbar filters
  toolbar.querySelector("#filter-projects-search").oninput = applyFilters;
  toolbar.querySelector("#filter-projects-status").onchange = applyFilters;
  toolbar.querySelector("#filter-projects-conf").onchange = applyFilters;

  // New Project modal opener
  header.querySelector("#btn-create-project-modal").onclick = () => {
    openCreateProjectModal();
  };

  function openCreateProjectModal() {
    subModalContainer.innerHTML = `
      <div class="modal-overlay">
        <div class="modal-container medium-modal">
          <div class="modal-header">
            <h2>Register New Project</h2>
            <button class="icon-btn btn-close-submodal">✕</button>
          </div>
          <div class="modal-form-body">
            <div class="form-group">
              <label>Project Name *</label>
              <input type="text" id="new-proj-name" class="form-input" placeholder="e.g. Apollo Engine">
            </div>
            <div class="form-group">
              <label>Core Objective / Purpose *</label>
              <textarea id="new-proj-purpose" class="form-textarea" rows="2" placeholder="Primary goal and architecture boundary..."></textarea>
            </div>
            <div class="form-group">
              <label>Description (Optional)</label>
              <textarea id="new-proj-desc" class="form-textarea" rows="2" placeholder="Additional architectural context..."></textarea>
            </div>
            <div class="form-row-2">
              <div class="form-group">
                <label>Confidentiality Classification</label>
                <select id="new-proj-conf" class="form-select">
                  <option value="internal">Internal (Local or API fallback allowed)</option>
                  <option value="confidential">Confidential (Strictly offline, zero cloud fallback)</option>
                  <option value="restricted">Restricted (Strictly offline, suppressed index details)</option>
                </select>
              </div>
              <div class="form-group">
                <label>Tech Stack (comma separated)</label>
                <input type="text" id="new-proj-stack" class="form-input" placeholder="Python, FastAPI, SQLite">
              </div>
            </div>
            <div class="form-group">
              <label>Local Repository Path (Optional)</label>
              <input type="text" id="new-proj-repo" class="form-input" placeholder="e.g. D:\\Projects\\Apollo">
            </div>
          </div>
          <div class="modal-footer">
            <button class="action-btn-secondary btn-close-submodal">Cancel</button>
            <button id="btn-submit-new-project" class="action-btn-primary">Register Project</button>
          </div>
        </div>
      </div>
    `;

    subModalContainer.querySelectorAll(".btn-close-submodal").forEach(b => {
      b.onclick = () => { subModalContainer.innerHTML = ""; };
    });

    subModalContainer.querySelector("#btn-submit-new-project").onclick = async () => {
      const name = subModalContainer.querySelector("#new-proj-name").value.trim();
      const purpose = subModalContainer.querySelector("#new-proj-purpose").value.trim();
      const description = subModalContainer.querySelector("#new-proj-desc").value.trim();
      const confidentiality = subModalContainer.querySelector("#new-proj-conf").value;
      const stackStr = subModalContainer.querySelector("#new-proj-stack").value.trim();
      const repo_path = subModalContainer.querySelector("#new-proj-repo").value.trim() || null;

      if (!name || !purpose) {
        alert("Project Name and Purpose are required.");
        return;
      }

      const tech_stack = stackStr ? stackStr.split(",").map(s => s.trim()).filter(Boolean) : [];

      try {
        const res = await fetch("/api/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, purpose, description, confidentiality, tech_stack, repo_path })
        });
        if (res.ok) {
          subModalContainer.innerHTML = "";
          onRefresh();
        } else {
          const err = await res.json();
          alert(`Could not create project: ${err.detail || "Validation error"}`);
        }
      } catch (e) {
        alert(`Error: ${e.message}`);
      }
    };
  }

  async function openKnowledgeDetailsModal(proj) {
    subModalContainer.innerHTML = `
      <div class="modal-overlay">
        <div class="modal-container wide-modal">
          <div class="modal-header">
            <div>
              <h2>${proj.name} — Knowledge Base</h2>
              <span class="badge badge-conf-${(proj.confidentiality || 'internal').toLowerCase()}">${proj.confidentiality}</span>
            </div>
            <button class="icon-btn btn-close-submodal">✕</button>
          </div>
          <div class="modal-form-body">
            <div class="knowledge-controls-row">
              <h3>Structured Knowledge Items</h3>
              <button id="btn-show-add-knowledge" class="action-btn-secondary">+ Add Item</button>
            </div>
            <div id="add-knowledge-form" class="hidden form-subpanel">
              <div class="form-row-2">
                <div class="form-group">
                  <label>Category</label>
                  <select id="new-know-cat" class="form-select">
                    <option value="decisions">Decisions</option>
                    <option value="architecture">Architecture</option>
                    <option value="tech_stack">Tech Stack</option>
                    <option value="conventions">Conventions</option>
                    <option value="domain_facts">Domain Facts</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>Title</label>
                  <input type="text" id="new-know-title" class="form-input" placeholder="Short summary title">
                </div>
              </div>
              <div class="form-group">
                <label>Content</label>
                <textarea id="new-know-content" class="form-textarea" rows="3" placeholder="Concrete knowledge or decision rationale..."></textarea>
              </div>
              <div class="knowledge-form-actions">
                <button id="btn-cancel-add-know" class="action-btn-secondary">Cancel</button>
                <button id="btn-save-know-item" class="action-btn-primary">Save Knowledge Item</button>
              </div>
            </div>
            <div id="project-knowledge-items-list" class="knowledge-items-list">
              <div style="color: var(--text-tertiary);">Loading knowledge items...</div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="action-btn-secondary btn-close-submodal">Close</button>
          </div>
        </div>
      </div>
    `;

    subModalContainer.querySelectorAll(".btn-close-submodal").forEach(b => {
      b.onclick = () => { subModalContainer.innerHTML = ""; };
    });

    const addForm = subModalContainer.querySelector("#add-knowledge-form");
    const showAddBtn = subModalContainer.querySelector("#btn-show-add-knowledge");
    showAddBtn.onclick = () => { addForm.classList.toggle("hidden"); };
    subModalContainer.querySelector("#btn-cancel-add-know").onclick = () => { addForm.classList.add("hidden"); };

    async function loadKnowledge() {
      const listEl = subModalContainer.querySelector("#project-knowledge-items-list");
      try {
        const res = await fetch(`/api/projects/${proj.project_id}/knowledge`);
        if (res.ok) {
          const items = await res.json();
          if (items.length === 0) {
            listEl.innerHTML = `<div style="color: var(--text-tertiary); font-style: italic; padding: 12px 0;">No knowledge items registered for this project yet.</div>`;
            return;
          }
          listEl.innerHTML = items.map(it => `
            <div class="knowledge-item-card">
              <div class="knowledge-item-header">
                <span class="badge badge-category">${it.category}</span>
                <span class="knowledge-title">${it.title}</span>
                <span class="badge badge-status-${(it.provenance?.verification_status || 'accepted').toLowerCase()}">
                  ${it.provenance?.verification_status || 'accepted'}
                </span>
              </div>
              <div class="knowledge-content">${it.content}</div>
              <div class="knowledge-provenance">
                <span>Authority: ${it.provenance?.source_authority || 'owner'}</span>
                <span>Confidence: ${Math.round((it.provenance?.claim_confidence || 1.0) * 100)}%</span>
              </div>
            </div>
          `).join("");
        } else {
          listEl.innerHTML = `<div style="color: var(--color-error);">Could not load knowledge items.</div>`;
        }
      } catch (e) {
        listEl.innerHTML = `<div style="color: var(--color-error);">${e.message}</div>`;
      }
    }

    subModalContainer.querySelector("#btn-save-know-item").onclick = async () => {
      const category = subModalContainer.querySelector("#new-know-cat").value;
      const title = subModalContainer.querySelector("#new-know-title").value.trim();
      const content = subModalContainer.querySelector("#new-know-content").value.trim();

      if (!title || !content) {
        alert("Title and Content are required.");
        return;
      }

      try {
        const res = await fetch(`/api/projects/${proj.project_id}/knowledge`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category, title, content })
        });
        if (res.ok) {
          addForm.classList.add("hidden");
          subModalContainer.querySelector("#new-know-title").value = "";
          subModalContainer.querySelector("#new-know-content").value = "";
          loadKnowledge();
        } else {
          const err = await res.json();
          alert(`Could not save item: ${err.detail || "Error"}`);
        }
      } catch (e) {
        alert(`Error: ${e.message}`);
      }
    };

    loadKnowledge();
  }

  // Initial render
  applyFilters();
}

/**
 * Tasks View
 */
export function renderTasksPage(container, { tasks = [], projects = [], activeProjectId = null, onRefresh, onApprove, onShowHistory }) {
  if (!container) return;
  container.innerHTML = "";

  const header = document.createElement("div");
  header.className = "view-header-bar";
  header.innerHTML = `
    <div>
      <h2 class="page-title">Tasks & Operational DAG</h2>
      <p class="page-subtitle">Managed tasks, dependency tracking, lifecycle state machines, and scoped critical approvals.</p>
    </div>
    <div class="view-header-actions">
      <button id="btn-create-task-modal" class="action-btn-primary">+ Create Task</button>
    </div>
  `;
  container.appendChild(header);

  // Summary Stat Grid
  const totalCount = tasks.length;
  const queuedCount = tasks.filter(t => t.status === "queued").length;
  const activeCount = tasks.filter(t => t.status === "active").length;
  const pendingApprCount = tasks.filter(t => t.status === "pending_approval").length;
  const completedCount = tasks.filter(t => t.status === "completed").length;

  const statGrid = document.createElement("div");
  statGrid.className = "task-stat-grid";
  statGrid.innerHTML = `
    <div class="task-stat-card">
      <span class="stat-num">${totalCount}</span>
      <span class="stat-name">Total Tasks</span>
    </div>
    <div class="task-stat-card">
      <span class="stat-num color-queued">${queuedCount}</span>
      <span class="stat-name">Queued</span>
    </div>
    <div class="task-stat-card">
      <span class="stat-num color-active">${activeCount}</span>
      <span class="stat-name">In Progress</span>
    </div>
    <div class="task-stat-card ${pendingApprCount > 0 ? 'card-pulse-warning' : ''}">
      <span class="stat-num color-warning">${pendingApprCount}</span>
      <span class="stat-name">Pending Approval</span>
    </div>
    <div class="task-stat-card">
      <span class="stat-num color-completed">${completedCount}</span>
      <span class="stat-name">Completed</span>
    </div>
  `;
  container.appendChild(statGrid);

  // Filter toolbar
  const toolbar = document.createElement("div");
  toolbar.className = "view-toolbar";
  toolbar.innerHTML = `
    <div class="search-box-inline">
      <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
      <input type="text" id="filter-tasks-search" class="toolbar-input" placeholder="Search tasks by title, resource, operation...">
    </div>
    <div class="toolbar-filters">
      <select id="filter-tasks-status" class="toolbar-select">
        <option value="all">All Statuses</option>
        <option value="pending_approval">Pending Approval</option>
        <option value="active">Active (Running)</option>
        <option value="queued">Queued</option>
        <option value="paused">Paused</option>
        <option value="completed">Completed</option>
        <option value="failed">Failed</option>
        <option value="cancelled">Cancelled</option>
      </select>
      <select id="filter-tasks-project" class="toolbar-select">
        <option value="all">All Projects</option>
        ${projects.map(p => `<option value="${p.project_id}">${p.name}</option>`).join("")}
      </select>
    </div>
  `;
  container.appendChild(toolbar);

  // Tasks list container
  const listContainer = document.createElement("div");
  listContainer.id = "tasks-list-container";
  listContainer.className = "tasks-list-vertical";
  container.appendChild(listContainer);

  // Submodal container for Task creation
  const subModalContainer = document.createElement("div");
  subModalContainer.id = "tasks-submodal-container";
  container.appendChild(subModalContainer);

  function applyFilters() {
    const query = toolbar.querySelector("#filter-tasks-search").value.trim().toLowerCase();
    const stFilter = toolbar.querySelector("#filter-tasks-status").value;
    const projFilter = toolbar.querySelector("#filter-tasks-project").value;

    const filtered = tasks.filter(t => {
      const matchQ = !query ||
        t.title.toLowerCase().includes(query) ||
        (t.description && t.description.toLowerCase().includes(query)) ||
        (t.target_resource && t.target_resource.toLowerCase().includes(query)) ||
        (t.operation && t.operation.toLowerCase().includes(query));
      const matchSt = stFilter === "all" || (t.status || "").toLowerCase() === stFilter;
      const matchProj = projFilter === "all" || t.project_id === projFilter;
      return matchQ && matchSt && matchProj;
    });

    renderTaskCards(filtered);
  }

  function renderTaskCards(items) {
    listContainer.innerHTML = "";
    if (items.length === 0) {
      listContainer.innerHTML = `
        <div class="empty-state-card">
          <span style="font-size: 24px;">📋</span>
          <div style="font-weight: 500; margin-top: 6px;">No matching tasks found</div>
          <div style="color: var(--text-tertiary); font-size: 13px;">Create a new operational task or adjust the filters.</div>
        </div>
      `;
      return;
    }

    items.forEach(task => {
      const card = document.createElement("div");
      const isPendingApproval = task.status === "pending_approval";
      card.className = `task-card ${isPendingApproval ? 'task-card-pending-approval' : ''}`;

      const projObj = projects.find(p => p.project_id === task.project_id);
      const projLabel = projObj ? projObj.name : (task.project_id ? task.project_id.slice(0, 8) : "Global");

      card.innerHTML = `
        <div class="task-card-header">
          <div class="task-title-row">
            <span class="task-title">${task.title}</span>
            <div class="task-badges">
              <span class="badge badge-priority-${(task.priority || 'medium').toLowerCase()}">${task.priority || 'medium'}</span>
              <span class="badge badge-task-status-${(task.status || 'queued').toLowerCase()}">${task.status}</span>
              <span class="badge badge-project-tag">📂 ${projLabel}</span>
            </div>
          </div>
        </div>
        <div class="task-card-body">
          ${task.description ? `<div class="task-desc">${task.description}</div>` : ''}
          ${task.critical_action_category ? `
            <div class="critical-action-flag">
              <span class="critical-flag-icon">🛡️</span>
              <div class="critical-flag-text">
                <div><strong>Critical Category:</strong> ${task.critical_action_category}</div>
                <div class="critical-target-op">
                  <span><strong>Target:</strong> <code class="mono-code">${task.target_resource || 'N/A'}</code></span>
                  <span><strong>Op:</strong> <code class="mono-code">${task.operation || 'N/A'}</code></span>
                </div>
              </div>
            </div>
          ` : ''}
          ${task.completion_criteria && task.completion_criteria.length > 0 ? `
            <div class="task-criteria-list">
              <span class="meta-label">Completion Criteria:</span>
              <ul>
                ${task.completion_criteria.map(c => `<li>${c}</li>`).join("")}
              </ul>
            </div>
          ` : ''}
        </div>
        <div class="task-card-footer">
          <div class="task-action-buttons">
            ${isPendingApproval ? `
              <button class="btn-review-approval action-btn-critical">
                🛡️ Review & Approve Action
              </button>
            ` : ''}
            ${task.status === "queued" ? `
              <button class="btn-transition action-btn-secondary" data-to="active">▶ Start</button>
            ` : ''}
            ${task.status === "active" ? `
              <button class="btn-transition action-btn-secondary" data-to="paused">⏸ Pause</button>
              <button class="btn-transition action-btn-secondary" data-to="completed">✓ Complete</button>
              <button class="btn-transition action-btn-secondary" data-to="failed">✕ Fail</button>
            ` : ''}
            ${task.status === "paused" ? `
              <button class="btn-transition action-btn-secondary" data-to="active">▶ Resume</button>
            ` : ''}
            ${!["completed", "cancelled", "failed"].includes(task.status) ? `
              <button class="btn-transition action-btn-secondary" data-to="cancelled">Cancel</button>
            ` : ''}
          </div>
          <div class="task-meta-buttons">
            <button class="btn-history action-btn-subtle" title="View State Transition Audit History">📜 History</button>
            <button class="btn-delete-task action-btn-subtle" title="Delete Task">🗑️</button>
          </div>
        </div>
      `;

      // Handle Review & Approve click
      const reviewBtn = card.querySelector(".btn-review-approval");
      if (reviewBtn) {
        reviewBtn.onclick = () => onApprove(task);
      }

      // Handle Lifecycle Transition clicks
      card.querySelectorAll(".btn-transition").forEach(btn => {
        btn.onclick = async () => {
          const targetStatus = btn.dataset.to;
          const reason = prompt(`Reason for transitioning task to '${targetStatus}':`, `Manual transition to ${targetStatus}`);
          if (!reason) return;
          try {
            const res = await fetch(`/api/tasks/${task.task_id}/transition`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                new_status: targetStatus,
                reason: reason,
                changed_by: "owner",
                owner_approved: targetStatus === "completed"
              })
            });
            if (res.ok) {
              onRefresh();
            } else {
              const err = await res.json();
              alert(`Transition rejected: ${err.detail || "State transition error"}`);
            }
          } catch (e) {
            alert(`Error transitioning task: ${e.message}`);
          }
        };
      });

      // Handle History click
      card.querySelector(".btn-history").onclick = () => {
        onShowHistory(task.task_id, task.title);
      };

      // Handle Delete click
      card.querySelector(".btn-delete-task").onclick = async () => {
        if (confirm(`Delete task "${task.title}"?`)) {
          try {
            const res = await fetch(`/api/tasks/${task.task_id}`, { method: "DELETE" });
            if (res.ok) {
              onRefresh();
            } else {
              const err = await res.json();
              alert(`Failed to delete task: ${err.detail || "Error"}`);
            }
          } catch (e) {
            alert(`Error: ${e.message}`);
          }
        }
      };

      listContainer.appendChild(card);
    });
  }

  // Hook toolbar filters
  toolbar.querySelector("#filter-tasks-search").oninput = applyFilters;
  toolbar.querySelector("#filter-tasks-status").onchange = applyFilters;
  toolbar.querySelector("#filter-tasks-project").onchange = applyFilters;

  // New Task modal opener
  header.querySelector("#btn-create-task-modal").onclick = () => {
    openCreateTaskModal();
  };

  function openCreateTaskModal() {
    subModalContainer.innerHTML = `
      <div class="modal-overlay">
        <div class="modal-container medium-modal">
          <div class="modal-header">
            <h2>Create Managed Task</h2>
            <button class="icon-btn btn-close-submodal">✕</button>
          </div>
          <div class="modal-form-body">
            <div class="form-group">
              <label>Task Title *</label>
              <input type="text" id="new-task-title" class="form-input" placeholder="e.g. Clean up build artifacts in workspace">
            </div>
            <div class="form-group">
              <label>Operational Description</label>
              <textarea id="new-task-desc" class="form-textarea" rows="2" placeholder="Task execution parameters and boundaries..."></textarea>
            </div>
            <div class="form-row-2">
              <div class="form-group">
                <label>Priority</label>
                <select id="new-task-priority" class="form-select">
                  <option value="low">Low</option>
                  <option value="medium" selected>Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
              <div class="form-group">
                <label>Project Scope</label>
                <select id="new-task-project" class="form-select">
                  <option value="">Global (No Project)</option>
                  ${projects.map(p => `<option value="${p.project_id}">${p.name}</option>`).join("")}
                </select>
              </div>
            </div>
            <div class="form-group">
              <label>Critical Action Category (Requires Scoped Owner Approval)</label>
              <select id="new-task-crit-cat" class="form-select">
                <option value="">None (Standard Task)</option>
                <option value="file_modification_or_deletion">File modification or deletion</option>
                <option value="financial_transaction">Financial transactions and purchases</option>
                <option value="external_communication">External communications (emails/calls)</option>
                <option value="system_operation">System operations (install/service modification)</option>
                <option value="security_credential_change">Security and credential modifications</option>
                <option value="self_modification">Self-modification and autonomous code alterations</option>
              </select>
            </div>
            <div class="form-row-2">
              <div class="form-group">
                <label>Target Resource (if critical)</label>
                <input type="text" id="new-task-target" class="form-input" placeholder="e.g. data/scratch/output.log">
              </div>
              <div class="form-group">
                <label>Operation (if critical)</label>
                <input type="text" id="new-task-op" class="form-input" placeholder="e.g. delete_file">
              </div>
            </div>
            <div class="form-group">
              <label>Scope Parameters (JSON format)</label>
              <textarea id="new-task-scope" class="form-textarea mono-textarea" rows="2" placeholder='{"dry_run": false}'></textarea>
            </div>
          </div>
          <div class="modal-footer">
            <button class="action-btn-secondary btn-close-submodal">Cancel</button>
            <button id="btn-submit-new-task" class="action-btn-primary">Create Task</button>
          </div>
        </div>
      </div>
    `;

    subModalContainer.querySelectorAll(".btn-close-submodal").forEach(b => {
      b.onclick = () => { subModalContainer.innerHTML = ""; };
    });

    subModalContainer.querySelector("#btn-submit-new-task").onclick = async () => {
      const title = subModalContainer.querySelector("#new-task-title").value.trim();
      const description = subModalContainer.querySelector("#new-task-desc").value.trim();
      const priority = subModalContainer.querySelector("#new-task-priority").value;
      const project_id = subModalContainer.querySelector("#new-task-project").value || null;
      const critical_action_category = subModalContainer.querySelector("#new-task-crit-cat").value || null;
      const target_resource = subModalContainer.querySelector("#new-task-target").value.trim() || null;
      const operation = subModalContainer.querySelector("#new-task-op").value.trim() || null;
      const scopeStr = subModalContainer.querySelector("#new-task-scope").value.trim();

      if (!title) {
        alert("Task Title is required.");
        return;
      }

      let scope_parameters = {};
      if (scopeStr) {
        try {
          scope_parameters = JSON.parse(scopeStr);
        } catch (e) {
          alert("Scope parameters must be valid JSON.");
          return;
        }
      }

      try {
        const res = await fetch("/api/tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title,
            description,
            priority,
            project_id,
            critical_action_category,
            target_resource,
            operation,
            scope_parameters,
            requires_owner_approval: Boolean(critical_action_category)
          })
        });
        if (res.ok) {
          subModalContainer.innerHTML = "";
          onRefresh();
        } else {
          const err = await res.json();
          alert(`Could not create task: ${err.detail || "Validation error"}`);
        }
      } catch (e) {
        alert(`Error: ${e.message}`);
      }
    };
  }

  // Initial render
  applyFilters();
}

/**
 * Learning & Self-Improvement View
 */
export function renderLearningPage(container, { onRefresh, onWipe }) {
  if (!container) return;
  container.innerHTML = "";

  const header = document.createElement("div");
  header.className = "view-header-bar";
  header.innerHTML = `
    <div>
      <h2 class="page-title">Controlled Learning & Systemic Weaknesses</h2>
      <p class="page-subtitle">Observational feedback experiences, systemic weaknesses, evaluated improvement proposals, and safety boundaries.</p>
    </div>
  `;
  container.appendChild(header);

  // Subtabs Navigation
  const subnav = document.createElement("div");
  subnav.className = "learning-subnav";
  subnav.innerHTML = `
    <button class="subnav-btn active" data-subtab="experiences">Experiences</button>
    <button class="subnav-btn" data-subtab="weaknesses">Systemic Weaknesses</button>
    <button class="subnav-btn" data-subtab="proposals">Improvement Proposals</button>
    <button class="subnav-btn" data-subtab="wipe">Safety & Data Wipe</button>
  `;
  container.appendChild(subnav);

  const subtabContent = document.createElement("div");
  subtabContent.id = "learning-subtab-content";
  subtabContent.className = "subtab-content-area";
  container.appendChild(subtabContent);

  function switchSubtab(subtab) {
    subnav.querySelectorAll(".subnav-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.subtab === subtab);
    });

    if (subtab === "experiences") renderExperiencesSubtab(subtabContent);
    else if (subtab === "weaknesses") renderWeaknessesSubtab(subtabContent);
    else if (subtab === "proposals") renderProposalsSubtab(subtabContent);
    else if (subtab === "wipe") renderWipeSubtab(subtabContent);
  }

  subnav.querySelectorAll(".subnav-btn").forEach(b => {
    b.onclick = () => switchSubtab(b.dataset.subtab);
  });

  // 1. Experiences Subtab
  async function renderExperiencesSubtab(el) {
    el.innerHTML = `<div style="color: var(--text-tertiary);">Loading experience records...</div>`;
    try {
      const res = await fetch("/api/learning/experiences");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const exps = await res.json();

      el.innerHTML = `
        <div class="subtab-toolbar">
          <span class="subtab-count-label">${exps.length} Sanitized Interaction Experiences</span>
        </div>
        <div class="learning-list" id="experiences-list"></div>
      `;

      const listEl = el.querySelector("#experiences-list");
      if (exps.length === 0) {
        listEl.innerHTML = `<div class="empty-state-card"><div style="color: var(--text-tertiary);">No interaction experiences recorded yet. Upvote/downvote replies or edit answers in chat to log experiences.</div></div>`;
        return;
      }

      exps.forEach(exp => {
        const item = document.createElement("div");
        item.className = "experience-card";
        item.innerHTML = `
          <div class="experience-header">
            <div class="experience-badges">
              <span class="badge ${exp.feedback_type === 'accepted_edit' ? 'badge-verified' : 'badge-corrected'}">${exp.feedback_type}</span>
              ${exp.error_category ? `<span class="badge badge-error-cat">${exp.error_category}</span>` : ''}
              <span class="mono-meta">${new Date((exp.created_at || 0) * 1000).toLocaleString()}</span>
            </div>
            <button class="btn-del-exp action-btn-subtle" title="Delete Experience (unlinks from weaknesses)">🗑️ Delete</button>
          </div>
          <div class="experience-body">
            <div class="experience-row">
              <span class="exp-label">Prompt:</span>
              <span class="exp-val">${exp.sanitized_prompt || 'N/A'}</span>
            </div>
            <div class="experience-row">
              <span class="exp-label">Original Response:</span>
              <span class="exp-val">${exp.sanitized_response || 'N/A'}</span>
            </div>
            ${exp.correction_text ? `
              <div class="experience-row">
                <span class="exp-label">Owner Correction:</span>
                <span class="exp-val color-completed">${exp.correction_text}</span>
              </div>
            ` : ''}
          </div>
        `;

        item.querySelector(".btn-del-exp").onclick = async () => {
          if (confirm("Delete this experience record? It will be safely unlinked from all systemic weaknesses.")) {
            try {
              const delRes = await fetch(`/api/learning/experiences/${exp.experience_id}`, { method: "DELETE" });
              if (delRes.ok) {
                renderExperiencesSubtab(el);
              } else {
                const err = await delRes.json();
                alert(`Failed to delete: ${err.detail || "Error"}`);
              }
            } catch (e) {
              alert(`Error: ${e.message}`);
            }
          }
        };

        listEl.appendChild(item);
      });
    } catch (e) {
      el.innerHTML = `<div style="color: var(--color-error);">Error loading experiences: ${e.message}</div>`;
    }
  }

  // 2. Weaknesses Subtab
  async function renderWeaknessesSubtab(el) {
    el.innerHTML = `<div style="color: var(--text-tertiary);">Loading systemic weaknesses...</div>`;
    try {
      const res = await fetch("/api/learning/weaknesses");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const weaknesses = await res.json();

      el.innerHTML = `
        <div class="subtab-toolbar">
          <span class="subtab-count-label">${weaknesses.length} Cataloged Systemic Weaknesses</span>
        </div>
        <div class="learning-list" id="weaknesses-list"></div>
      `;

      const listEl = el.querySelector("#weaknesses-list");
      if (weaknesses.length === 0) {
        listEl.innerHTML = `<div class="empty-state-card"><div style="color: var(--text-tertiary);">No systemic weaknesses cataloged. Recurring patterns across negative feedback are aggregated here.</div></div>`;
        return;
      }

      weaknesses.forEach(w => {
        const item = document.createElement("div");
        item.className = "weakness-card";
        item.innerHTML = `
          <div class="weakness-header">
            <span class="weakness-title">${w.title || 'Untitled Weakness'}</span>
            <div class="weakness-badges">
              <span class="badge badge-priority-${(w.severity || 'medium').toLowerCase()}">${w.severity}</span>
              <span class="badge badge-status-${(w.status || 'identified').toLowerCase()}">${w.status}</span>
            </div>
          </div>
          <div class="weakness-desc">${w.pattern_description || 'No description available.'}</div>
          <div class="weakness-meta-row">
            <span>Occurrences: <strong>${w.occurrence_count || 1}</strong></span>
            <span>Linked Experiences: <strong>${(w.experience_ids || []).length}</strong></span>
          </div>
          <div class="weakness-controls">
            <div class="form-row-inline">
              <label>Update Status:</label>
              <select class="status-select toolbar-select">
                <option value="identified" ${w.status === 'identified' ? 'selected' : ''}>Identified</option>
                <option value="under_review" ${w.status === 'under_review' ? 'selected' : ''}>Under Review</option>
                <option value="proposed_fix" ${w.status === 'proposed_fix' ? 'selected' : ''}>Proposed Fix</option>
                <option value="resolved" ${w.status === 'resolved' ? 'selected' : ''}>Resolved</option>
                <option value="ignored" ${w.status === 'ignored' ? 'selected' : ''}>Ignored</option>
              </select>
              <input type="text" class="resolution-input toolbar-input" placeholder="Resolution note / commit reference..." value="${w.resolution_notes || ''}">
              <button class="btn-save-weakness action-btn-secondary">Save</button>
            </div>
          </div>
        `;

        item.querySelector(".btn-save-weakness").onclick = async () => {
          const newStatus = item.querySelector(".status-select").value;
          const note = item.querySelector(".resolution-input").value.trim();
          try {
            const patchRes = await fetch(`/api/learning/weaknesses/${w.weakness_id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ status: newStatus, resolution_note: note })
            });
            if (patchRes.ok) {
              renderWeaknessesSubtab(el);
            } else {
              const err = await patchRes.json();
              alert(`Update failed: ${err.detail || "Error"}`);
            }
          } catch (e) {
            alert(`Error: ${e.message}`);
          }
        };

        listEl.appendChild(item);
      });
    } catch (e) {
      el.innerHTML = `<div style="color: var(--color-error);">Error loading weaknesses: ${e.message}</div>`;
    }
  }

  // 3. Proposals Subtab
  async function renderProposalsSubtab(el) {
    el.innerHTML = `<div style="color: var(--text-tertiary);">Loading candidate proposals...</div>`;
    try {
      const res = await fetch("/api/learning/proposals");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const proposals = await res.json();

      el.innerHTML = `
        <div class="safety-banner-box">
          <span style="font-size: 20px;">🛡️</span>
          <div>
            <strong>Fixed Safety Boundary:</strong>
            Improvement proposals are evaluated against strict offline benchmarks. Owner approval records acceptance but does NOT autonomously rewrite code or deploy models.
          </div>
        </div>
        <div class="subtab-toolbar" style="margin-top: 14px;">
          <span class="subtab-count-label">${proposals.length} Evaluated Improvement Proposals</span>
        </div>
        <div class="learning-list" id="proposals-list"></div>
      `;

      const listEl = el.querySelector("#proposals-list");
      if (proposals.length === 0) {
        listEl.innerHTML = `<div class="empty-state-card"><div style="color: var(--text-tertiary);">No improvement proposals generated yet. Distillation cycles create candidate proposals from curated feedback.</div></div>`;
        return;
      }

      proposals.forEach(prop => {
        const item = document.createElement("div");
        item.className = "proposal-card";
        item.innerHTML = `
          <div class="proposal-header">
            <span class="proposal-title">${prop.title || 'Untitled Proposal'}</span>
            <div class="proposal-badges">
              <span class="badge badge-category">${prop.change_category}</span>
              <span class="badge badge-eval-${(prop.evaluation_status || 'pending').toLowerCase()}">Eval: ${prop.evaluation_status}</span>
              <span class="badge badge-approval-${(prop.owner_approval_status || 'pending').toLowerCase()}">Approval: ${prop.owner_approval_status}</span>
            </div>
          </div>
          <div class="proposal-desc">${prop.description || ''}</div>
          ${prop.proposed_changes ? `
            <div class="proposal-changes">
              <span class="meta-label">Proposed Changes / Invariants:</span>
              <pre class="approval-code-block">${JSON.stringify(prop.proposed_changes, null, 2)}</pre>
            </div>
          ` : ''}
          ${prop.evaluation_results ? `
            <div class="proposal-eval-results">
              <span class="meta-label">Benchmark Results:</span>
              <pre class="approval-code-block">${JSON.stringify(prop.evaluation_results, null, 2)}</pre>
            </div>
          ` : ''}
          <div class="proposal-actions">
            <button class="btn-eval-prop action-btn-secondary">Run Benchmark Evaluation</button>
            ${prop.owner_approval_status !== 'approved' ? `
              <button class="btn-approve-prop action-btn-primary">Approve Proposal</button>
            ` : '<span class="color-completed" style="font-size: 13px; font-weight: 500;">✓ Approved by Owner</span>'}
            ${prop.owner_approval_status !== 'rejected' ? `
              <button class="btn-reject-prop action-btn-danger">Reject</button>
            ` : '<span style="color: var(--color-error); font-size: 13px;">✕ Rejected</span>'}
          </div>
        </div>
        `;

        item.querySelector(".btn-eval-prop").onclick = async () => {
          try {
            const evalRes = await fetch(`/api/learning/proposals/${prop.proposal_id}/evaluate`, { method: "POST" });
            if (evalRes.ok) {
              alert("Benchmark evaluation completed!");
              renderProposalsSubtab(el);
            } else {
              const err = await evalRes.json();
              alert(`Evaluation failed: ${err.detail || "Error"}`);
            }
          } catch (e) {
            alert(`Error: ${e.message}`);
          }
        };

        const apprBtn = item.querySelector(".btn-approve-prop");
        if (apprBtn) {
          apprBtn.onclick = async () => {
            const comment = prompt("Optional owner approval comment:");
            try {
              const decRes = await fetch(`/api/learning/proposals/${prop.proposal_id}/decision`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ approved: true, owner_comment: comment })
              });
              if (decRes.ok) {
                renderProposalsSubtab(el);
              } else {
                const err = await decRes.json();
                alert(`Approval failed: ${err.detail || "Error"}`);
              }
            } catch (e) {
              alert(`Error: ${e.message}`);
            }
          };
        }

        const rejBtn = item.querySelector(".btn-reject-prop");
        if (rejBtn) {
          rejBtn.onclick = async () => {
            const comment = prompt("Reason for rejection:");
            try {
              const decRes = await fetch(`/api/learning/proposals/${prop.proposal_id}/decision`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ approved: false, owner_comment: comment })
              });
              if (decRes.ok) {
                renderProposalsSubtab(el);
              } else {
                const err = await decRes.json();
                alert(`Rejection failed: ${err.detail || "Error"}`);
              }
            } catch (e) {
              alert(`Error: ${e.message}`);
            }
          };
        }

        listEl.appendChild(item);
      });
    } catch (e) {
      el.innerHTML = `<div style="color: var(--color-error);">Error loading proposals: ${e.message}</div>`;
    }
  }

  // 4. Wipe Subtab (Danger Zone)
  function renderWipeSubtab(el) {
    el.innerHTML = `
      <div class="danger-zone-container">
        <div class="danger-header">
          <span style="font-size: 22px;">⚠️</span>
          <div>
            <h3 style="color: var(--color-error); margin: 0;">Full Learning Data Wipe & Reset</h3>
            <p style="color: var(--text-secondary); margin: 4px 0 0 0; font-size: 13.5px;">
              Permanently purges observational experiences, systemic weaknesses, and candidate improvement proposals.
            </p>
          </div>
        </div>

        <div class="wipe-disclosure-grid">
          <div class="disclosure-box box-wiped">
            <span class="disclosure-title color-error">✕ WHAT WILL BE PERMANENTLY WIPED</span>
            <ul>
              <li>All interaction experience records</li>
              <li>Cataloged systemic weakness entries</li>
              <li>Candidate improvement proposals & benchmarks</li>
              <li>Curated candidate datasets in training memory</li>
            </ul>
          </div>
          <div class="disclosure-box box-preserved">
            <span class="disclosure-title color-completed">✓ WHAT IS STRICTLY PRESERVED</span>
            <ul>
              <li>Core conversation history & transcripts</li>
              <li>Database structural integrity & WAL mode</li>
              <li>HINAKU persona prompt (<code>hinaku_persona.md</code>)</li>
              <li>System audit logs & security configurations</li>
            </ul>
          </div>
        </div>

        <div class="wipe-controls-form">
          <label class="checkbox-container">
            <input type="checkbox" id="check-confirm-wipe">
            <span class="checkbox-label"><strong>Confirmation 1:</strong> I explicitly confirm the complete wipe of all learning experiences and weaknesses.</span>
          </label>
          <label class="checkbox-container">
            <input type="checkbox" id="check-ack-loss">
            <span class="checkbox-label"><strong>Confirmation 2:</strong> I acknowledge permanent data loss and understand this operation cannot be undone.</span>
          </label>

          <div class="form-group" style="margin-top: 14px;">
            <label>Type <code>WIPE_LEARNING_DATA</code> to unlock:</label>
            <input type="text" id="input-wipe-code" class="form-input" placeholder="Type WIPE_LEARNING_DATA exactly">
          </div>

          <div class="danger-button-row" style="margin-top: 20px;">
            <button id="btn-execute-learning-wipe" class="action-btn-danger" disabled>Permanently Wipe Learning Data</button>
          </div>

          <div id="wipe-status-output" class="status-msg hidden"></div>
        </div>
      </div>
    `;

    const c1 = el.querySelector("#check-confirm-wipe");
    const c2 = el.querySelector("#check-ack-loss");
    const inp = el.querySelector("#input-wipe-code");
    const btn = el.querySelector("#btn-execute-learning-wipe");
    const statusOut = el.querySelector("#wipe-status-output");

    function validateUnlock() {
      const isMatch = inp.value.trim() === "WIPE_LEARNING_DATA";
      btn.disabled = !(c1.checked && c2.checked && isMatch);
    }

    c1.onchange = validateUnlock;
    c2.onchange = validateUnlock;
    inp.oninput = validateUnlock;

    btn.onclick = async () => {
      btn.disabled = true;
      btn.textContent = "Wiping...";
      statusOut.classList.add("hidden");

      try {
        const res = await fetch("/api/learning/wipe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirm_wipe: true,
            acknowledge_data_loss: true,
            scope: "all_experiences_and_weaknesses"
          })
        });

        if (res.ok) {
          const result = await res.json();
          statusOut.className = "status-msg status-msg-success";
          statusOut.innerHTML = `
            <strong>✓ Learning Data Successfully Wiped!</strong><br>
            • Experiences deleted: ${result.deleted_experiences}<br>
            • Weaknesses deleted: ${result.deleted_weaknesses}<br>
            • Proposals deleted: ${result.deleted_proposals}<br>
            <em>Core conversation history and audit logs remain intact.</em>
          `;
          statusOut.classList.remove("hidden");
          c1.checked = false;
          c2.checked = false;
          inp.value = "";
          btn.textContent = "Permanently Wipe Learning Data";
        } else {
          const err = await res.json();
          statusOut.className = "status-msg status-msg-error";
          statusOut.textContent = `Wipe failed: ${err.detail || "Authorization error"}`;
          statusOut.classList.remove("hidden");
          btn.disabled = false;
          btn.textContent = "Permanently Wipe Learning Data";
        }
      } catch (e) {
        statusOut.className = "status-msg status-msg-error";
        statusOut.textContent = `Error: ${e.message}`;
        statusOut.classList.remove("hidden");
        btn.disabled = false;
        btn.textContent = "Permanently Wipe Learning Data";
      }
    };
  }

  // Default to experiences subtab
  switchSubtab("experiences");
}


