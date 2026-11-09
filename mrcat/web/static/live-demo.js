/* Guided real execution. All progress comes from the existing session snapshot. */
const LIVE_DEMO = document.body.dataset.liveDemo === "true";
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

async function initLiveDemo() {
  if (!LIVE_DEMO) return;
  liveDemoCatalog = await requestJson("/static/bmi-demo.json");
  const panel = document.getElementById("live-demo-guide");
  panel.hidden = false;
  const intro = document.createElement("p");
  intro.textContent = "Run the BMI → T2D example in one session. Start with literature and online GWAS, try the supplied local files, then follow up with MR-APSS. Each step runs on the server and can take several minutes. No API key needed.";
  const steps = document.createElement("div");
  steps.className = "live-demo-steps";
  for (const step of liveDemoCatalog.steps) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.demoStep = step.id;
    button.textContent = step.label;
    button.title = step.description;
    button.addEventListener("click", () => previewDemoPrompt(step.prompt));
    steps.appendChild(button);
  }
  const preview = document.createElement("details");
  preview.id = "live-demo-preview";
  const summary = document.createElement("summary");
  summary.textContent = "Request to send";
  const prompt = document.createElement("p");
  prompt.id = "live-demo-prompt";
  const send = document.createElement("button");
  send.type = "button";
  send.id = "live-demo-send";
  send.className = "primary-button";
  send.textContent = "Send request";
  send.addEventListener("click", () => sendReply({preventDefault() {}}, prompt.textContent));
  preview.append(summary, prompt, send);
  const progress = document.createElement("p");
  progress.id = "live-demo-progress";
  progress.setAttribute("role", "status");
  const controls = document.createElement("div");
  controls.className = "live-demo-controls";
  for (const [id, label] of [["confirm", "Confirm plan & run"], ["resume", "Resume current task"], ["stop", "Stop execution"]]) {
    const button = document.createElement("button");
    button.type = "button";
    button.id = `live-demo-${id}`;
    button.textContent = label;
    button.hidden = true;
    button.addEventListener("click", () => id === "stop" ? stopActiveJob()
      : sendReply({preventDefault() {}}, liveDemoCatalog[id]));
    controls.appendChild(button);
  }
  const recording = document.createElement("a");
  recording.href = "https://result4.mrcat.science/#example-result4";
  recording.target = "_blank";
  recording.rel = "noopener";
  recording.textContent = "View a completed Result 4 session ↗";
  panel.append(intro, steps, progress, preview, controls, recording);
  updateLiveDemo();
}

function previewDemoPrompt(prompt) {
  document.getElementById("live-demo-prompt").textContent = prompt;
  document.getElementById("live-demo-preview").open = true;
  updateLiveDemo();
}

function updateLiveDemo() {
  if (!LIVE_DEMO || !liveDemoCatalog) return;
  const snapshot = state.snapshot;
  const events = snapshot?.mr?.events || [];
  const messages = events.filter(event => event.type === "user_message").map(event => event.content);
  const running = Boolean(snapshot?.active_job);
  const loading = Boolean(state.currentSessionId && !snapshot);
  const pending = Boolean(snapshot?.pending_question);
  const failed = ["failed", "paused", "stopped"].includes(snapshot?.state?.status);
  const activeTask = activeMrTask(snapshot);
  const unfinished = Boolean(activeTask && activeTask.status !== "completed");
  const next = liveDemoCatalog.steps.findIndex(step => !messages.includes(step.prompt));
  const locked = state.busy || running || loading || pending || failed || unfinished;
  document.querySelectorAll("[data-demo-step]").forEach((button, index) => {
    button.disabled = locked || index !== next || (index === 0 && Boolean(state.currentSessionId));
    // A submitted request is not proof that the computation succeeded.
    button.dataset.submitted = String(messages.includes(liveDemoCatalog.steps[index].prompt));
  });
  const selected = document.getElementById("live-demo-prompt").textContent;
  document.getElementById("live-demo-send").disabled = locked || next < 0 || selected !== liveDemoCatalog.steps[next]?.prompt;
  document.getElementById("live-demo-preview").hidden = !selected || messages.includes(selected);
  const confirm = document.getElementById("live-demo-confirm");
  confirm.hidden = !pending || running;
  confirm.disabled = state.busy;
  const resume = document.getElementById("live-demo-resume");
  resume.hidden = !failed || running;
  resume.disabled = state.busy;
  const stop = document.getElementById("live-demo-stop");
  stop.hidden = !running;
  stop.disabled = state.busy;
  document.getElementById("live-demo-progress").textContent = loading ? "Loading your session…"
    : state.busy ? "Submitting your request…"
    : running ? "Running · follow the conversation and execution notebook below."
    : pending ? "Review the plan or question in the conversation before confirming."
    : failed ? "Execution paused or failed. Inspect the message below before resuming."
    : unfinished ? "The current analysis is not complete. Inspect the conversation for details."
    : next < 0 ? "The guided requests have finished. Inspect the result tables and plots below."
    : state.currentSessionId ? "Ready for the next request in this session."
    : "Start with 1a · Search the literature.";
  document.querySelectorAll("#study-setup-content input, #study-setup-content select, #study-setup-content textarea, #study-setup-content button").forEach(element => { element.disabled = true; });
}
