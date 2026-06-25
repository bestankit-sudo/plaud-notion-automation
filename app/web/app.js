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
  parts.push('<div id="speaker-key"></div>');
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
  renderSpeakerKey(rid);
}

async function renderSpeakerKey(rid) {
  const host = document.getElementById("speaker-key");
  if (!host) return;
  let data, lib;
  try {
    const r = await fetch(`/api/meetings/${encodeURIComponent(rid)}/speakers`);
    if (!r.ok) return; // naming disabled (404) or error
    data = await r.json();
    lib = await (await fetch("/api/speakers")).json();
  } catch (e) {
    return;
  }
  if (!data.speakers || !data.speakers.length) return;
  const known = (lib.speakers || []).map((s) => s.name);

  const card = document.createElement("div");
  card.className = "speaker-key";
  const h = document.createElement("h3");
  h.textContent = "Speaker Key";
  const note = document.createElement("small");
  note.className = "hint";
  note.textContent = `Name a voice to enroll it — future meetings auto-label it (match ≥ ${data.threshold}).`;
  const dl = document.createElement("datalist");
  dl.id = "known-speakers";
  for (const n of known) {
    const o = document.createElement("option");
    o.value = n;
    dl.appendChild(o);
  }
  card.append(h, note, dl);
  for (const sp of data.speakers) card.appendChild(speakerRow(rid, sp));
  host.replaceChildren(card);
}

function speakerRow(rid, sp) {
  const row = document.createElement("div");
  row.className = "spk-row";

  const head = document.createElement("div");
  head.className = "spk-head";
  const disp = document.createElement("span");
  disp.className = "spk-display";
  disp.textContent = sp.display;
  const badge = document.createElement("span");
  badge.className = "spk-badge " + (sp.enrolled ? "known" : "guest");
  badge.textContent = sp.enrolled ? "enrolled ✓" : "Guest";
  const dur = document.createElement("span");
  dur.className = "spk-dur";
  dur.textContent = `${sp.total_speech_sec}s`;
  head.append(disp, badge, dur);
  if (!sp.enrolled && typeof sp.score === "number") {
    const hint = document.createElement("small");
    hint.className = "hint";
    hint.textContent = `nearest ${sp.score.toFixed(2)} — needs ≥ 0.75 to auto-label`;
    head.appendChild(hint);
  }

  const actions = document.createElement("div");
  actions.className = "spk-actions";
  const audio = document.createElement("audio");
  audio.controls = true;
  audio.preload = "none";
  audio.hidden = true;
  const hear = document.createElement("button");
  hear.type = "button";
  hear.className = "spk-btn";
  hear.textContent = "▶ hear";
  hear.addEventListener("click", () => {
    if (!audio.src) {
      audio.src = `/api/audio/${encodeURIComponent(rid)}/snippet?label=${encodeURIComponent(sp.label)}`;
    }
    audio.hidden = false;
    audio.play().catch(() => {});
  });
  const input = document.createElement("input");
  input.type = "text";
  input.className = "spk-input";
  input.placeholder = "name this voice";
  input.setAttribute("list", "known-speakers");
  if (sp.enrolled) input.value = sp.display;
  const save = document.createElement("button");
  save.type = "button";
  save.className = "spk-btn primary";
  save.textContent = "Save";
  const status = document.createElement("span");
  status.className = "spk-status";
  save.addEventListener("click", async () => {
    const name = input.value.trim();
    if (!name) {
      status.textContent = "enter a name";
      return;
    }
    save.disabled = true;
    status.textContent = "saving…";
    try {
      const r = await fetch(
        `/api/meetings/${encodeURIComponent(rid)}/speakers/${encodeURIComponent(sp.label)}/name`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) }
      );
      if (!r.ok) throw new Error("save failed");
      status.textContent = "saved ✓";
      setTimeout(() => loadDetail(rid, document.querySelector(".row.active")), 350);
    } catch (e) {
      status.textContent = "failed";
      save.disabled = false;
    }
  });
  actions.append(hear, audio, input, save, status);

  row.append(head, actions);
  return row;
}

function li(text) {
  const d = document.createElement("li");
  d.textContent = text;
  return d.outerHTML;
}

loadList();
