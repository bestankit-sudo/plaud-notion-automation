const form = document.getElementById("setup");
const notionFields = document.getElementById("notion-fields");
const modelsEl = document.getElementById("models");
let selectedModel = null;

form.destination.forEach((r) =>
  r.addEventListener("change", () => {
    notionFields.hidden = form.destination.value !== "notion";
  })
);

async function loadModels() {
  let models;
  try {
    ({ models } = await (await fetch("/api/setup/models")).json());
  } catch (e) {
    document.getElementById("error").textContent = "Could not load models. Reload to retry.";
    return;
  }
  modelsEl.innerHTML = "";
  for (const m of models) {
    const row = document.createElement("label");
    row.className = "model-row";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "model";
    radio.value = m.model;
    radio.dataset.provider = m.provider;
    if (m.default) {
      radio.checked = true;
      selectedModel = m;
    }
    radio.addEventListener("change", () => { selectedModel = m; });
    const name = document.createElement("span");
    name.className = "model-name";
    name.textContent = `${m.label} — ${m.tier}`;
    const cost = document.createElement("span");
    cost.className = "model-cost";
    cost.textContent = `~$${m.cost.per_100.toFixed(2)} / 100 mtgs`;
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
