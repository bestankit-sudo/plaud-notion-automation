// Phase 0 of the wizard: drive the installer (app/install backend via /api/install).
// All dynamic text is set via textContent; help links come from the step registry.
const stepsEl = document.getElementById("install-steps");

// Per-step "why it's needed" + "how" copy, shown on the right of each step.
const STEP_INFO = {
  brew: {
    why: "The macOS package manager. ffmpeg and Python 3.12 install through it, so the app gets the exact versions it needs instead of you hunting for installers — it's the foundation everything else sits on.",
    how: ["Open the guide and paste its one-line install command into Terminal.", "Come back and click Re-check."],
  },
  ffmpeg: {
    why: "Reads and clips the Plaud audio. Transcription can't run without it, and it cuts the short per-speaker clips you play in the Speaker Key.",
    how: ["Click Install — fetched automatically via Homebrew."],
  },
  py312: {
    why: "The exact Python the worker and the on-device ML stack are built against. It must be 3.12 — newer 3.13 / 3.14 aren't supported by the ML libraries yet.",
    how: ["Click Install — added automatically via Homebrew."],
  },
  ml: {
    why: "What makes transcription and speaker recognition run on YOUR Mac: MLX Whisper (transcribes on the Apple GPU), pyannote (separates who-spoke-when), and the voiceprint embeddings. Because it's local, your audio and voiceprints never leave the machine — the whole point of the app.",
    how: ["Click Install. It builds a dedicated environment and downloads a few GB of models on the first run (one-time)."],
  },
  docker: {
    why: "Runs the self-hosted Riffado container — the piece that pulls your recordings off Plaud's cloud onto your Mac.",
    how: ["Install Docker Desktop from the guide and start it.", "Click Re-check."],
  },
  riffado: {
    why: "The local service that syncs recordings from your Plaud device so the worker can process them. Runs in Docker on 127.0.0.1.",
    how: ["Click Generate secrets (creates its DB password + keys).", "Click Install to start the container."],
  },
  plaud_otp: {
    why: "Links your Plaud account so Riffado can fetch your recordings. You paste Riffado's API key so the worker can talk to it.",
    how: ["Open Riffado, log in, and connect your Plaud account.", "Copy its API key (op_…) into the Configure section below."],
  },
  launchd: {
    why: "Two background agents that keep things running without you: one checks Riffado every 30 minutes and auto-processes new recordings; the other keeps this dashboard always-on, so the URL works even when you haven't started it by hand.",
    how: ["Click Start background services — it registers both agents with macOS (launchd)."],
  },
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

function stepInfoPanel(s) {
  const info = STEP_INFO[s.id] || { why: "", how: [] };
  const panel = document.createElement("div");
  panel.className = "step-info";

  const whyLabel = document.createElement("div");
  whyLabel.className = "info-label";
  whyLabel.textContent = "Why it's needed";
  const why = document.createElement("p");
  why.className = "info-why";
  why.textContent = info.why;
  panel.append(whyLabel, why);

  if (info.how && info.how.length) {
    const howLabel = document.createElement("div");
    howLabel.className = "info-label";
    howLabel.textContent = "How";
    const ol = document.createElement("ol");
    ol.className = "info-how";
    for (const stepText of info.how) {
      const li = document.createElement("li");
      li.textContent = stepText;
      ol.appendChild(li);
    }
    panel.append(howLabel, ol);
  }
  if (s.guide_url) {
    const a = document.createElement("a");
    a.className = "help-link";
    a.href = s.guide_url;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = "Open guide ↗";
    panel.appendChild(a);
  }
  return panel;
}

function renderStep(s, i) {
  const row = document.createElement("div");
  row.className = "install-step";

  const main = document.createElement("div");
  main.className = "step-main";

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

  main.append(head, actions, log);
  row.append(main, stepInfoPanel(s));
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
