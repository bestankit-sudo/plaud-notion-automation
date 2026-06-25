async function loadList() {
  const res = await fetch("/api/meetings");
  const { destination, meetings } = await res.json();
  document.getElementById("destination").textContent = destination;
  const list = document.getElementById("list");
  list.innerHTML = "";
  if (!meetings.length) {
    list.innerHTML = '<p class="empty">No meetings yet.</p>';
    return;
  }
  for (const m of meetings) {
    const el = document.createElement("button");
    el.className = "row";
    const when = new Date(m.recorded_at).toLocaleString();
    el.innerHTML = `<span class="row-title"></span><span class="row-when"></span>`;
    el.querySelector(".row-title").textContent = m.title;
    el.querySelector(".row-when").textContent = when;
    el.onclick = () => loadDetail(m.recording_id, el);
    list.appendChild(el);
  }
}

async function loadDetail(rid, rowEl) {
  document.querySelectorAll(".row.active").forEach((r) => r.classList.remove("active"));
  if (rowEl) rowEl.classList.add("active");
  const res = await fetch(`/api/meetings/${encodeURIComponent(rid)}`);
  const detail = document.getElementById("detail");
  if (!res.ok) {
    detail.innerHTML = '<p class="empty">Could not load meeting.</p>';
    return;
  }
  const m = await res.json();
  const parts = [];
  parts.push(`<h2></h2>`);
  parts.push(`<p class="meta"></p>`);
  parts.push(`<audio controls src="/api/audio/${encodeURIComponent(rid)}"></audio>`);
  if (m.overview?.length) {
    parts.push("<h3>Overview</h3><ul>" + m.overview.map(li).join("") + "</ul>");
  }
  for (const s of m.sections || []) {
    parts.push(`<h3 class="sec"></h3><ul>` + (s.bullets || []).map(li).join("") + "</ul>");
  }
  if (m.action_items?.length) {
    parts.push("<h3>Action Items</h3><ul>");
    for (const a of m.action_items) {
      const owner = a.owner ? `<strong></strong>: ` : "";
      parts.push(`<li class="ai">${owner}<span class="task"></span></li>`);
    }
    parts.push("</ul>");
  }
  if (m.attendees?.length) {
    parts.push("<h3>Attendees</h3><ul>" + m.attendees.map((a) => li(a.name || "—")).join("") + "</ul>");
  }
  if (m.transcript?.length) {
    parts.push('<h3>Transcript</h3><div class="transcript"></div>');
  }
  detail.innerHTML = parts.join("");
  detail.querySelector("h2").textContent = m.title;
  const metaEl = detail.querySelector("p.meta");
  if (metaEl) metaEl.textContent = m.duration_label || "";
  // fill section headings + action item text safely (avoid HTML injection)
  const secHeads = detail.querySelectorAll("h3.sec");
  (m.sections || []).forEach((s, i) => { if (secHeads[i]) secHeads[i].textContent = s.heading; });
  detail.querySelectorAll("li.ai").forEach((liEl, i) => {
    const a = m.action_items[i];
    const strong = liEl.querySelector("strong");
    if (strong) strong.textContent = a.owner;
    liEl.querySelector(".task").textContent = a.task;
  });
  const tx = detail.querySelector(".transcript");
  if (tx) {
    for (const t of m.transcript) {
      const p = document.createElement("p");
      const b = document.createElement("strong");
      b.textContent = (t.speaker || "Speaker") + ": ";
      p.appendChild(b);
      p.appendChild(document.createTextNode(t.text));
      tx.appendChild(p);
    }
  }
}

function li(text) {
  const d = document.createElement("li");
  d.textContent = text;
  return d.outerHTML;
}

loadList();
