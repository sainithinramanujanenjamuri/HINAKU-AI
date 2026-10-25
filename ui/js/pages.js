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

