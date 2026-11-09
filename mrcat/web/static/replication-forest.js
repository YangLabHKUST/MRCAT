/* Interactive forest view of the exact estimates saved by analysis-replication. */
function replicationForestNumber(value) {
  if (value == null || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function replicationForestFormat(value) {
  const number = replicationForestNumber(value);
  if (number === null) return "Unavailable";
  if (number === 0) return "0";
  return Math.abs(number) < 0.0001 || Math.abs(number) >= 10000
    ? number.toExponential(4) : String(Number(number.toPrecision(6)));
}

function replicationForestFormatP(value) {
  const number = replicationForestNumber(value);
  if (number === null) return "Unavailable";
  if (number === 0) return "<1e-300";
  return number < 0.001 ? number.toExponential(3) : String(Number(number.toPrecision(4)));
}

function replicationForestSvg(tag, attributes = {}, label = "") {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (label) node.textContent = label;
  return node;
}

function replicationForestInterval(row) {
  const interval = row?.ci?.ranges?.find((item) => (
    replicationForestNumber(item?.lower) !== null && replicationForestNumber(item?.upper) !== null
  ));
  if (interval) return { lower: Number(interval.lower), upper: Number(interval.upper) };
  return null;
}

function replicationForestDomain(rows) {
  const values = [0];
  for (const row of rows) {
    const beta = replicationForestNumber(row["beta.hat"] ?? row.beta);
    const interval = replicationForestInterval(row);
    if (beta !== null) values.push(beta);
    if (interval) values.push(interval.lower, interval.upper);
  }
  let low = Math.min(...values);
  let high = Math.max(...values);
  const span = high - low || Math.max(Math.abs(low), Math.abs(high), 1);
  low -= span * 0.12;
  high += span * 0.12;
  return [low, high];
}

function replicationForestMethodOrder(rows) {
  const priority = ["ivw", "mr-apss", "bwmr", "mr-egger", "weighted median", "weighted mode"];
  return [...new Set(rows.map((row) => text(row.method)).filter(Boolean))].sort((left, right) => {
    const leftIndex = priority.indexOf(left.toLowerCase());
    const rightIndex = priority.indexOf(right.toLowerCase());
    return (leftIndex < 0 ? priority.length : leftIndex) - (rightIndex < 0 ? priority.length : rightIndex)
      || left.localeCompare(right);
  });
}

function replicationForestStudyLabel(analysis) {
  const study = analysis?.outcome_study || {};
  return [text(study.trait), text(study.study_id)].filter(Boolean).join(" · ");
}

function buildReplicationForest(snapshot, model, staticImage) {
  const host = notebookElement("div", "replication-forest");
  const status = notebookElement("p", "replication-forest-note", "Loading replication estimates…");
  status.setAttribute("role", "status");
  host.appendChild(status);

  const render = (payload) => {
    try {
      renderReplicationForest(host, payload);
      staticImage.hidden = true;
    } catch (error) {
      status.textContent = `Interactive forest unavailable: ${error.message}`;
    }
  };
  if (Array.isArray(model.payload?.estimates) && Array.isArray(model.payload?.analyses)) {
    render(model.payload);
    return host;
  }

  const path = text(model.payload?.result_record_path)
    || model.artifacts.find((artifact) => artifactBasename(artifact.path) === "replication_result_record.json")?.path;
  if (!path || !artifactBelongsToExecutionScope(path, model.group.scope)) {
    status.textContent = "Interactive forest unavailable: this execution has no saved replication result record.";
    return host;
  }
  const resource = notebookResource(snapshot, path, "json");
  const load = () => {
    if (resource?.status === "ready") render(resource.value);
    else status.textContent = `Interactive forest unavailable: ${resource?.error || "result record could not be loaded"}.`;
  };
  if (resource?.status === "loading") resource.promise.then(load);
  else load();
  return host;
}

function renderReplicationForest(host, payload) {
  const rows = (payload?.estimates || []).filter((row) => (
    replicationForestNumber(row?.["beta.hat"] ?? row?.beta) !== null && replicationForestInterval(row)
  ));
  const analyses = [...(payload?.analyses || [])].sort((left, right) => (
    Number(left.analysis_index) - Number(right.analysis_index)
  ));
  if (!rows.length || !analyses.length) throw new Error("no estimates with effect size and confidence interval were recorded");

  host.replaceChildren();
  const methods = replicationForestMethodOrder(rows);
  const panelWidth = 350;
  const labelWidth = 176;
  const top = 88;
  const rowHeight = 54;
  const plotBottom = top + methods.length * rowHeight;
  const width = labelWidth + analyses.length * panelWidth + 24;
  const height = plotBottom + 70;
  const viewport = notebookElement("div", "replication-forest-viewport");
  const svg = replicationForestSvg("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "group",
    "aria-label": "Interactive replication forest plot. Focus an estimate to inspect its effect size, confidence interval and P value.",
  });
  // Keep labels at a readable size when several cohorts share the plot.
  svg.style.minWidth = `${Math.max(760, width)}px`;
  const tooltip = notebookElement("div", "replication-forest-tooltip");
  tooltip.setAttribute("role", "tooltip");
  tooltip.hidden = true;
  viewport.appendChild(svg);
  host.append(viewport, tooltip);

  const lookup = new Map(rows.map((row) => [`${row.analysis_index}:${row.method}`, row]));
  const domains = new Map(analyses.map((analysis) => [
    analysis.analysis_index,
    replicationForestDomain(rows.filter((row) => Number(row.analysis_index) === Number(analysis.analysis_index))),
  ]));
  const plotLeft = (index) => labelWidth + index * panelWidth + 26;
  const plotRight = (index) => labelWidth + (index + 1) * panelWidth - 22;
  const scale = (index, value) => {
    const analysis = analyses[index];
    const [low, high] = domains.get(analysis.analysis_index);
    return plotLeft(index) + (value - low) / (high - low) * (plotRight(index) - plotLeft(index));
  };

  svg.appendChild(replicationForestSvg("text", { x: 8, y: top - 18, class: "replication-forest-method-head" }, "METHOD"));
  analyses.forEach((analysis, index) => {
    const center = (plotLeft(index) + plotRight(index)) / 2;
    svg.appendChild(replicationForestSvg("text", { x: center, y: 24, "text-anchor": "middle", class: "replication-forest-panel-title" }, text(analysis.name) || `Analysis ${index + 1}`));
    svg.appendChild(replicationForestSvg("text", { x: center, y: 48, "text-anchor": "middle", class: "replication-forest-study" }, replicationForestStudyLabel(analysis)));
    const study = analysis.outcome_study || {};
    const metadata = [text(study.source), study.sample_size ? `N=${Number(study.sample_size).toLocaleString()}` : "", text(study.ancestry)].filter(Boolean).join(" · ");
    svg.appendChild(replicationForestSvg("text", { x: center, y: 68, "text-anchor": "middle", class: "replication-forest-study-meta" }, metadata));
  });

  methods.forEach((method, methodIndex) => {
    const y = top + methodIndex * rowHeight + rowHeight / 2;
    if (methodIndex % 2 === 0) svg.appendChild(replicationForestSvg("rect", { x: 0, y: y - rowHeight / 2 + 2, width, height: rowHeight - 4, class: "replication-forest-stripe" }));
    svg.appendChild(replicationForestSvg("text", { x: 8, y: y + 5, class: "replication-forest-method" }, method));
  });

  analyses.forEach((analysis, index) => {
    const [low, high] = domains.get(analysis.analysis_index);
    for (let tick = 0; tick <= 4; tick += 1) {
      const value = low + (high - low) * tick / 4;
      const x = scale(index, value);
      svg.appendChild(replicationForestSvg("line", { x1: x, y1: top, x2: x, y2: plotBottom, class: "replication-forest-grid" }));
      svg.appendChild(replicationForestSvg("text", { x, y: plotBottom + 24, "text-anchor": "middle", class: "replication-forest-tick" }, replicationForestFormat(value)));
    }
    if (low <= 0 && high >= 0) {
      const zero = scale(index, 0);
      svg.appendChild(replicationForestSvg("line", { x1: zero, y1: top, x2: zero, y2: plotBottom, class: "replication-forest-zero" }));
    }
  });
  svg.appendChild(replicationForestSvg("text", { x: labelWidth + analyses.length * panelWidth / 2, y: height - 12, "text-anchor": "middle", class: "replication-forest-axis-label" }, "MR estimate (β)"));

  let active = null;
  const hide = () => {
    tooltip.hidden = true;
    active?.classList.remove("is-active");
    active = null;
  };
  analyses.forEach((analysis, analysisIndex) => {
    methods.forEach((method, methodIndex) => {
      const row = lookup.get(`${analysis.analysis_index}:${method}`);
      if (!row) return;
      const beta = Number(row["beta.hat"] ?? row.beta);
      const interval = replicationForestInterval(row);
      const y = top + methodIndex * rowHeight + rowHeight / 2;
      const lower = scale(analysisIndex, interval.lower);
      const upper = scale(analysisIndex, interval.upper);
      const point = scale(analysisIndex, beta);
      const colorClass = beta >= 0 ? "is-positive" : "is-negative";
      const mark = replicationForestSvg("g", { class: `replication-forest-estimate ${colorClass}`, tabindex: 0, role: "img" });
      const ciText = `[${replicationForestFormat(interval.lower)}, ${replicationForestFormat(interval.upper)}]`;
      mark.setAttribute("aria-label", `${text(analysis.name)}, ${method}. Effect size ${replicationForestFormat(beta)}. 95% CI ${ciText}. P value ${replicationForestFormatP(row.pval)}.`);
      mark.append(
        replicationForestSvg("line", { x1: lower, y1: y, x2: upper, y2: y, class: "replication-forest-ci" }),
        replicationForestSvg("line", { x1: lower, y1: y - 6, x2: lower, y2: y + 6, class: "replication-forest-cap" }),
        replicationForestSvg("line", { x1: upper, y1: y - 6, x2: upper, y2: y + 6, class: "replication-forest-cap" }),
        replicationForestSvg("circle", { cx: point, cy: y, r: 12, fill: "transparent" }),
        replicationForestSvg("circle", { cx: point, cy: y, r: 6, class: "replication-forest-dot" }),
      );
      svg.appendChild(mark);
      const show = (event) => {
        active?.classList.remove("is-active");
        active = mark;
        mark.classList.add("is-active");
        tooltip.replaceChildren(
          notebookElement("strong", "", `${text(analysis.name) || `Analysis ${analysisIndex + 1}`} · ${method}`),
        );
        const stats = notebookElement("dl", "replication-forest-stats");
        [
          ["Effect size", replicationForestFormat(beta)],
          ["95% CI", ciText],
          ["P value", replicationForestFormatP(row.pval)],
          ["Adjusted P", replicationForestFormatP(row.qval)],
        ].forEach(([label, value]) => stats.append(notebookElement("dt", "", label), notebookElement("dd", "", value)));
        tooltip.appendChild(stats);
        if (row.nsnp != null) tooltip.appendChild(notebookElement("p", "", `${row.nsnp} SNP${Number(row.nsnp) === 1 ? "" : "s"}`));
        tooltip.hidden = false;
        const hostBounds = host.getBoundingClientRect();
        const markBounds = mark.getBoundingClientRect();
        const left = (event?.clientX ?? markBounds.x + markBounds.width / 2) - hostBounds.x;
        const topPosition = (event?.clientY ?? markBounds.y) - hostBounds.y;
        tooltip.style.left = `${Math.max(0, Math.min(left + 12, host.clientWidth - tooltip.offsetWidth))}px`;
        tooltip.style.top = `${Math.max(0, topPosition - tooltip.offsetHeight - 12)}px`;
      };
      mark.addEventListener("pointerenter", show);
      mark.addEventListener("pointermove", show);
      mark.addEventListener("click", show);
      mark.addEventListener("focus", () => show());
      mark.addEventListener("blur", hide);
      mark.addEventListener("keydown", (event) => { if (event.key === "Escape") hide(); });
    });
  });
  svg.addEventListener("pointerleave", hide);
  svg.addEventListener("pointermove", (event) => { if (!event.target.closest(".replication-forest-estimate")) hide(); });
  viewport.addEventListener("scroll", hide);

  host.appendChild(notebookElement("p", "replication-forest-note", `${rows.length} estimates · Hover, tap or focus a point for effect size, 95% CI and P value. All estimates use the same filled marker; evidence is read from the interval and P values.`));
  host.appendChild(notebookElement("p", "replication-forest-note", "Panels use independent beta axes."));
}
