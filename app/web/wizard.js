const form = document.getElementById("setup");
const notionFields = document.getElementById("notion-fields");
const modelsEl = document.getElementById("models");
let selectedModel = null;

form.destination.forEach((r) =>
  r.addEventListener("change", () => {
    notionFields.hidden = form.destination.value !== "notion";
  })
);

const PROVIDER_INFO = {
  anthropic: { label: "Claude (Anthropic)", keyUrl: "https://console.anthropic.com/settings/keys", keyHint: "Console → Settings → API Keys → Create Key." },
  openai: { label: "OpenAI", keyUrl: "https://platform.openai.com/api-keys", keyHint: "Create a new secret key." },
};

async function loadModels() {
  let models;
  try {
    ({ models } = await (await fetch("/api/setup/models")).json());
  } catch (e) {
    document.getElementById("error").textContent = "Could not load models. Reload to retry.";
    return;
  }
  models = [...models].sort((a, b) => a.provider.localeCompare(b.provider)); // group providers regardless of API order
  modelsEl.innerHTML = "";
  let lastProvider = null;
  for (const m of models) {
    if (m.provider !== lastProvider) {
      lastProvider = m.provider;
      const info = PROVIDER_INFO[m.provider] || { label: m.provider, keyUrl: "#", keyHint: "" };
      const head = document.createElement("div");
      head.className = "provider-section";
      const h = document.createElement("span");
      h.className = "provider-name";
      h.textContent = info.label;
      const a = document.createElement("a");
      a.className = "help-link";
      a.href = info.keyUrl;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "Get an API key ↗";
      const hint = document.createElement("small");
      hint.className = "hint";
      hint.textContent = info.keyHint;
      head.append(h, a, hint);
      modelsEl.appendChild(head);
    }
    const row = document.createElement("label");
    row.className = "model-row";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "model";
    radio.value = m.model;
    radio.dataset.provider = m.provider;
    if (m.default) { radio.checked = true; selectedModel = m; }
    radio.addEventListener("change", () => { selectedModel = m; });
    const name = document.createElement("span");
    name.className = "model-name";
    name.textContent = `${m.label} — ${m.tier}`;
    const cost = document.createElement("span");
    cost.className = "model-cost";
    const usd = (n) => (n >= 1 ? `$${Math.round(n)}` : `$${n.toFixed(2)}`);
    cost.textContent = `${usd(m.cost.per_100_low)}–${usd(m.cost.per_100_high)} / 100 meetings`;
    cost.title = "Estimated cost for 100 meetings' summaries (transcription is free). " +
      "Low = a short ~20-min English meeting; high = a long ~70-min or non-English one.";
    row.append(radio, name, cost);
    modelsEl.appendChild(row);
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = document.getElementById("error");
  err.textContent = "";
  if (!selectedModel) { err.textContent = "Pick a model."; return; }
  const destination = form.destination.value;

  const cfg = {
    destination,
    summarizer_provider: selectedModel.provider,
    summarizer_model: selectedModel.model,
    speaker_naming_enabled: form.speaker_naming_enabled.checked,
    notion_parent_page_id: destination === "notion" ? form.notion_parent_page_id.value : null,
  };

  const secrets = {};
  const providerKey = form.PROVIDER_KEY.value.trim();
  if (providerKey) {
    secrets[selectedModel.provider === "anthropic" ? "ANTHROPIC_API_KEY" : "OPENAI_API_KEY"] = providerKey;
  }
  for (const k of ["HF_TOKEN", "RIFFADO_BASE_URL", "RIFFADO_API_KEY"]) {
    if (form[k].value.trim()) secrets[k] = form[k].value.trim();
  }
  if (destination === "notion" && form.NOTION_TOKEN.value.trim()) {
    secrets["NOTION_TOKEN"] = form.NOTION_TOKEN.value.trim();
  }

  try {
    let res = await fetch("/api/setup/config", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cfg),
    });
    if (!res.ok) throw new Error("config save failed");
    if (Object.keys(secrets).length) {
      res = await fetch("/api/setup/secrets", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values: secrets }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "secrets save failed");
    }
    window.location.reload(); // configured → viewer
  } catch (e2) {
    err.textContent = String(e2.message || e2);
  }
});

loadModels();

function setStatus(which, ok, detail) {
  const el = document.querySelector(`.test-status[data-status="${which}"]`);
  if (!el) return;
  el.textContent = (ok ? "✓ " : "✗ ") + detail;
  el.className = "test-status " + (ok ? "ok" : "bad");
}

async function runTest(which) {
  let endpoint, payload;
  if (which === "provider") {
    if (!selectedModel) { setStatus("provider", false, "pick a model first"); return; }
    endpoint = selectedModel.provider; // "anthropic" | "openai"
    payload = { key: form.PROVIDER_KEY.value.trim() };
  } else if (which === "hf") {
    endpoint = "hf"; payload = { token: form.HF_TOKEN.value.trim() };
  } else if (which === "notion") {
    endpoint = "notion"; payload = { token: form.NOTION_TOKEN.value.trim() };
  } else if (which === "riffado") {
    endpoint = "riffado";
    payload = { base_url: form.RIFFADO_BASE_URL.value.trim(), api_key: form.RIFFADO_API_KEY.value.trim() };
  }
  setStatus(which, false, "testing…");
  try {
    const res = await fetch(`/api/setup/test/${endpoint}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    const body = await res.json();
    setStatus(which, !!body.ok, body.detail || (body.ok ? "ok" : "failed"));
  } catch (e) {
    setStatus(which, false, "request failed");
  }
}

document.querySelectorAll(".test-btn").forEach((b) =>
  b.addEventListener("click", () => runTest(b.dataset.test))
);

// Step 1 / Step 2 tabs (ARIA tablist: arrow-key nav, one panel visible at a time).
function setupTabs() {
  const tabs = Array.from(document.querySelectorAll(".tab"));
  if (!tabs.length) return;
  function select(tab) {
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      const panel = document.getElementById(t.getAttribute("aria-controls"));
      if (panel) panel.hidden = !on;
    }
  }
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => select(tab));
    tab.addEventListener("keydown", (e) => {
      let j = null;
      if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
      else if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") j = 0;
      else if (e.key === "End") j = tabs.length - 1;
      if (j !== null) { e.preventDefault(); tabs[j].focus(); select(tabs[j]); }
    });
  });
  const next = document.getElementById("to-configure");
  if (next) next.addEventListener("click", () => {
    const t = document.getElementById("tab-configure");
    select(t); t.focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}
setupTabs();
