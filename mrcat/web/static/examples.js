/* Packaged, read-only recordings rendered by the regular conversation/notebook. */
const RESULT4_EXAMPLE_ROOT = "/static/examples/result4";
const RESULT4_EXAMPLE_ID = "example-result4";
const REPLAY_ONLY = document.body.dataset.replayOnly === "true";

function leaveExample() {
  state.example = null;
  document.body.classList.remove("viewing-example");
  document.getElementById("example-navigation").hidden = true;
}

async function openResult4Example() {
  newChat();
  state.currentSessionId = RESULT4_EXAMPLE_ID;
  state.example = {loading: true};
  updateComposer();
  try {
    const recording = await requestJson(`${RESULT4_EXAMPLE_ROOT}/recording.json`);
    if (state.currentSessionId !== RESULT4_EXAMPLE_ID) return;
    state.example = recording;
    document.body.classList.add("viewing-example");
    window.history.replaceState(null, "", `${location.pathname}${location.search}#${RESULT4_EXAMPLE_ID}`);
    const navigation = document.getElementById("example-navigation");
    navigation.replaceChildren();
    recording.stages.forEach((stage, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = stage.title;
      button.addEventListener("click", () => showExampleStage(index));
      navigation.appendChild(button);
    });
    const guide = document.createElement("a");
    guide.href = exampleArtifactUrl(recording.report_path);
    guide.target = "_blank";
    guide.rel = "noopener";
    guide.textContent = "Open final report ↗";
    navigation.appendChild(guide);
    navigation.hidden = false;
    showExampleStage(0);
  } catch (error) {
    if (state.currentSessionId !== RESULT4_EXAMPLE_ID) return;
    newChat();
    appendEmptyConversation(`Could not load the example: ${error.message}. Please try again.`);
  }
}

function showExampleStage(index) {
  const recording = state.example;
  if (!recording?.stages) return;
  const stage = recording.stages[index];
  const snapshot = structuredClone(recording.snapshot);
  snapshot.mr.events = snapshot.mr.events.slice(stage.start, stage.end);
  snapshot.mr.state.events = snapshot.mr.events;
  const paths = index === 0 ? new Set(Object.keys(recording.files))
    : new Set(snapshot.mr.events.flatMap(event => event.details?.generated_files || []));
  for (const run of Object.values(snapshot.mr.manifest.artifacts || {})) {
    run.files = run.files.filter(file => paths.has(file.path));
  }
  for (const run of Object.values(snapshot.mr.manifest.runs || {})) {
    run.artifacts.files = run.artifacts.files.filter(path => paths.has(path));
  }
  snapshot.images = snapshot.images.filter(image => paths.has(image.summary));
  state.snapshot = null;
  resetExecutionNotebook();
  applySnapshot(snapshot);
  els.sessionTitle.textContent = recording.title;
  els.sessionSubtitle.textContent = stage.description;
  els.statusChip.textContent = "Read only";
  els.conversationFeed.scrollTop = 0;
  document.querySelectorAll("#example-navigation button").forEach((button, i) => {
    button.setAttribute("aria-pressed", String(i === index));
  });
}

function exampleArtifactUrl(path, preview = false) {
  // Only files explicitly included in the reviewed export can be fetched.
  const file = state.example?.files?.[path];
  if (!file) return "";
  const asset = preview ? file.preview : file.path;
  return asset ? `${RESULT4_EXAMPLE_ROOT}/${asset.split("/").map(encodeURIComponent).join("/")}` : "";
}
