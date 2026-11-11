/* Guided real execution. All progress comes from the existing session snapshot. */
const LIVE_DEMO = document.body.dataset.liveDemo === "true";
const PUBLIC_DEMO_SESSIONS = new Set((document.body.dataset.publicSessions || "").split(" ").filter(Boolean));
let liveDemoCatalog = null;

function connectLiveDemoPolling() {
  // Short requests also work through hosts which buffer streaming responses.
  const sid = state.currentSessionId;
  const controller = new AbortController();
  let timer;
  const connection = {close() { clearTimeout(timer); controller.abort(); }};
  state.eventSource = connection;
  const poll = async () => {
    if (state.eventSource !== connection) return;
    try {
      if (!document.hidden || !state.snapshot) {
        const snapshot = await requestJson(`/api/sessions/${encodeURIComponent(sid)}`, {signal: controller.signal});
        if (state.eventSource !== connection) return;
        state.activityConnection = "connected";
        applySnapshot(snapshot);
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      state.activityConnection = "reconnecting";
      renderActivity(state.snapshot);
    }
    if (state.eventSource === connection) timer = setTimeout(poll, state.snapshot?.active_job ? 2000 : 5000);
  };
  poll();
}

let liveDemoSelection = null;

async function initLiveDemo() {
  if (!LIVE_DEMO) return;
  liveDemoCatalog = await requestJson("/static/bmi-demo.json");
  const panel = document.getElementById("live-demo-guide");
  panel.hidden = false;
  const suggestions = document.createElement("details");
  suggestions.id = "live-demo-suggestions";
  suggestions.open = !window.location.hash.startsWith("#session_");
  const summary = document.createElement("summary");
  summary.textContent = "Example questions · click to edit";
  const steps = document.createElement("div");
  steps.className = "live-demo-steps";
  for (const step of liveDemoCatalog.steps) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.demoStep = step.id;
    button.textContent = step.prompt;
    button.title = step.description;
    button.addEventListener("click", () => {
      liveDemoSelection = step.setup ? step : null;
      els.replyInput.value = step.prompt;
      els.replyInput.dispatchEvent(new Event("input", {bubbles: true}));
      suggestions.open = false;
      updateLiveDemo();
      els.replyInput.focus();
    });
    steps.appendChild(button);
  }
  suggestions.append(summary, steps);
  const recording = document.createElement("a");
  recording.href = "https://result4.mrcat.science/#example-result4";
  recording.target = "_blank";
  recording.rel = "noopener";
  recording.textContent = "View a completed Result 4 session ↗";
  suggestions.appendChild(recording);
  const attachment = document.createElement("div");
  attachment.id = "live-demo-attachment";
  attachment.hidden = true;
  const label = document.createElement("span");
  label.id = "live-demo-attachment-label";
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Remove";
  remove.addEventListener("click", clearLiveDemoSetup);
  attachment.append(label, remove);
  panel.append(suggestions, attachment);
  updateLiveDemo();
}

function clearLiveDemoSetup() {
  liveDemoSelection = null;
  updateLiveDemo();
}

function updateLiveDemo() {
  if (!LIVE_DEMO || !liveDemoCatalog) return;
  document.getElementById("live-demo-guide").hidden = PUBLIC_DEMO_SESSIONS.has(state.currentSessionId);
  const locked = state.busy || Boolean(state.snapshot?.active_job) || isReadOnlySession();
  document.querySelectorAll("[data-demo-step]").forEach(button => { button.disabled = locked; });
  const attachment = document.getElementById("live-demo-attachment");
  attachment.hidden = !liveDemoSelection;
  document.getElementById("live-demo-attachment-label").textContent = liveDemoSelection
    ? `Example data to send: BMI → T2D · ${liveDemoSelection.label}` : "";
  attachment.querySelector("button").disabled = locked;
  document.querySelectorAll("#study-setup-content input, #study-setup-content select, #study-setup-content textarea, #study-setup-content button").forEach(element => { element.disabled = true; });
}

async function sendLiveDemoSetup(reply) {
  const selected = liveDemoSelection.setup;
  const form = new FormData();
  form.append("exposure_manifest", JSON.stringify(selected.exposures));
  form.append("outcome_manifest", JSON.stringify(selected.outcomes));
  form.append("analysis_request", reply);
  form.append("methods", JSON.stringify(selected.methods));
  form.append("sources", JSON.stringify(selected.sources));
  const endpoint = state.currentSessionId
    ? `/api/sessions/${encodeURIComponent(state.currentSessionId)}/study-setup` : "/api/manual-sessions";
  state.pendingUserMessage = {text: reply, sessionId: state.currentSessionId};
  els.replyInput.value = "";
  renderConversation(state.snapshot);
  setBusy(true);
  try {
    const response = await requestJson(endpoint, {method: "POST", body: form});
    clearLiveDemoSetup();
    await refreshSessions();
    await selectSession(response.session.session_id);
  } catch (error) {
    state.pendingUserMessage = null;
    els.replyInput.value = reply;
    renderConversation(state.snapshot);
    alert(`Send failed: ${error.message}`);
  } finally {
    setBusy(false);
  }
}
