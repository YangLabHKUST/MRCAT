/* Read-only notebook projection of saved session events and artifacts. */
const notebook = {
  session: "",
  task: "",
  cells: new Map(),
  focusedExecutionId: "",
  focusCleanup: null,
  collapsedCells: new Set(),
  resources: new Map(),
  fileOwners: new Map(),
  revision: 0,
  scheduled: false,
  view: "task",
};

function notebookElement(tag, className = "", label = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (label) node.textContent = label;
  return node;
}

function resetExecutionNotebook() {
  notebook.focusCleanup?.();
  disposeQcExplorers(els.notebookOutput);
  notebook.session = "";
  notebook.task = "";
  notebook.focusedExecutionId = "";
  notebook.cells.clear();
  notebook.collapsedCells.clear();
  notebook.resources.clear();
  notebook.fileOwners.clear();
  notebook.revision += 1;
  notebook.view = "task";
  els.notebookOutput?.replaceChildren();
  if (els.notebookOutput) delete els.notebookOutput.dataset.signature;
}

function setNotebookView(view) {
  if (!["task", "builder"].includes(view) || notebook.view === view) return;
  notebook.focusCleanup?.();
  notebook.view = view;
  els.notebookOutput.scrollTop = 0;
  renderExecutionNotebook();
}

function scheduleNotebookRender(sessionId) {
  if (sessionId !== state.currentSessionId || notebook.scheduled) return;
  notebook.scheduled = true;
  requestAnimationFrame(() => {
    notebook.scheduled = false;
    if (sessionId === state.currentSessionId) renderExecutionNotebook();
  });
}

function notebookResource(snapshot, path, format = "json") {
  const url = artifactRawUrl(snapshot, path);
  if (!url) return null;
  const key = `${format}:${url}`;
  if (notebook.resources.has(key)) return notebook.resources.get(key);
  const entry = { status: "loading", value: null, error: "" };
  notebook.resources.set(key, entry);
  const sessionId = state.currentSessionId;
  const revision = notebook.revision;
  entry.promise = fetch(url).then(async (response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const value = format === "json" ? await response.json()
      : format === "preview" ? await readNotebookTextPreview(response)
      : await response.text();
    entry.status = "ready";
    entry.value = value;
    return value;
  }).catch((error) => {
    entry.status = "error";
    entry.error = error.message;
    return null;
  }).finally(() => {
    if (revision === notebook.revision) scheduleNotebookRender(sessionId);
  });
  return entry;
}

function buildNotebookSearchResults(file, snapshot, events) {
  const section = notebookElement("section", "notebook-search-results");
  section.dataset.path = file.path;
  section.appendChild(notebookElement("p", "muted", "Loading GWAS candidates…"));
  const owner = [...events].reverse().find(event => event.details?.generated_files?.includes(file.path));
  const version = owner ? `${owner.id}:${owner.details.status}` : "";
  void loadJsonArtifact(snapshot, file.path, "mr", version).then(payload => {
    if (!Array.isArray(payload?.candidates)) throw new Error("No candidate list in this file.");
    const target = payload.target || {};
    const diagnostics = payload.diagnostics || {};
    const dataSearch = {targets: [{
      target: target.kind === "study_id" ? {study_id: target.value} : {trait: target.resolved_query || target.value},
      resolved_target: target,
      candidates: payload.candidates,
    }]};
    const key = `${snapshot.session_id}:${file.path}`;
    const render = () => {
      section.replaceChildren(buildDataSearchPanel(dataSearch, key, render));
      const issues = (diagnostics.source_reports || []).filter(report => report.status === "error");
      if (issues.length) {
        section.appendChild(notebookElement("p", "muted", "Search source issues: " + issues.map(report => `${report.source} (${report.status})`).join(", ") + ". See the saved results for details."));
      }
      const link = buildExternalLink(artifactRawUrl(snapshot, file.path), "Download candidate data");
      link.download = artifactBasename(file.path);
      section.appendChild(link);
    };
    render();
  }).catch(error => {
    section.replaceChildren(notebookElement("p", "muted", `Candidate preview unavailable: ${error.message}`));
    section.appendChild(buildExternalLink(artifactRawUrl(snapshot, file.path), "Open candidate data"));
  });
  return section;
}

// Both panes number the same execution events, including failures and retries.
function codeExecutionEvents(snapshot) {
  return (snapshot?.mr?.events || []).filter(event => event.type === "code_execution");
}

function codeExecutionStatus(details) {
  if (details.status === "exited") {
    if (details.returncode === 0) return "Completed";
    return details.returncode == null ? "Exit status unavailable" : `Failed (exit ${details.returncode})`;
  }
  return {running: "Running", cancelled: "Stopped", timeout: "Timed out", launch_error: "Could not start", failed: "Failed"}[details.status] || "Status unavailable";
}

function codeExecutionTone(details) {
  if (details.status === "running") return "running";
  if (details.status === "exited" && details.returncode === 0) return "completed";
  if (["timeout", "launch_error", "failed"].includes(details.status)
      || (details.status === "exited" && details.returncode != null && details.returncode !== 0)) return "failed";
  return "neutral";
}

function codeExecutionHeading(event) {
  const lines = text(event.content).split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const title = (lines.shift() || "Analysis execution")
    .replace(/^#{1,6}\s+|^[-*]\s+|^\d+[.)]\s+/, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/[*`]/g, "");
  return {
    title: title.length > 160 ? title.slice(0, 160) + "…" : title,
    description: (title.length > 160 ? [title, ...lines] : lines).join("\n"),
  };
}

function focusCodeExecution(executionId) {
  setNotebookView("task");
  const cell = notebook.cells.get(executionId)?.node;
  if (cell) focusNotebookElement(cell);
}

function focusNotebookElement(target) {
  notebook.focusCleanup?.();
  const host = els.notebookOutput;
  const executionId = target.closest(".codeact-cell")?.dataset.executionId || "";
  notebook.focusedExecutionId = executionId;
  for (const [id, entry] of notebook.cells) entry.node.classList.toggle("is-selected", id === executionId);
  for (const previous of host.querySelectorAll(".is-artifact-selected")) previous.classList.remove("is-artifact-selected");
  if (target !== target.closest(".codeact-cell")) target.classList.add("is-artifact-selected");
  target.tabIndex = -1;
  target.focus({preventScroll: true});
  let frame = 0;
  const align = () => {
    frame = 0;
    if (!target.isConnected) { stop(); return; }
    const offset = target.getBoundingClientRect().top - host.getBoundingClientRect().top - 12;
    if (Math.abs(offset) > 1) host.scrollTo({top: host.scrollTop + offset, behavior: "instant"});
  };
  // Earlier results and lazy images can change the target's position after a click.
  const observer = new ResizeObserver(() => {
    if (!frame) frame = requestAnimationFrame(align);
  });
  const interactions = ["wheel", "touchstart", "pointerdown", "keydown"];
  const stop = () => {
    observer.disconnect();
    cancelAnimationFrame(frame);
    for (const type of interactions) host.removeEventListener(type, stop, true);
    notebook.focusCleanup = null;
  };
  notebook.focusCleanup = stop;
  for (const type of interactions) host.addEventListener(type, stop, {capture: true, passive: true});
  observer.observe(host);
  for (const cell of host.children) observer.observe(cell);
  align();
}

function notebookOutputFiles(snapshot) {
  return Object.values(snapshot?.mr?.manifest?.artifacts || {})
    .flatMap(run => Object.values(run).flat())
    .filter(file => file.path.startsWith("workspace/") && !file.path.startsWith("workspace/inputs/"));
}

function focusNotebookArtifact(path) {
  setNotebookView("task");
  renderExecutionNotebook();
  const owner = notebook.fileOwners.get(path);
  const scope = notebook.cells.get(owner?.executionId)?.node || els.notebookOutput;
  const escaped = CSS.escape(path);
  const directory = path.slice(0, path.lastIndexOf("/") + 1);
  const searchResult = [...scope.querySelectorAll(".notebook-search-results[data-path], .notebook-search-artifact[data-path]")]
    .find(node => node.dataset.path.slice(0, node.dataset.path.lastIndexOf("/") + 1) === directory);
  let target = path.endsWith("/response.json") ? searchResult : null;
  target ||= scope.querySelector(`[data-result-path="${escaped}"]`)
    || scope.querySelector(`.notebook-search-results[data-path="${escaped}"], .notebook-search-artifact[data-path="${escaped}"], figure[data-path="${escaped}"], .skill-data-preview-tabs button[data-path="${escaped}"]`);
  // Result records, including reports/*_result.json, use their invocation's response view.
  if (!target && /(?:_result(?:_record)?|gwas_qc_format_report|gwas_pair_prepare_record|response)\.json$/.test(path)) {
    target = [...scope.querySelectorAll(".codeact-result[data-result-path]")]
      .filter(node => path.startsWith(node.dataset.resultPath.slice(0, node.dataset.resultPath.lastIndexOf("/") + 1)))
      .sort((left, right) => right.dataset.resultPath.length - left.dataset.resultPath.length)[0]
      || searchResult;
  }
  target ||= scope.querySelector(`.notebook-file[data-path="${escaped}"]`);
  if (!target) return false;
  if (target.matches(".skill-data-preview-tabs button")) {
    target.click();
    target = target.closest(".skill-data-preview");
  }
  for (let node = target; node && node !== els.notebookOutput; node = node.parentElement) {
    if (node.tagName === "DETAILS") node.open = true;
  }
  focusNotebookElement(target);
  return true;
}

function notebookFileOwners(events) {
  const owners = new Map();
  events.forEach((event, index) => {
    for (const path of event.details.generated_files || []) {
      owners.set(path, {executionId: event.details.execution_id, number: index + 1});
    }
  });
  return owners;
}

function notebookFileCellLink(owner) {
  const button = notebookElement("button", "codeact-file-owner", `Cell ${owner.number}`);
  button.type = "button";
  button.setAttribute("aria-label", `View Cell ${owner.number} in Execution Notebook`);
  button.addEventListener("click", () => focusCodeExecution(owner.executionId));
  return button;
}

function appendCodeExecutionFile(section, file, snapshot, events) {
  if (nativeSearchArtifactKind(file)) section.appendChild(buildNotebookSearchArtifact(file, snapshot));
  if (artifactBasename(file.path) === "gwas_search_shortlists.json") {
    section.appendChild(buildNotebookSearchResults(file, snapshot, events));
  }
  if (notebookPngPath(file.path)) {
    const image = notebookElement("img", "notebook-figure-image");
    image.src = artifactRawUrl(snapshot, file.path);
    image.alt = file.summary || artifactBasename(file.path);
    image.loading = "lazy";
    image.style.maxWidth = "100%";
    section.appendChild(image);
  }
  section.appendChild(buildNotebookFile(file, snapshot));
}

// Result views consume saved MRCAT artifacts, never inferred skill invocations.
function codeExecutionArtifactPath(value, files) {
  if (typeof value !== "string") return "";
  const candidates = files.filter(file => value === file.path || value.endsWith(`/${file.path}`));
  return candidates.length === 1 ? candidates[0].path : "";
}

function codeExecutionResultFiles(files) {
  const responses = files.filter(file => artifactBasename(file.path) === "response.json");
  return [...responses, ...files.filter(file => /(?:_result_record|gwas_qc_format_report|gwas_pair_prepare_record)\.json$/.test(file.path)
    && !responses.some(response => file.path.startsWith(response.path.slice(0, -"response.json".length))))];
}

function buildCodeExecutionResult(file, snapshot, files) {
  const section = notebookElement("section", "codeact-result");
  section.dataset.resultPath = file.path;
  section.appendChild(notebookElement("p", "muted", "Loading saved result…"));
  const resource = notebookResource(snapshot, file.path);
  void resource.promise.then(record => {
    if (resource.status === "error") throw new Error(resource.error);
    if (!record || typeof record !== "object" || Array.isArray(record)) throw new Error("Expected a saved result object.");
    section.replaceChildren();
    const outputs = record.outputs && typeof record.outputs === "object" ? record.outputs : null;
    const results = outputs ? Object.entries(outputs).filter(([, value]) => value && typeof value === "object" && !Array.isArray(value)) : [["", record]];
    const summary = text(record.summary || record.interpretation?.summary);
    const status = text(record.details?.result_status || outputs?.status);
    const firstParagraph = summary.split(/\n\s*\n/)[0];
    if (summary) section.appendChild(notebookElement("p", "codeact-result-summary",
      firstParagraph.length > 360 ? firstParagraph.slice(0, 360) + "…" : firstParagraph));
    if (status && !["ok", "success", "completed"].includes(status.toLowerCase())) {
      section.appendChild(notebookElement("p", "notebook-warning", `Recorded result status: ${status}`));
    }
    for (const [key, payload] of results) {
      const methods = methodResultRows(payload);
      const summaryTablePath = codeExecutionArtifactPath(payload.summary_table_path, files);
      const hasSummaryTable = codeExecutionDataViews(files).some(view => view.artifact.path === summaryTablePath);
      const title = {gwas_qc_result: "GWAS quality control", gwas_pair_prepare_result: "Harmonization and LD clumping"}[key]
        || (methods.length ? methods.map(row => row.method).filter(Boolean).join(" · ") : "")
        || (key ? key.replace(/_result$/, "").replaceAll("_", " ") : text(payload.method) || artifactBasename(file.path).replace(/\.json$/, "").replaceAll("_", " "));
      section.appendChild(notebookElement("h5", "codeact-result-title", title));
      if (methods.length) {
        section.appendChild(buildMrMethodResultTable(methods.map(row => Object.fromEntries(Object.entries(row).map(([key, value]) => [key, value === null ? undefined : value])))));
      }
      if (!hasSummaryTable && Array.isArray(payload.estimates) && payload.estimates.length) section.appendChild(buildAggregateAnalysisTable(payload.estimates));
      if (Array.isArray(payload.mediation_paths) && payload.mediation_paths.length) section.appendChild(buildAggregateAnalysisTable(payload.mediation_paths, true));
      const sensitivity = notebookElement("div", "analysis-sensitivity-grid");
      for (const [name, value] of [["Heterogeneity", payload.heterogeneity], ["Directional pleiotropy", payload.pleiotropy], ["Leave one out", payload.leave_one_out], ["MR-PRESSO", payload.mr_presso]]) {
        if (!value || typeof value !== "object") continue;
        const card = notebookElement("article", "analysis-sensitivity-card");
        card.appendChild(notebookElement("strong", "", name));
        renderNotebookJsonPreview(card, value, JSON.stringify(value), name);
        sensitivity.appendChild(card);
      }
      if (sensitivity.children.length) section.appendChild(sensitivity);
      const metrics = extractSkillSummaryMetrics(summary);
      if (key === "gwas_qc_result") {
        if (payload.label) section.appendChild(notebookElement("p", "", payload.label));
        const retention = buildQcRetentionVisual(metrics);
        if (retention) section.appendChild(retention);
      } else if (key === "gwas_pair_prepare_result") {
        section.appendChild(buildPairPreparationVisual(metrics, {
          exposure: {label: payload.exposure_label}, outcome: {label: payload.outcome_label},
        }));
      } else if (!key && payload.total_input != null && payload.total_final != null) {
        const retention = buildQcRetentionVisual(extractSkillSummaryMetrics(`canonical_rows=${payload.total_input}, formatted_rows=${payload.total_final}`));
        if (retention) section.appendChild(retention);
      } else if (!key && payload.mdat_path && payload.mrdat_path) {
        section.appendChild(buildPairPreparationVisual(metrics, {exposure: {label: payload.exposure_label}, outcome: {label: payload.outcome_label}}));
      } else if (!payload.methods && metrics.length) {
        section.appendChild(buildSkillMetricGrid(metrics));
      }
      // Interactive views use only the instrument table/estimates referenced by this result.
      for (const plot of payload.plot_manifest?.plots || []) {
        const path = codeExecutionArtifactPath(plot.path, files);
        if (!path) continue;
        const figure = section.closest(".codeact-cell")?.querySelector(`figure[data-path="${CSS.escape(path)}"]`);
        if (figure && plot.title) figure.querySelector("figcaption strong").textContent = plot.title;
        const explanation = codeExecutionArtifactPath(plot.explanation_path, files);
        if (figure && explanation) figure.appendChild(buildNotebookFile({path: explanation}, snapshot));
        const image = figure?.querySelector(".notebook-figure-link");
        if (!image) continue;
        if (plot.plot_id === "primary_scatter") {
          const selected = codeExecutionArtifactPath(payload.selected_mrdat_path, files);
          if (selected) figure.insertBefore(buildPrimaryScatter(snapshot, {payload: {...payload, selected_mrdat_path: selected}, artifacts: files}, image), image);
        } else if (plot.plot_id === "replication_forest_matrix" && Array.isArray(payload.estimates) && Array.isArray(payload.analyses)) {
          figure.insertBefore(buildReplicationForest(snapshot, {payload}, image), image);
        }
      }
    }
    if (summary.length > firstParagraph.length || firstParagraph.length > 360) {
      const detail = notebookDisclosure("Read full summary", `result-summary:${file.path}`);
      detail.appendChild(notebookElement("p", "codeact-result-summary", summary));
      section.appendChild(detail);
    }
    for (const note of record.details?.risk_notes || []) {
      section.appendChild(notebookElement("p", "notebook-warning", typeof note === "string" ? note : JSON.stringify(note)));
    }
    if (!section.children.length) section.appendChild(notebookElement("p", "muted", "Open the saved record to inspect this result."));
    section.appendChild(buildNotebookFile(file, snapshot));
  }).catch(error => {
    section.replaceChildren(notebookElement("p", "muted", `Result preview unavailable: ${error.message}`), buildNotebookFile(file, snapshot));
  });
  return section;
}

function codeExecutionDataViews(files) {
  return files.filter(file => isPreviewableTableArtifact(file) && !/\/(?:samples|generated_code)\//.test(file.path)).map(file => {
    const name = artifactBasename(file.path);
    const label = name.includes("mrdat_clumped") ? "Clumped SNPs"
      : name === "gwas_pair_mdat.tsv.gz" || name === "gwas_pair_mdat.tsv" ? "Harmonized SNPs"
      : /\.mrapss\.tsv(?:\.gz)?$/.test(name) ? "Formatted GWAS"
      : name === "selected_mrdat.tsv" ? "Selected instruments" : name;
    return {id: file.path, label, description: file.path, artifact: file};
  }).sort((a, b) => {
    const order = ["Formatted GWAS", "Clumped SNPs", "Harmonized SNPs", "Selected instruments"];
    const rank = view => order.includes(view.label) ? order.indexOf(view.label) : order.length;
    return rank(a) - rank(b);
  });
}

function nativeSearchArtifactKind(file) {
  return {"search.json": "web_search", "scan_design.json": "scan_design"}[artifactBasename(file.path)] || "";
}

function reviewSearchQuery(snapshot, file, payload, query) {
  if (state.currentSessionId !== snapshot.session_id || state.busy || state.snapshot?.active_job || els.replyInput.disabled) return;
  els.replyInput.value = `Please propose an MR analysis plan for the selected query below and wait for plan confirmation. Use only the selected traits; do not reintroduce unselected candidates from the original request or evidence. Preserve all other source, ancestry, study-ID, method and threshold constraints.\n\n${query}\n\nOriginal request and constraints: ${text(payload.request)}\nSaved evidence: ${file.path}`;
  els.replyInput.focus();
}

function buildNotebookSearchArtifact(file, snapshot, version = "") {
  const kind = nativeSearchArtifactKind(file);
  const section = notebookElement("section", `notebook-search-artifact notebook-${kind.replaceAll("_", "-")}`);
  section.dataset.path = file.path;
  section.appendChild(notebookElement("p", "muted", "Loading saved Search result…"));
  const revision = version || notebook.fileOwners.get(file.path)?.version || "";
  void loadJsonArtifact(snapshot, file.path, "mr", revision).then(payload => {
    if (payload?.kind !== kind) throw new Error("This file does not contain the expected Search result.");
    if (kind === "scan_design") {
      section.replaceChildren(buildNotebookScanDesign(file, snapshot, payload));
    } else {
      section.replaceChildren(buildNotebookWebSearch(file, snapshot, payload));
    }
  }).catch(error => section.replaceChildren(notebookElement("p", "notebook-warning", `Could not load Search result: ${error.message}`)));
  return section;
}

function buildNotebookWebSearch(file, snapshot, payload) {
  if (typeof payload.answer !== "string" || !payload.answer.trim()) throw new Error("Search answer is missing.");
  const body = payload.answer;
  const report = parseSearchReportMarkdown(body) || {
    title: "Search Findings", introMarkdown: "", sections: [{heading: "Findings", markdown: body}],
    mainSectionCount: 1, referenceCount: 0,
  };
  report.query = text(payload.query);
  const references = [];
  for (const [index, item] of (Array.isArray(payload.citations) ? payload.citations : []).entries()) {
    let url;
    try {
      url = new URL(item?.url);
      if (!["http:", "https:"].includes(url.protocol)) continue;
    } catch { continue; }
    references.push({number: text(item.citation_id) || String(index + 1), id: text(item.id),
      title: text(item.title) || url.hostname, url: url.href});
  }
  if (references.length) {
    report.sections.push({heading: "References", markdown: "", references});
    report.referenceCount = references.length;
  }
  // Artifact identity keeps expansion state independent across cells and sessions.
  const card = buildSearchReportCard(report, {run_id: `${snapshot.session_id}:${file.path}`}, body);
  const meta = card.querySelector(".search-report-heading > span");
  const provider = text(payload.provider);
  const failed = (Array.isArray(payload.attempts) ? payload.attempts : [])
    .filter(attempt => attempt.status === "failed").map(attempt => text(attempt.provider)).filter(Boolean);
  if (provider) meta.textContent += ` · ${provider}${failed.length ? ` (fallback from ${failed.join(", ")})` : ""}`;
  if (!references.length) card.appendChild(notebookElement("p", "muted", "No source links were saved with this search."));
  return card;
}

function buildNotebookScanDesign(file, snapshot, payload) {
  const design = payload.scan_design;
  const exposure = design?.exposure_list;
  const outcome = design?.outcome_list;
  if (!Array.isArray(exposure) || !Array.isArray(outcome)
      || !exposure.length || !outcome.length
      || [...exposure, ...outcome].some(item => !item || typeof item.trait !== "string" || !item.trait.trim())) {
    throw new Error("Scan design requires named exposure and outcome traits.");
  }
  // Keep choices local to this browser tab, session, file and exact trait lists.
  const key = JSON.stringify([snapshot.session_id, file.path, exposure, outcome]);
  const storageKey = `mrcat.scanSelection:${key}`;
  if (!state.scanSelection[key]) {
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey));
      if (Array.isArray(saved?.exposure) && Array.isArray(saved?.outcome)) state.scanSelection[key] = saved;
    } catch { /* Storage may be unavailable; in-memory choices still work. */ }
  }
  const selection = scanSelectionForArtifact(key, exposure.length, outcome.length);
  const panel = notebookElement("section", "data-search-panel scan-design-panel");
  function render() {
    selection.exposure = normalizeScanIndices(selection.exposure, exposure.length);
    selection.outcome = normalizeScanIndices(selection.outcome, outcome.length);
    const count = selection.exposure.length * selection.outcome.length;
    panel.replaceChildren(notebookElement("h4", "", "Scan design"), notebookElement("p", "data-search-summary",
      `${selection.exposure.length} exposure traits × ${selection.outcome.length} outcome traits = ${count} scan pairs`));
    const grid = notebookElement("div", "data-search-grid scan-design-grid");
    const toggle = (side, index) => {
      const values = selection[side];
      selection[side] = values.includes(index) ? values.filter(value => value !== index) : [...values, index];
      try { sessionStorage.setItem(storageKey, JSON.stringify(selection)); } catch { /* Keep in-memory choices. */ }
      render();
      panel.querySelector(`[data-scan-side="${side}"] [data-scan-index="${index}"]`)?.focus({preventScroll: true});
    };
    grid.append(buildScanTraitTable("exposure", exposure, key, exposure.length, outcome.length, toggle),
      buildScanTraitTable("outcome", outcome, key, exposure.length, outcome.length, toggle));
    panel.appendChild(grid);
    if (text(design.rationale)) panel.appendChild(notebookElement("p", "scan-rationale", text(design.rationale)));
    const submit = notebookElement("button", "query-button notebook-scan-submit", "Review selected scan query");
    submit.type = "button";
    submit.dataset.searchAction = "review";
    submit.dataset.emptySelection = String(!count);
    submit.disabled = !count || state.busy || Boolean(state.snapshot?.active_job);
    submit.addEventListener("click", () => {
      if (!selection.exposure.length || !selection.outcome.length) return;
      const query = ["PHENOME_SCAN",
        `exposure_traits=${JSON.stringify(selection.exposure.map(index => exposure[index].trait))}`,
        `outcome_traits=${JSON.stringify(selection.outcome.map(index => outcome[index].trait))}`,
      ].join("\n");
      reviewSearchQuery(snapshot, file, payload, query);
    });
    panel.appendChild(submit);
  }
  render();
  return panel;
}

function buildSearchQueryChoices(file, snapshot, version) {
  const section = notebookElement("section", "notebook-search-queries");
  section.dataset.path = file.path;
  section.appendChild(notebookElement("p", "muted", "Loading proposed analysis queries…"));
  void loadJsonArtifact(snapshot, file.path, "mr", version).then(payload => {
    if (payload?.kind !== "research_brief" || !Array.isArray(payload.pipeline_queries)) {
      throw new Error("No proposed queries in this document.");
    }
    section.replaceChildren(notebookElement("h4", "", "Proposed analysis queries"));
    if (!payload.pipeline_queries.length) section.appendChild(notebookElement("p", "muted", "No executable query proposed. Review the brief for missing information."));
    for (const query of payload.pipeline_queries) {
      if (typeof query !== "string" || !query.trim()) continue;
      const button = notebookElement("button", "query-button", query);
      button.type = "button";
      button.title = "Copy this query to the message box for review";
      button.dataset.searchAction = "review";
      button.disabled = state.busy || Boolean(state.snapshot?.active_job);
      button.addEventListener("click", () => reviewSearchQuery(snapshot, file, payload, query));
      section.appendChild(button);
    }
  }).catch(error => section.replaceChildren(notebookElement("p", "muted", `Could not load proposed queries: ${error.message}`)));
  return section;
}

function appendCodeExecutionOutputs(cell, files, snapshot, events, version) {
  const searchArtifacts = files.filter(file => nativeSearchArtifactKind(file));
  const results = codeExecutionResultFiles(files).filter(file => !searchArtifacts.some(artifact =>
    file.path === artifact.path.replace(/[^/]+$/, "response.json")));
  const searches = files.filter(file => artifactBasename(file.path) === "gwas_search_shortlists.json");
  const reports = files.filter(file => /(?:^|\/)(?:final_summary|report|research_brief)\.md$/.test(file.path));
  const documents = files.filter(file => /(?:^|\/)research_brief\.json$/.test(file.path));
  const displayed = new Set([...results, ...searches, ...reports, ...documents, ...searchArtifacts].map(file => file.path));
  if (results.length || searches.length || reports.length || documents.length || searchArtifacts.length) {
    const result = notebookSection("Result");
    result.classList.add("codeact-results", "notebook-result-section");
    for (const file of searches) {
      result.appendChild(buildNotebookSearchResults(file, snapshot, events));
      result.appendChild(buildNotebookFile(file, snapshot));
    }
    for (const file of results) result.appendChild(buildCodeExecutionResult(file, snapshot, files));
    for (const file of reports) {
      const preview = buildNotebookFile(file, snapshot);
      preview.open = true;
      result.appendChild(preview);
    }
    for (const file of searchArtifacts) {
      result.appendChild(buildNotebookSearchArtifact(file, snapshot, version));
      result.appendChild(buildNotebookFile(file, snapshot));
    }
    for (const file of documents) {
      result.appendChild(buildSearchQueryChoices(file, snapshot, version));
      result.appendChild(buildNotebookFile(file, snapshot));
    }
    cell.appendChild(result);
  }
  const views = codeExecutionDataViews(files);
  if (views.length) {
    const data = notebookSection("Data preview");
    data.classList.add("codeact-data");
    data.appendChild(buildSkillDataPreview(views, snapshot));
    cell.appendChild(data);
  }
  const images = files.filter(file => notebookPngPath(file.path));
  if (images.length) {
    const figures = notebookSection("Figures");
    figures.classList.add("codeact-figures");
    const qcGroups = new Map();
    for (const file of images) {
      displayed.add(file.path);
      const sidecar = file.path.replace(/\.png$/i, ".plot.json");
      if (qcPlotKind(file.path) && files.some(candidate => candidate.path === sidecar)) {
        const folder = file.path.slice(0, file.path.lastIndexOf("/"));
        if (!qcGroups.has(folder)) qcGroups.set(folder, []);
        qcGroups.get(folder).push(file);
      } else {
        figures.appendChild(buildNotebookFigure(file, snapshot));
      }
      figures.appendChild(buildNotebookFile(file, snapshot));
    }
    for (const plots of qcGroups.values()) figures.appendChild(buildQcExplorer(plots, snapshot));
    cell.appendChild(figures);
  }
  const remaining = files.filter(file => !displayed.has(file.path));
  if (remaining.length) {
    const output = notebookDisclosure(`Files (${remaining.length})`, `files:${version}`);
    output.classList.add("codeact-artifacts");
    for (const file of remaining) output.appendChild(buildNotebookFile(file, snapshot));
    cell.appendChild(output);
  }
}

function buildCodeExecutionCell(event, index, files, owners, snapshot, events) {
  const d = event.details;
  const tone = codeExecutionTone(d);
  const heading = codeExecutionHeading(event);
  const cell = notebookElement("article", `notebook-cell codeact-cell is-${tone}`);
  cell.dataset.executionId = d.execution_id;
  cell.id = `codeact-cell-${d.execution_id}`;
  cell.tabIndex = -1;
  const head = notebookElement("header", "codeact-cell-head");
  const identity = notebookElement("div", "codeact-cell-identity");
  const title = notebookElement("h4", "codeact-cell-title", heading.title);
  title.title = heading.title;
  identity.appendChild(title);
  const meta = [`Cell ${index + 1}`, d.language, d.duration_seconds == null ? "" : formatDuration(d.duration_seconds),
    {search: "Search Agent", mr: "MR Agent", report: "Report Agent"}[d.agent], d.task_id].filter(Boolean);
  identity.appendChild(notebookElement("span", "codeact-cell-meta", meta.join(" · ")));
  const status = notebookElement("span", `codeact-cell-status is-${tone}`, codeExecutionStatus(d));
  head.append(identity, status);
  cell.appendChild(head);
  if (heading.description) {
    const purpose = notebookDisclosure("Execution notes", `purpose:${d.execution_id}`);
    purpose.classList.add("codeact-purpose");
    purpose.appendChild(notebookElement("p", "codeact-cell-purpose", heading.description));
    cell.appendChild(purpose);
  }
  if (tone === "failed") {
    const message = text(d.stderr || d.stdout).split(/\r?\n/).filter(line => line.trim()).at(-1);
    const error = notebookElement("div", "codeact-cell-error");
    error.appendChild(notebookElement("strong", "", codeExecutionStatus(d)));
    if (message) error.appendChild(notebookElement("p", "", message.length > 300 ? message.slice(0, 300) + "…" : message));
    error.appendChild(notebookElement("p", "muted", "Open execution details for the full code and logs."));
    cell.appendChild(error);
  }
  const paths = [...new Set(d.generated_files || [])].filter(path => path.startsWith("workspace/") && !path.startsWith("workspace/inputs/"));
  const available = files.filter(file => paths.includes(file.path) && owners.get(file.path)?.executionId === d.execution_id);
  appendCodeExecutionOutputs(cell, available, snapshot, events, `${d.execution_id}:${d.status}:${d.returncode}`);
  const history = notebookElement("div", "codeact-file-history");
  for (const path of paths) {
    const owner = owners.get(path);
    if (!files.some(file => file.path === path)) history.appendChild(notebookElement("p", "muted", `${artifactBasename(path)} · File no longer available`));
    else if (owner?.executionId !== d.execution_id) {
      const note = notebookElement("p", "", `${artifactBasename(path)} · Updated by `);
      note.title = path; note.appendChild(notebookFileCellLink(owner)); history.appendChild(note);
    }
  }
  if (history.children.length) cell.appendChild(history);
  const execution = notebookDisclosure("Execution details", `execution:${d.execution_id}`);
  execution.classList.add("codeact-execution-details");
  for (const [kind, label, output, empty] of [
    ["code", "Code", d.code, "No code recorded."],
    ["stdout", "Output", d.stdout, "No output."],
    ["stderr", "Logs / errors", d.stderr, "No logs or errors."],
  ]) {
    const section = notebookElement("section", `codeact-stream codeact-stream-${kind}`);
    const title = notebookElement("h4", "codeact-stream-title", label);
    if (kind !== "code") title.appendChild(notebookElement("span", "codeact-stream-channel", kind));
    const content = notebookElement("pre", kind === "code" ? "codeact-code" : "codeact-output", output || empty);
    content.classList.toggle("is-empty", !output);
    section.append(title, content); execution.appendChild(section);
  }
  for (const path of [d.source_path, d.stdout_path, d.stderr_path].filter(Boolean)) {
    const link = buildExternalLink(artifactRawUrl(snapshot, path), artifactBasename(path));
    link.classList.add("codeact-file"); execution.appendChild(link);
  }
  cell.appendChild(execution);
  return cell;
}

function renderExecutionNotebook() {
  const snapshot = state.snapshot;
  const host = els.notebookOutput;
  const previousScroll = host.scrollTop;
  const signature = JSON.stringify([snapshot?.session_id, snapshot?.mr?.events, snapshot?.mr?.manifest, notebook.view]);
  if (host.dataset.signature === signature) return;
  host.dataset.signature = signature;
  const previous = notebook.cells;
  notebook.cells = new Map();
  const events = codeExecutionEvents(snapshot);
  const visible = notebookOutputFiles(snapshot);
  const owners = notebookFileOwners(events);
  for (const [path, owner] of owners) {
    const event = events.find(event => event.details.execution_id === owner.executionId);
    const d = event?.details || {};
    owner.version = JSON.stringify([event?.id, d.status, d.returncode, d.duration_seconds, d.stdout?.length, d.stderr?.length]);
    if (notebook.fileOwners.get(path)?.version !== owner.version) {
      for (const format of ["preview", "text", "json"]) notebook.resources.delete(`${format}:${artifactRawUrl(snapshot, path)}`);
      state.tableArtifactCache.delete(artifactSpreadsheetUrl(snapshot, path));
    }
  }
  notebook.fileOwners = owners;
  const taskView = notebook.view === "task";
  const completed = events.filter(event => event.details.status === "exited" && event.details.returncode === 0).length;
  els.notebookStatus.textContent = taskView ? `${events.length} executions · ${completed} completed` : `${visible.length} files`;
  for (const [tab, selected] of [[els.notebookTaskTab, taskView], [els.notebookBuilderTab, !taskView]]) {
    tab.classList.toggle("active", selected); tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1;
    tab.setAttribute("aria-controls", "notebook-output");
  }
  els.notebookLatest.disabled = taskView ? !events.length : !visible.length;
  host.setAttribute("aria-label", taskView ? "Analysis steps and results" : "Generated files");
  const children = [];
  if (taskView) for (const [index, event] of events.entries()) {
    const paths = new Set(event.details.generated_files || []);
    const cellFiles = visible.filter(file => paths.has(file.path));
    const cellSignature = JSON.stringify([snapshot.session_id, event, index, cellFiles, [...paths].map(path => [path, owners.get(path)])]);
    let entry = previous.get(event.details.execution_id);
    if (!entry || entry.signature !== cellSignature) {
      const detailsState = new Map([...(entry?.node.querySelectorAll("details[data-detail]") || [])].map(node => [node.dataset.detail, node.open]));
      if (entry) disposeQcExplorers(entry.node);
      const node = buildCodeExecutionCell(event, index, cellFiles, owners, snapshot, events);
      for (const detail of node.querySelectorAll("details[data-detail]")) if (detailsState.has(detail.dataset.detail)) detail.open = detailsState.get(detail.dataset.detail);
      entry = {node, signature: cellSignature};
    }
    entry.node.classList.toggle("is-selected", notebook.focusedExecutionId === event.details.execution_id);
    notebook.cells.set(event.details.execution_id, entry); children.push(entry.node);
  }
  for (const [id, entry] of previous) if (!notebook.cells.has(id)) disposeQcExplorers(entry.node);
  const remaining = taskView ? visible.filter(file => !owners.has(file.path)) : visible;
  if (remaining.length) {
    const section = notebookElement("section", "codeact-artifacts");
    section.appendChild(notebookElement("h3", "", taskView ? "Other files" : "Files and figures"));
    for (const file of remaining) {
      const entry = notebookElement("div", "codeact-artifact-entry");
      const owner = owners.get(file.path);
      const source = notebookElement("p", "codeact-file-history", owner ? "Last generated or updated by " : file.path.startsWith("workspace/reports/") ? "Generated by Report Agent" : "No generating cell recorded");
      if (owner) source.appendChild(notebookFileCellLink(owner));
      entry.appendChild(source); appendCodeExecutionFile(entry, file, snapshot, events); section.appendChild(entry);
    }
    children.push(section);
  }
  if (!children.length) children.push(notebookElement("p", "empty-note", "Analysis results, data previews and figures will appear here as execution progresses."));
  // Keep unchanged cells mounted: unrelated events must not reset previews or charts.
  const keep = new Set(children);
  for (const node of [...host.children]) if (!keep.has(node)) node.remove();
  children.forEach((node, index) => { if (host.children[index] !== node) host.insertBefore(node, host.children[index] || null); });
  host.scrollTop = previousScroll;
}

function setNotebookCellCollapsed(cell, collapsed) {
  if (collapsed) notebook.collapsedCells.add(cell.dataset.cellKey);
  else notebook.collapsedCells.delete(cell.dataset.cellKey);
  cell.classList.toggle("is-collapsed", collapsed);
  cell.querySelector(".notebook-cell-body").hidden = collapsed;
  const toggle = cell.querySelector(".notebook-cell-toggle");
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.setAttribute("aria-label", collapsed ? "Expand cell" : "Collapse cell");
  toggle.title = collapsed ? "Expand cell" : "Collapse cell";
}

function notebookPngPath(path) {
  return /\.png$/i.test(text(path));
}

function notebookPreviewKind(artifact) {
  if (isPreviewableTableArtifact(artifact)) return "table";
  const path = text(artifact.path);
  if (/\.pdf$/i.test(path)) return "pdf";
  if (/\.html?$/i.test(path)) return "html";
  if (/\.md$/i.test(path)) return "markdown";
  if (/\.json$/i.test(path)) return "json";
  if (/\.(txt|log|jsonl|yaml|yml|py|r|sh)$/i.test(path)) return "text";
  return "";
}

function buildNotebookFile(artifact, snapshot) {
  const path = text(artifact.path);
  const name = artifactBasename(path);
  const kind = notebookPreviewKind(artifact);
  const inline = kind && kind !== "pdf";
  const file = notebookElement(inline ? "details" : "div", "notebook-file");
  file.dataset.path = path;
  if (inline) file.dataset.detail = `file:${path}`;
  const head = notebookElement(inline ? "summary" : "div", "notebook-file-head");
  const artifactLabel = text(artifact.label);
  const displayName = artifactLabel && artifactLabel !== name
    ? `${artifactLabel} · ${name}`
    : name;
  const filename = notebookElement("span", "notebook-file-name", displayName);
  filename.title = path;
  head.append(createUiIcon(artifactUiIcon(artifact)), filename);
  const url = artifactRawUrl(snapshot, path);
  const download = buildExternalLink(url, "Download");
  download.download = name;
  if (inline) {
    const action = notebookElement("span", "notebook-file-action", "Preview");
    head.appendChild(action);
    file.appendChild(head);
    const preview = notebookElement("div", "notebook-file-preview");
    const content = notebookElement("div", "notebook-file-content");
    preview.append(content, download);
    file.appendChild(preview);
    let loaded = false;
    file.addEventListener("toggle", async () => {
      action.textContent = file.open ? "Close preview" : "Preview";
      if (!file.open || loaded) return;
      loaded = true;
      content.textContent = "Loading preview…";
      try {
        if (kind === "table") {
          const payload = await loadTableArtifact(snapshot, path);
          renderSpreadsheetPreview(content, payload, { maxRows: 50 });
        } else {
          const entry = notebookResource(snapshot, path, "preview");
          if (!entry) throw new Error("File is unavailable");
          await entry.promise;
          if (entry.status === "error") {
            const key = `preview:${url}`;
            if (notebook.resources.get(key) === entry) notebook.resources.delete(key);
            throw new Error(entry.error);
          }
          renderNotebookTextPreview(content, entry.value, kind, name);
        }
      } catch (error) {
        content.textContent = `Preview unavailable: ${error.message}`;
        loaded = false;
      }
    });
  } else {
    if (kind === "pdf") head.appendChild(buildExternalLink(url, "Preview ↗"));
    else download.title = "Preview is not supported for this file format.";
    head.appendChild(download);
    file.appendChild(head);
  }
  return file;
}

async function readNotebookTextPreview(response) {
  const limit = 256 * 1024;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let content = "";
  let bytes = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) return { text: content + decoder.decode(), truncated: false };
    const remaining = limit - bytes;
    content += decoder.decode(value.subarray(0, remaining), { stream: true });
    bytes += value.length;
    if (bytes >= limit) {
      await reader.cancel();
      return { text: content + decoder.decode(), truncated: true };
    }
  }
}

function renderNotebookTextPreview(host, preview, kind, name) {
  host.replaceChildren();
  if (preview.truncated) host.appendChild(notebookElement("p", "muted", "Preview limited to 256 KB. Download the full file below."));
  if (kind === "html" && !preview.truncated) {
    const frame = notebookElement("iframe", "notebook-document");
    frame.title = name;
    frame.setAttribute("sandbox", "");
    frame.srcdoc = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\';">' + preview.text;
    host.appendChild(frame);
  } else if (kind === "markdown" && !preview.truncated) {
    const body = notebookElement("div", "message-body notebook-explanation");
    body.innerHTML = renderMarkdown(preview.text);
    host.appendChild(body);
  } else if (kind === "json" && !preview.truncated) {
    try {
      renderNotebookJsonPreview(host, JSON.parse(preview.text), preview.text, name);
    } catch {
      host.appendChild(notebookElement("pre", "notebook-code", preview.text || "Empty file."));
    }
  } else {
    host.appendChild(notebookElement("pre", "notebook-code", preview.text || "Empty file."));
  }
}

function renderNotebookJsonPreview(host, value, rawText, name) {
  const view = notebookElement("div", "notebook-json-view");
  view.setAttribute("aria-label", `${name} structured JSON preview`);
  view.appendChild(buildNotebookJsonValue(value, "Result", 0));
  const raw = notebookElement("details", "notebook-json-raw");
  raw.appendChild(notebookElement("summary", "", "Raw JSON"));
  raw.appendChild(notebookElement("pre", "notebook-code", JSON.stringify(value, null, 2) || rawText));
  host.append(view, raw);
}

function buildNotebookJsonValue(value, label, depth) {
  if (value === null || typeof value !== "object") {
    const row = notebookElement("div", "notebook-json-scalar");
    row.append(
      notebookElement("span", "notebook-json-key", label),
      notebookElement("span", "notebook-json-value", formatParameterValue(value)),
    );
    return row;
  }
  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index + 1), item])
    : Object.entries(value);
  const details = notebookElement("details", "notebook-json-node");
  details.open = depth === 0;
  const kind = Array.isArray(value) ? "items" : "fields";
  details.appendChild(notebookElement("summary", "", `${label} · ${entries.length} ${kind}`));
  const body = notebookElement("div", "notebook-json-node-body");
  for (const [key, item] of entries) {
    body.appendChild(buildNotebookJsonValue(item, key, depth + 1));
  }
  details.appendChild(body);
  return details;
}

function notebookSection(title) {
  const section = notebookElement("section", "notebook-section");
  section.appendChild(notebookElement("h5", "notebook-section-title", title));
  return section;
}

function notebookDisclosure(label, key) {
  const details = notebookElement("details", "notebook-details");
  details.dataset.detail = key;
  details.appendChild(notebookElement("summary", "", label));
  return details;
}

function buildNotebookFigure(plot, snapshot) {
  const figure = notebookElement("figure", "notebook-figure");
  const path = text(plot.path || plot.summary);
  figure.dataset.path = path;
  const title = text(plot.title || plot.plot_id) || artifactBasename(path);
  const url = artifactRawUrl(snapshot, path);
  const caption = notebookElement("figcaption", "");
  caption.appendChild(notebookElement("strong", "", title));
  caption.appendChild(buildExternalLink(url, "Open full size ↗"));
  figure.appendChild(caption);
  const link = buildExternalLink(url, "");
  link.className = "notebook-figure-link";
  const image = notebookElement("img");
  image.src = url;
  image.alt = title;
  image.loading = "lazy";
  image.addEventListener("error", () => {
    image.remove();
    link.textContent = "Preview unavailable · open the figure file";
  });
  link.appendChild(image);
  figure.appendChild(link);
  if (plot.explanation_path) figure.appendChild(buildNotebookFile({ path: plot.explanation_path }, snapshot));
  return figure;
}

function scrollToLatestNotebookCell() {
  const cells = els.notebookOutput.querySelectorAll(".codeact-cell");
  (cells[cells.length - 1] || els.notebookOutput.lastElementChild)?.scrollIntoView({block: "start", behavior: "smooth"});
}
