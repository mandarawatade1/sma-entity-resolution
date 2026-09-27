const API = "";
const CANONICAL_FIELDS = ["name", "email", "phone", "address", "city", "state", "zip", "company"];

// ---------- Tabs ----------
document.querySelectorAll("#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "resolve") loadStats();
    if (btn.dataset.tab === "review") loadClusters();
    if (btn.dataset.tab === "repository") loadRepository(0);
  });
});

// ---------- Upload & mapping ----------
let parsedColumns = [];

document.getElementById("btn-preview").addEventListener("click", async () => {
  const file = document.getElementById("ds-file").files[0];
  if (!file) return alert("Choose a file first");
  const text = await file.text();
  if (file.name.toLowerCase().endsWith(".json")) {
    const data = JSON.parse(text);
    parsedColumns = Object.keys(data[0] || {});
  } else {
    const firstLine = text.split(/\r?\n/)[0];
    parsedColumns = firstLine.split(",").map((c) => c.trim().replace(/^"|"$/g, ""));
  }
  renderMappingUI();
  document.getElementById("btn-upload").disabled = false;
});

function renderMappingUI() {
  const area = document.getElementById("mapping-area");
  area.innerHTML = "";
  CANONICAL_FIELDS.forEach((field) => {
    const wrap = document.createElement("div");
    wrap.className = "map-field";
    const guess = parsedColumns.find((c) => c.toLowerCase().includes(field)) || "";
    wrap.innerHTML = `
      <label>${field}</label>
      <select data-field="${field}">
        <option value="">-- not mapped --</option>
        ${parsedColumns.map((c) => `<option value="${c}" ${c === guess ? "selected" : ""}>${c}</option>`).join("")}
      </select>`;
    area.appendChild(wrap);
  });
}

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("ds-name").value;
  const file = document.getElementById("ds-file").files[0];
  const mapping = {};
  document.querySelectorAll("#mapping-area select").forEach((sel) => {
    if (sel.value) mapping[sel.dataset.field] = sel.value;
  });

  const fd = new FormData();
  fd.append("name", name);
  fd.append("mapping", JSON.stringify(mapping));
  fd.append("file", file);

  const statusEl = document.getElementById("upload-status");
  statusEl.textContent = "Uploading...";
  statusEl.className = "status-msg";
  try {
    const res = await fetch(`${API}/api/datasets`, { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");
    statusEl.textContent = `Ingested ${data.rows_ingested} rows into dataset #${data.dataset_id}.`;
    statusEl.className = "status-msg ok";
    document.getElementById("upload-form").reset();
    document.getElementById("mapping-area").innerHTML = "";
    document.getElementById("btn-upload").disabled = true;
    loadDatasets();
  } catch (err) {
    statusEl.textContent = err.message;
    statusEl.className = "status-msg err";
  }
});

async function loadDatasets() {
  const res = await fetch(`${API}/api/datasets`);
  const datasets = await res.json();
  const tbody = document.querySelector("#datasets-table tbody");
  tbody.innerHTML = datasets.map((d) => `
    <tr>
      <td>${d.id}</td>
      <td>${d.name}</td>
      <td>${d.row_count}</td>
      <td>${Object.keys(d.mapping).map((f) => `<span class="pill">${f}</span>`).join("")}</td>
      <td><button class="danger" onclick="deleteDataset(${d.id})">Delete</button></td>
    </tr>`).join("");
}

async function deleteDataset(id) {
  if (!confirm("Delete this dataset and its records?")) return;
  await fetch(`${API}/api/datasets/${id}`, { method: "DELETE" });
  loadDatasets();
}

// ---------- Resolution ----------
document.getElementById("threshold").addEventListener("input", (e) => {
  document.getElementById("threshold-val").textContent = e.target.value;
});

document.getElementById("btn-resolve").addEventListener("click", async () => {
  const threshold = document.getElementById("threshold").value;
  const statusEl = document.getElementById("resolve-status");
  statusEl.textContent = "Running resolution...";
  statusEl.className = "status-msg";
  try {
    const res = await fetch(`${API}/api/resolve?threshold=${threshold}`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Resolution failed");
    statusEl.textContent = `Found ${data.clusters_found} entity clusters — ${data.duplicate_groups_needing_review} need review, ${data.auto_added_unique_records} unique records auto-added.`;
    statusEl.className = "status-msg ok";
    loadStats();
  } catch (err) {
    statusEl.textContent = err.message;
    statusEl.className = "status-msg err";
  }
});

async function loadStats() {
  const res = await fetch(`${API}/api/stats`);
  const s = await res.json();
  document.getElementById("stats-grid").innerHTML = `
    <div class="stat-box"><div class="num">${s.datasets}</div><div class="lbl">Datasets</div></div>
    <div class="stat-box"><div class="num">${s.records}</div><div class="lbl">Total records</div></div>
    <div class="stat-box"><div class="num">${s.pending_clusters}</div><div class="lbl">Pending review</div></div>
    <div class="stat-box"><div class="num">${s.master_records}</div><div class="lbl">Master records</div></div>`;
}

// ---------- Review ----------
async function loadClusters() {
  const res = await fetch(`${API}/api/clusters?status=pending`);
  const clusters = await res.json();
  const list = document.getElementById("clusters-list");
  if (!clusters.length) {
    list.innerHTML = "<p>No duplicate groups pending review. Run resolution first.</p>";
    return;
  }
  list.innerHTML = clusters.map((c) => renderCluster(c)).join("");
}

function renderCluster(c) {
  const fieldOptions = (field) => {
    const values = [...new Set(c.members.map((m) => m.raw[Object.keys(m.raw).find(
      (k) => k.toLowerCase() === field
    ) || ""] || m.normalized[field] || "").filter(Boolean))];
    if (!values.length) return "";
    return `
      <div class="field-row">
        <div class="fname">${field}</div>
        <select data-field="${field}">
          ${values.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join("")}
        </select>
      </div>`;
  };

  return `
    <div class="cluster" data-cluster-id="${c.cluster_id}">
      <div class="cluster-header">
        <strong>Cluster #${c.cluster_id}</strong>
        <span class="score-badge">${c.max_score.toFixed(1)}% match</span>
      </div>
      <table>
        <thead><tr><th>Source</th>${CANONICAL_FIELDS.map((f) => `<th>${f}</th>`).join("")}</tr></thead>
        <tbody>
          ${c.members.map((m) => `
            <tr>
              <td>${m.dataset_name}</td>
              ${CANONICAL_FIELDS.map((f) => `<td>${escapeHtml(m.normalized[f] || "")}</td>`).join("")}
            </tr>`).join("")}
        </tbody>
      </table>
      <p style="color:var(--muted); font-size:0.85rem; margin-top:10px;">Choose the value to keep for each field in the merged record:</p>
      ${CANONICAL_FIELDS.map(fieldOptions).join("")}
      <div class="cluster-actions">
        <button onclick="decideCluster(${c.cluster_id}, 'confirm')">Confirm Merge</button>
        <button class="secondary" onclick="decideCluster(${c.cluster_id}, 'reject')">Keep Separate</button>
      </div>
    </div>`;
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function decideCluster(clusterId, action) {
  const clusterEl = document.querySelector(`.cluster[data-cluster-id="${clusterId}"]`);
  const merged_fields = {};
  if (action === "confirm") {
    clusterEl.querySelectorAll("select[data-field]").forEach((sel) => {
      merged_fields[sel.dataset.field] = sel.value;
    });
  }
  await fetch(`${API}/api/clusters/${clusterId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, merged_fields }),
  });
  loadClusters();
  loadStats();
}

// ---------- Repository ----------
async function loadRepository(offset) {
  const res = await fetch(`${API}/api/repository?limit=50&offset=${offset}`);
  const data = await res.json();
  const tbody = document.querySelector("#repo-table tbody");
  tbody.innerHTML = data.items.map((item) => `
    <tr>
      <td>${escapeHtml(item.merged.name || "")}</td>
      <td>${escapeHtml(item.merged.email || "")}</td>
      <td>${escapeHtml(item.merged.phone || "")}</td>
      <td>${escapeHtml(item.merged.address || "")}</td>
      <td>${escapeHtml(item.merged.city || "")}</td>
      <td>${escapeHtml(item.merged.state || "")}</td>
      <td>${escapeHtml(item.merged.company || "")}</td>
      <td>${item.source_record_ids.length}</td>
    </tr>`).join("");

  const pag = document.getElementById("repo-pagination");
  const hasMore = offset + 50 < data.total;
  const hasPrev = offset > 0;
  pag.innerHTML = `
    <button class="secondary" ${hasPrev ? "" : "disabled"} onclick="loadRepository(${offset - 50})">Prev</button>
    <span style="margin: 0 10px; color: var(--muted);">${offset + 1}-${Math.min(offset + 50, data.total)} of ${data.total}</span>
    <button class="secondary" ${hasMore ? "" : "disabled"} onclick="loadRepository(${offset + 50})">Next</button>`;
}

// ---------- Init ----------
loadDatasets();
