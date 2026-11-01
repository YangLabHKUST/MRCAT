/* QC views read point sidecars from the same execution as the saved figures. */
const qcKinds = {
  gwas_qc_post_format_manhattan: "Manhattan",
  gwas_qc_qq_plot: "QQ",
  gwas_qc_signal_retention_curve: "Signal retention",
};
let qcPlotlyPromise;

function qcPlotKind(path) {
  const name = artifactBasename(path || "").replace(/\.png$/i, "");
  return Object.hasOwn(qcKinds, name) ? name : "";
}

function loadQcPlotly() {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  if (!qcPlotlyPromise) qcPlotlyPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/static/vendor/plotly-gl2d-3.1.0.min.js";
    script.onload = () => resolve(window.Plotly);
    script.onerror = () => { script.remove(); qcPlotlyPromise = null; reject(new Error("Chart library could not be loaded")); };
    document.head.appendChild(script);
  });
  return qcPlotlyPromise;
}

function disposeQcExplorers(root) {
  root?.querySelectorAll(".qc-explorer").forEach((host) => host.dispose?.());
}

function qcNumber(value) {
  if (value == null || !Number.isFinite(Number(value))) return "Unavailable";
  const number = Number(value);
  if (Number.isSafeInteger(number)) return number.toLocaleString("en-US");
  return number === 0 ? "0" : Math.abs(number) < 0.001 || Math.abs(number) >= 1e6
    ? number.toExponential(4) : Number(number.toPrecision(6)).toLocaleString("en-US");
}

function buildQcExplorer(plots, snapshot) {
  const host = notebookElement("section", "qc-explorer");
  host.setAttribute("aria-label", "Interactive GWAS QC figures");
  const heading = notebookElement("div", "qc-heading");
  heading.append(notebookElement("strong", "", "Explore QC"), notebookElement("span", "qc-badge", "View only"));
  const tabs = notebookElement("div", "qc-tabs");
  tabs.setAttribute("role", "group");
  tabs.setAttribute("aria-label", "QC figure type");
  const toolbar = notebookElement("form", "qc-toolbar");
  const chromosome = notebookElement("select");
  chromosome.setAttribute("aria-label", "Chromosome");
  const search = notebookElement("input");
  search.type = "search";
  search.placeholder = "Find plotted rsID";
  search.setAttribute("aria-label", "Find plotted SNP by rsID");
  const find = notebookElement("button", "", "Find SNP");
  find.type = "submit";
  const reset = notebookElement("button", "", "Reset view");
  reset.type = "button";
  toolbar.append(chromosome, search, find, reset);
  const status = notebookElement("p", "qc-status");
  status.setAttribute("role", "status");
  const chart = notebookElement("div", "qc-chart");
  chart.setAttribute("role", "img");
  const details = notebookElement("div", "qc-point-details");
  details.setAttribute("aria-live", "polite");
  const note = notebookElement("p", "qc-note");
  const originals = notebookElement("details", "qc-original");
  originals.appendChild(notebookElement("summary", "", "Saved figure and explanation"));
  const originalBody = notebookElement("div");
  originals.appendChild(originalBody);
  const downloads = notebookElement("div", "qc-downloads");
  host.append(heading, tabs, toolbar, status, chart, details, note, downloads, originals);
  let active, data, visible = [], selected = null, disposed = false, revision = 0, loaded = false;
  let pending = Promise.resolve();
  const cache = new Map();
  const available = Object.keys(qcKinds).flatMap((kind) => {
    const plot = plots.find((item) => qcPlotKind(item.path) === kind);
    return plot ? [{ kind, plot }] : [];
  });
  const buttons = new Map();
  const chromosomeTicks = () => {
    const ticks = data.chromosomes.filter((item) => !chromosome.value || item.label === chromosome.value);
    const width = chart.clientWidth || host.clientWidth || 400;
    const step = Math.max(1, Math.ceil(ticks.length / Math.max(2, Math.floor((width - 80) / 28))));
    return ticks.filter((_, index) => index % step === 0);
  };
  for (const item of available) {
    const button = notebookElement("button", "", qcKinds[item.kind]);
    button.type = "button";
    button.addEventListener("click", () => activate(item));
    tabs.appendChild(button);
    buttons.set(item.kind, button);
  }
  const inspect = (point, pinned = false) => {
    if (!point) return;
    details.replaceChildren();
    details.appendChild(notebookElement("strong", "", data.kind === "manhattan" ? point.snp : data.kind === "qq" ? "QQ quantile" : "Signal threshold"));
    const values = data.kind === "manhattan"
      ? [["Chromosome", point.chr], ["Position (reference BP)", point.bp], ["P", point.p], ["−log10(P)", point.neglogp]]
      : data.kind === "qq"
        ? [["Expected −log10(P)", point.x], ["Observed −log10(P)", point.y]]
        : [["Cutoff −log10(P) ≥", point.threshold], ["Retained SNPs", point.n_retained], ...(data.mode === "retention_fraction" ? [["Raw SNPs", point.n_raw], ["Retained fraction", point.value]] : [])];
    const list = notebookElement("dl");
    for (const [label, value] of values) {
      const display = label === "P" && value != null ? String(value) : qcNumber(value);
      list.append(notebookElement("dt", "", label), notebookElement("dd", "", display));
    }
    details.appendChild(list);
    if (pinned) details.appendChild(notebookElement("span", "qc-note", "Pinned · click another point or reset to clear"));
  };
  const pointFromEvent = (event) => {
    const point = event.points?.[0];
    return point && point.curveNumber === 0 ? visible[point.pointIndex ?? point.pointNumber] : null;
  };
  const plot = () => {
    const token = revision;
    // Serialize Plotly mutations when users switch tabs or filters quickly.
    pending = pending.catch(() => {}).then(async () => {
      if (disposed || token !== revision || !data) return;
      const Plotly = await loadQcPlotly();
      if (disposed || token !== revision) return;
      const manhattan = data.kind === "manhattan", qq = data.kind === "qq";
      visible = manhattan ? data.points.filter((p) => !chromosome.value || String(p.chr) === chromosome.value)
        : qq ? data.expected.map((x, i) => ({ x, y: data.observed[i] })) : data.points;
      const manhattanX = (point) => chromosome.value ? point.bp / 1e6 : point.x;
      const xs = visible.map((p) => manhattan ? manhattanX(p) : qq ? p.x : p.threshold);
      const ys = visible.map((p) => manhattan ? p.neglogp : qq ? p.y : p.value);
      const maxX = xs.reduce((a, b) => Math.max(a, b), 1), maxY = ys.reduce((a, b) => Math.max(a, b), 1);
      const trace = {
        type: "scattergl", mode: manhattan || qq ? "markers" : "lines+markers", x: xs, y: ys,
        marker: { size: qq ? 3 : 5, color: manhattan ? visible.map((p) => data.colors[String(p.chr)] || "#356a91") : "#356a91", opacity: qq ? 0.5 : 0.8 },
        line: { color: "#356a91", width: 2 },
        // Point details use textContent below so dataset strings never become HTML.
        hoverinfo: "none",
      };
      const layout = {
        height: 420, autosize: true, margin: { l: 96, r: 24, t: 28, b: 92 },
        font: { family: "system-ui, sans-serif", size: 18, color: "#42546b" },
        paper_bgcolor: "#ffffff", plot_bgcolor: "#ffffff", showlegend: false, dragmode: "zoom",
        xaxis: { title: { text: manhattan ? "Chromosome" : qq ? "Expected −log10(P)" : "Association cutoff: −log10(P) ≥ x", font: { size: 18 } }, zeroline: false, showgrid: false, automargin: true },
        yaxis: { title: { text: manhattan ? "−log10(P)" : qq ? "Observed −log10(P)" : data.mode === "retention_fraction" ? "Retained fraction" : "Formatted SNP count", font: { size: 18 } }, gridcolor: "#edf1f5", zeroline: false, rangemode: "tozero", automargin: true },
        shapes: [],
      };
      if (manhattan) {
        if (chromosome.value) {
          layout.xaxis.title.text = `Position on Chr ${chromosome.value} (Mb, reference)`;
        } else {
          const ticks = chromosomeTicks();
          Object.assign(layout.xaxis, { tickmode: "array", tickvals: ticks.map((item) => item.x), ticktext: ticks.map((item) => item.label), tickangle: 0, tickfont: { size: 16 } });
        }
        layout.shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: data.significance, y1: data.significance, line: { color: "#d82435", width: 1, dash: "dash" } });
        layout.yaxis.range = [0, Math.max(maxY, data.significance) * 1.12];
      } else if (qq) {
        layout.shapes.push({ type: "line", x0: 0, x1: maxX * 1.05, y0: 0, y1: maxX * 1.05, line: { color: "#68788b", width: 1, dash: "dash" } });
        layout.xaxis.range = [0, maxX * 1.05];
        layout.yaxis.range = [0, Math.max(maxY, maxX * 1.05) * 1.05];
      } else {
        layout.shapes.push({ type: "line", yref: "paper", y0: 0, y1: 1, x0: data.significance, x1: data.significance, line: { color: "#d82435", width: 1, dash: "dash" } });
        if (data.mode !== "retention_fraction") layout.yaxis.type = "log";
      }
      const traces = [trace];
      if (manhattan) {
        const top = visible.filter((p) => data.highlighted.includes(p.snp));
        traces.push({ type: "scattergl", mode: "markers", x: top.map(manhattanX), y: top.map((p) => p.neglogp), marker: { size: 9, color: "#d82435", symbol: "triangle-up" }, hoverinfo: "skip" });
        if (selected) traces.push({ type: "scattergl", mode: "markers", x: [manhattanX(selected)], y: [selected.neglogp], marker: { size: 15, color: "#122c43", symbol: "circle-open" }, hoverinfo: "skip" });
      }
      await Plotly.react(chart, traces, layout, { displaylogo: false, responsive: false, scrollZoom: false, modeBarButtonsToRemove: ["select2d", "lasso2d", "toImage", "hoverClosestCartesian", "hoverCompareCartesian"], showTips: false });
      if (disposed || token !== revision) { Plotly.purge(chart); return; }
      chart.removeAllListeners("plotly_hover");
      chart.removeAllListeners("plotly_click");
      chart.on("plotly_hover", (event) => { if (!selected) inspect(pointFromEvent(event)); });
      chart.on("plotly_click", (event) => { selected = pointFromEvent(event); inspect(selected, true); });
      chart.setAttribute("aria-label", `${qcKinds[active.kind]} plot; ${visible.length.toLocaleString()} plotted points. Drag to zoom; use Reset view to restore.`);
      status.textContent = `${visible.length.toLocaleString()} plotted ${qq ? "quantiles" : manhattan ? "SNPs" : "thresholds"}${qq && data.lambda_gc != null ? ` · λGC ${qcNumber(data.lambda_gc)}` : ""} · Drag to zoom · Click to pin details`;
      loaded = true;
    }).catch((error) => {
      if (!disposed && token === revision) {
        status.textContent = `Interactive view unavailable: ${error.message}. The saved figure is below.`;
        originals.open = true;
      }
    });
    return pending;
  };
  async function activate(item) {
    const token = ++revision;
    active = item; data = null; selected = null; loaded = false;
    if (window.Plotly && chart.data) window.Plotly.purge(chart);
    chart.replaceChildren(); details.replaceChildren(); note.textContent = "";
    for (const [kind, button] of buttons) button.setAttribute("aria-pressed", String(kind === item.kind));
    toolbar.hidden = true;
    status.textContent = "Loading saved plotting data…";
    originalBody.replaceChildren(buildNotebookFigure(item.plot, snapshot));
    originals.open = false;
    downloads.replaceChildren();
    const path = item.plot.path.replace(/\.png$/i, ".plot.json");
    try {
      if (!cache.has(path)) cache.set(path, fetch(artifactRawUrl(snapshot, path), { cache: "no-store" }).then(async (response) => {
        if (!response.ok) throw new Error(response.status === 404 ? "this figure has no saved point data" : `data request failed (HTTP ${response.status})`);
        return response.json();
      }));
      const value = await cache.get(path);
      if (disposed || token !== revision) return;
      const expectedKind = { gwas_qc_post_format_manhattan: "manhattan", gwas_qc_qq_plot: "qq", gwas_qc_signal_retention_curve: "retention" }[item.kind];
      if (value.version !== 1 || value.kind !== expectedKind) throw new Error("unrecognized QC plot data");
      data = value;
      toolbar.hidden = false;
      chromosome.hidden = search.hidden = find.hidden = data.kind !== "manhattan";
      chromosome.replaceChildren(new Option("All chromosomes", ""));
      for (const item of data.chromosomes || []) chromosome.add(new Option(`Chr ${item.label}`, item.label));
      search.value = "";
      note.textContent = data.note || "";
      downloads.appendChild(buildExternalLink(artifactRawUrl(snapshot, path), "Open plot data ↗"));
      await plot();
    } catch (error) {
      if (disposed || token !== revision) return;
      cache.delete(path);
      status.textContent = `Interactive view unavailable: ${error.message}.`;
      originals.open = true;
    }
  }
  toolbar.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!data || data.kind !== "manhattan") return;
    const query = search.value.trim().toLowerCase();
    const point = data.points.find((item) => item.snp.toLowerCase() === query);
    if (!point) { status.textContent = "SNP not found in this plotted subset. This does not indicate absence from the full GWAS."; return; }
    selected = point; chromosome.value = String(point.chr);
    await plot();
    if (!disposed && selected === point) { inspect(point, true); status.textContent = `Located ${point.snp} · Chr ${point.chr} · highlighted in the plot`; }
  });
  chromosome.addEventListener("change", () => { selected = null; details.replaceChildren(); plot(); });
  reset.addEventListener("click", () => { selected = null; search.value = ""; chromosome.value = ""; details.replaceChildren(); plot(); });
  let chartWidth = 0;
  const resize = new ResizeObserver(() => {
    if (!loaded || !chart.clientWidth || !chart.data || chartWidth === chart.clientWidth) return;
    chartWidth = chart.clientWidth;
    window.Plotly.Plots.resize(chart);
    if (data.kind === "manhattan" && !chromosome.value) {
      const ticks = chromosomeTicks();
      window.Plotly.relayout(chart, { "xaxis.tickvals": ticks.map((item) => item.x), "xaxis.ticktext": ticks.map((item) => item.label) });
    }
  });
  resize.observe(chart);
  host.dispose = () => { disposed = true; revision++; resize.disconnect(); if (chart.data) window.Plotly?.purge(chart); };
  activate(available[0]);
  return host;
}
