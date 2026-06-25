// Phase 0 of the wizard: drive the installer (app/install backend via /api/install).
// All dynamic text is set via textContent; help links come from the step registry.
const stepsEl = document.getElementById("install-steps");

const GUIDE_HINTS = {
  brew: "Install Homebrew (the macOS package manager), then click Re-check.",
  docker: "Install and start Docker Desktop (it runs the Riffado container), then Re-check.",
  plaud_otp: "Log into Riffado in your browser, connect your Plaud account, then paste its API key in the Configure section below.",
};

async function loadStatus() {
  let steps;
  try {
    ({ steps } = await (await fetch("/api/install/status")).json());
  } catch (e) {
    stepsEl.textContent = "Could not reach the install API. Is ./run still running?";
    return;
  }
  stepsEl.replaceChildren();
  (steps || []).forEach((s, i) => stepsEl.appendChild(renderStep(s, i)));
}

function badge(done) {
  const b = document.createElement("span");
  b.className = "step-badge " + (done ? "done" : "pending");
  b.textContent = done ? "✓ done" : "● pending";
  return b;
}

function renderStep(s, i) {
  const row = document.createElement("div");
  row.className = "install-step";

  const head = document.createElement("div");
  head.className = "step-head";
  const num = document.createElement("span");
  num.className = "step-num";
  num.textContent = String(i + 1);
  const title = document.createElement("span");
  title.className = "step-title";
  title.textContent = s.title;
  const detail = document.createElement("span");
  detail.className = "step-detail";
  detail.textContent = s.detail || "";
  const badgeEl = badge(s.done);
  head.append(num, title, badgeEl, detail);

  const actions = document.createElement("div");
  actions.className = "step-actions";

  const log = document.createElement("pre");
  log.className = "step-log";
  log.hidden = true;

  if (s.kind === "guide") {
    if (s.guide_url) {
      const a = document.createElement("a");
      a.className = "help-link";
      a.href = s.guide_url;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "Open guide ↗";
      actions.appendChild(a);
    }
    const hint = document.createElement("small");
    hint.className = "hint";
    hint.textContent = GUIDE_HINTS[s.id] || "";
    actions.appendChild(hint);
    actions.appendChild(button("Re-check", "step-btn", loadStatus));
  } else if (s.id === "riffado") {
    actions.appendChild(button("Generate secrets", "step-btn", () => genSecrets(detail)));
    actions.appendChild(runButton(s, log, detail, badgeEl));
  } else if (s.id === "launchd") {
    const label = s.done ? "Reload background services" : "Start background services";
    actions.appendChild(button(label, "step-btn primary", (e) => loadAgents(detail, log, badgeEl, e.currentTarget)));
  } else {
    actions.appendChild(runButton(s, log, detail, badgeEl));
  }

  row.append(head, actions, log);
  return row;
}

function button(text, cls, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = cls;
  b.textContent = text;
  b.addEventListener("click", onClick);
  return b;
}

function runButton(s, log, detail, badgeEl) {
  return button(s.done ? "Re-run" : "Install", "step-btn", (e) =>
    streamStep(s.id, e.currentTarget, log, detail, badgeEl)
  );
}

function markDone(badgeEl) {
  badgeEl.className = "step-badge done";
  badgeEl.textContent = "✓ done";
}

function streamStep(id, btn, log, detail, badgeEl) {
  btn.disabled = true;
  log.hidden = false;
  log.textContent = "";
  detail.textContent = "running…";
  detail.className = "step-detail";

  const src = new EventSource(`/api/install/stream/${id}`);
  let finished = false;
  const finish = (ok, msg) => {
    if (finished) return;
    finished = true;
    src.close();
    btn.disabled = false;
    detail.textContent = msg;
    detail.className = "step-detail " + (ok ? "ok" : "bad");
    if (ok) markDone(badgeEl);
  };

  src.addEventListener("log", (e) => {
    const d = JSON.parse(e.data);
    log.textContent += (d.line ?? "") + "\n";
    log.scrollTop = log.scrollHeight;
  });
  src.addEventListener("skip", () => {
    log.textContent += "(already installed — skipped)\n";
  });
  src.addEventListener("done", (e) => {
    const d = JSON.parse(e.data);
    finish(true, d.skipped ? "already done" : "installed ✓");
  });
  // Named "error" frames carry .data; EventSource also fires a dataless "error"
  // on connection close — ignore that one once we've finished.
  src.addEventListener("error", (e) => {
    if (e.data) {
      const d = JSON.parse(e.data);
      finish(false, d.detail || `failed (exit ${d.code})`);
    } else if (!finished) {
      finish(false, "connection lost");
    }
  });
}

async function genSecrets(detail) {
  detail.textContent = "generating…";
  detail.className = "step-detail";
  try {
    const body = await (await fetch("/api/install/riffado/secrets", { method: "POST" })).json();
    detail.textContent = body.written && body.written.length
      ? `secrets written (${body.written.join(", ")})`
      : "secrets already present";
    detail.className = "step-detail ok";
  } catch (e) {
    detail.textContent = "failed to write secrets";
    detail.className = "step-detail bad";
  }
}

async function loadAgents(detail, log, badgeEl, btn) {
  if (btn) btn.disabled = true;
  detail.textContent = "loading…";
  detail.className = "step-detail";
  log.hidden = false;
  log.textContent = "";
  try {
    const body = await (await fetch("/api/install/launchd/load", { method: "POST" })).json();
    for (const a of body.agents) {
      log.textContent += `${a.label}: ${a.rc === 0 ? "loaded ✓" : "exit " + a.rc}\n`;
    }
    if (body.ok) {
      log.textContent += "Dashboard is now always-on at http://127.0.0.1:8787 — bookmark it.\n";
      detail.textContent = "background services running ✓";
      detail.className = "step-detail ok";
      markDone(badgeEl);
    } else {
      detail.textContent = "some agents failed to load";
      detail.className = "step-detail bad";
    }
  } catch (e) {
    detail.textContent = "failed to load agents";
    detail.className = "step-detail bad";
  } finally {
    if (btn) btn.disabled = false;
  }
}

loadStatus();
