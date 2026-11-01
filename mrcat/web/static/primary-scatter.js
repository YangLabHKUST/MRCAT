/* Interactive view of the exact instrument table saved by mr-primary. */
function primaryScatterNumber(value) {
  if (value == null || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function parsePrimaryScatterTable(source) {
  const lines = source.replace(/^\uFEFF/, "").trim().split(/\r?\n/);
  const headers = lines.shift().split("\t");
  const columns = ["SNP", "b.exp", "b.out", "se.exp", "se.out"].map((name) => headers.indexOf(name));
  if (columns.includes(-1)) throw new Error("The saved instrument table is missing SNP, beta or SE columns.");
  let omitted = 0;
  const points = lines.filter((line) => line.trim()).flatMap((line, index) => {
    const values = line.split("\t");
    const [snp, bx, by, sx, sy] = columns.map((column) => values[column]);
    const betaExposure = primaryScatterNumber(bx);
    const betaOutcome = primaryScatterNumber(by);
    if (!snp || betaExposure === null || betaOutcome === null) {
      omitted += 1;
      return [];
    }
    const seExposure = primaryScatterNumber(sx);
    const seOutcome = primaryScatterNumber(sy);
    const direction = betaExposure < 0 ? -1 : 1;
    return [{
      index, snp, betaExposure, betaOutcome,
      seExposure: seExposure !== null && seExposure >= 0 ? seExposure : null,
      seOutcome: seOutcome !== null && seOutcome >= 0 ? seOutcome : null,
      x: direction * betaExposure, y: direction * betaOutcome, flipped: direction < 0,
    }];
  });
  if (!points.length) throw new Error("No SNPs with recorded exposure and outcome betas are available.");
  return { points, omitted };
}

function primaryScatterFormat(value) {
  if (value === null || !Number.isFinite(value)) return "Unavailable";
  if (value === 0) return "0";
  return Math.abs(value) < 0.0001 || Math.abs(value) >= 10000
    ? value.toExponential(4) : String(Number(value.toPrecision(6)));
}

function primaryScatterCI(beta, se) {
  return se === null ? "Unavailable (SE not recorded)"
    : `[${primaryScatterFormat(beta - 1.96 * se)}, ${primaryScatterFormat(beta + 1.96 * se)}]`;
}

function primaryScatterErfc(value) {
  const x = Math.abs(value);
  const t = 1 / (1 + 0.5 * x);
  const tail = t * Math.exp(
    -x * x - 1.26551223
    + t * (1.00002368
      + t * (0.37409196
        + t * (0.09678418
          + t * (-0.18628806
            + t * (0.27886807
              + t * (-1.13520398
                + t * (1.48851587
                  + t * (-0.82215223 + t * 0.17087277))))))))
  );
  return value >= 0 ? tail : 2 - tail;
}

function primaryScatterWald(point) {
  if (!Number.isFinite(point.betaExposure) || point.betaExposure === 0 || !Number.isFinite(point.betaOutcome)) {
    return { beta: null, se: null, p: null };
  }
  const beta = point.betaOutcome / point.betaExposure;
  const se = Number.isFinite(point.seOutcome) && point.seOutcome >= 0
    ? point.seOutcome / Math.abs(point.betaExposure)
    : null;
  const z = se !== null && se > 0 ? beta / se : null;
  const p = z === null ? null : Math.max(0, Math.min(1, primaryScatterErfc(Math.abs(z) / Math.SQRT2)));
  return { beta, se, p };
}

function primaryScatterFormatP(value) {
  if (value === null || !Number.isFinite(value)) return "Unavailable";
  if (value === 0) return "<1e-300";
  return value < 0.001 ? value.toExponential(3) : String(Number(value.toPrecision(4)));
}

function primaryScatterSvg(tag, attributes = {}, label = "") {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (label) node.textContent = label;
  return node;
}

function buildPrimaryScatter(snapshot, model, staticImage) {
  const host = notebookElement("div", "primary-scatter");
  const status = notebookElement("p", "primary-scatter-note", "Loading SNP details…");
  status.setAttribute("role", "status");
  host.appendChild(status);
  const path = text(model.payload?.selected_mrdat_path)
    || model.artifacts.find((artifact) => artifactBasename(artifact.path) === "selected_mrdat.tsv")?.path;
  if (!path || !model.artifacts?.some(artifact => artifact.path === path)) {
    status.textContent = "SNP hover is unavailable: this execution has no saved instrument table.";
    return host;
  }
  // Read the complete selected table, never the truncated spreadsheet preview.
  const resource = notebookResource(snapshot, path, "text");
  const render = () => {
    if (resource?.status !== "ready") {
      status.textContent = `SNP hover unavailable: ${resource?.error || "instrument table could not be loaded"}.`;
      return;
    }
    try {
      const data = parsePrimaryScatterTable(resource.value);
      renderPrimaryScatter(host, data, model.payload);
      staticImage.hidden = true;
    } catch (error) {
      status.textContent = `SNP hover unavailable: ${error.message}`;
    }
  };
  if (resource?.status === "loading") resource.promise.then(render);
  else render();
  return host;
}

function renderPrimaryScatter(host, { points, omitted }, payload) {
  host.replaceChildren();
  const legend = notebookElement("div", "primary-scatter-legend");
  const viewport = notebookElement("div", "primary-scatter-viewport");
  const svg = primaryScatterSvg("svg", { viewBox: "0 0 640 440", role: "group", "aria-label": "Primary MR scatter plot. Focus a SNP to inspect its Wald ratio and harmonized associations." });
  const tooltip = notebookElement("div", "primary-scatter-tooltip");
  tooltip.setAttribute("role", "tooltip");
  tooltip.hidden = true;
  const note = notebookElement("p", "primary-scatter-note",
    `${points.length} SNPs · Hover, tap or focus a point for its Wald ratio, 95% CI and harmonized associations.`);
  const scaleNote = notebookElement("p", "primary-scatter-note",
    "Points are displayed using the exposure-increasing allele. This changes only the plotted coordinates; the harmonized analysis values and Wald ratio remain unchanged. Error bars: ±1 SE. Wald 95% CI uses the first-order SE = outcome SE / |exposure beta|.");
  if (omitted) scaleNote.append(` ${omitted} row(s) lack usable SNP identifiers or betas and cannot be plotted.`);
  host.append(legend, viewport, tooltip, note, scaleNote);
  viewport.appendChild(svg);

  const bounds = { left: 112, right: 614, top: 22, bottom: 374 };
  let xmin = 0, xmax = 0, ymin = 0, ymax = 0;
  for (const point of points) {
    xmin = Math.min(xmin, point.x - (point.seExposure || 0));
    xmax = Math.max(xmax, point.x + (point.seExposure || 0));
    ymin = Math.min(ymin, point.y - (point.seOutcome || 0));
    ymax = Math.max(ymax, point.y + (point.seOutcome || 0));
  }
  const xpad = (xmax - xmin || 0.1) * 0.06;
  const ypad = (ymax - ymin || 0.1) * 0.08;
  xmin -= xpad; xmax += xpad; ymin -= ypad; ymax += ypad;
  const x = (value) => bounds.left + (value - xmin) / (xmax - xmin) * (bounds.right - bounds.left);
  const y = (value) => bounds.bottom - (value - ymin) / (ymax - ymin) * (bounds.bottom - bounds.top);
  const line = (parent, x1, y1, x2, y2, attributes = {}) => parent.appendChild(primaryScatterSvg("line", { x1, y1, x2, y2, ...attributes }));

  for (let tick = 0; tick <= 4; tick += 1) {
    const xv = xmin + (xmax - xmin) * tick / 4;
    const yv = ymin + (ymax - ymin) * tick / 4;
    line(svg, x(xv), bounds.top, x(xv), bounds.bottom, { class: "primary-scatter-grid" });
    line(svg, bounds.left, y(yv), bounds.right, y(yv), { class: "primary-scatter-grid" });
    const tickLabel = (value) => value === 0 ? "0" : Math.abs(value) < 0.001 ? value.toExponential(1) : String(Number(value.toPrecision(3)));
    svg.appendChild(primaryScatterSvg("text", { x: x(xv), y: 395, "text-anchor": "middle", class: "primary-scatter-tick primary-scatter-x-tick" }, tickLabel(xv)));
    svg.appendChild(primaryScatterSvg("text", { x: bounds.left - 12, y: y(yv) + 4, "text-anchor": "end", class: "primary-scatter-tick primary-scatter-y-tick" }, tickLabel(yv)));
  }
  line(svg, bounds.left, y(0), bounds.right, y(0), { class: "primary-scatter-zero" });
  svg.appendChild(primaryScatterSvg("path", { d: `M${bounds.left} ${bounds.top}V${bounds.bottom}H${bounds.right}`, class: "primary-scatter-axis" }));
  svg.appendChild(primaryScatterSvg("text", { x: (bounds.left + bounds.right) / 2, y: 428, "text-anchor": "middle", class: "primary-scatter-axis-label primary-scatter-x-axis-label" }, "SNP effect on exposure"));
  svg.appendChild(primaryScatterSvg("text", { transform: "translate(18 198) rotate(-90)", "text-anchor": "middle", class: "primary-scatter-axis-label primary-scatter-y-axis-label" }, "SNP effect on outcome"));
  const marks = primaryScatterSvg("svg", { x: bounds.left, y: bounds.top, width: bounds.right - bounds.left, height: bounds.bottom - bounds.top, viewBox: `${bounds.left} ${bounds.top} ${bounds.right - bounds.left} ${bounds.bottom - bounds.top}` });
  svg.appendChild(marks);

  const colors = { IVW: "#0072B2", "MR-Egger": "#D55E00", "Weighted median": "#009E73", "Weighted mode": "#7A5195" };
  for (const method of payload?.methods || []) {
    const beta = primaryScatterNumber(method["beta.hat"] ?? method.beta);
    if (beta === null) continue;
    let intercept = 0;
    if (["MR-Egger", "MR Egger"].includes(method.method)) {
      // The saved TwoSampleMR plot uses the weighted Egger intercept after orientation.
      const valid = points.filter((point) => point.seOutcome > 0);
      if (valid.length !== points.length) continue;
      const weightSum = valid.reduce((sum, point) => sum + 1 / point.seOutcome ** 2, 0);
      intercept = valid.reduce((sum, point) => sum + (point.y - beta * point.x) / point.seOutcome ** 2, 0) / weightSum;
      if (!Number.isFinite(intercept)) continue;
    }
    const color = colors[method.method === "MR Egger" ? "MR-Egger" : method.method] || "#596579";
    line(marks, x(xmin), y(intercept + beta * xmin), x(xmax), y(intercept + beta * xmax), { stroke: color, "stroke-width": 2 });
    const label = notebookElement("span", "", method.method);
    label.style.setProperty("--method-color", color);
    legend.appendChild(label);
  }
  for (const point of points) {
    const errorBars = primaryScatterSvg("g", { class: "primary-scatter-error" });
    if (point.seExposure !== null) line(errorBars, x(point.x - point.seExposure), y(point.y), x(point.x + point.seExposure), y(point.y));
    if (point.seOutcome !== null) line(errorBars, x(point.x), y(point.y - point.seOutcome), x(point.x), y(point.y + point.seOutcome));
    marks.appendChild(errorBars);
  }

  let active = null;
  const hide = () => {
    tooltip.hidden = true;
    active?.classList.remove("is-active");
    active = null;
  };
  points.forEach((point) => {
    const node = primaryScatterSvg("g", { class: "primary-scatter-point", tabindex: 0, role: "img", "data-snp": point.snp });
    const wald = primaryScatterWald(point);
    const description = `${point.snp}. Wald ratio ${primaryScatterFormat(wald.beta)}, 95% CI ${primaryScatterCI(wald.beta, wald.se)}, P value ${primaryScatterFormatP(wald.p)}. Exposure beta ${primaryScatterFormat(point.betaExposure)}. Outcome beta ${primaryScatterFormat(point.betaOutcome)}.`;
    node.setAttribute("aria-label", description);
    node.appendChild(primaryScatterSvg("circle", { cx: x(point.x), cy: y(point.y), r: 8, fill: "transparent" }));
    node.appendChild(primaryScatterSvg("circle", { cx: x(point.x), cy: y(point.y), r: 3.3, class: "primary-scatter-dot" }));
    marks.appendChild(node);
    const show = (event) => {
      if (active !== node) {
        active?.classList.remove("is-active");
        active = node;
        node.classList.add("is-active");
        tooltip.replaceChildren(notebookElement("strong", "", `${/^rs\d+$/i.test(point.snp) ? "rsID" : "SNP"}: ${point.snp}`));
        if (!/^rs\d+$/i.test(point.snp)) tooltip.appendChild(notebookElement("p", "", "An rsID was not recorded for this SNP."));
        const waldResult = notebookElement("section", "primary-scatter-wald");
        waldResult.appendChild(notebookElement("span", "primary-scatter-wald-label", "Single-SNP MR estimate"));
        waldResult.appendChild(notebookElement("strong", "primary-scatter-wald-value", `Wald ratio ${primaryScatterFormat(wald.beta)}`));
        const waldStats = notebookElement("dl", "primary-scatter-wald-stats");
        for (const [label, value] of [
          ["95% CI", primaryScatterCI(wald.beta, wald.se)],
          ["P value", primaryScatterFormatP(wald.p)],
        ]) {
          waldStats.append(
            notebookElement("dt", "", label),
            notebookElement("dd", "", value),
          );
        }
        waldResult.appendChild(waldStats);
        tooltip.appendChild(waldResult);
        const table = notebookElement("table");
        const caption = document.createElement("caption");
        caption.textContent = "Harmonized analysis associations";
        table.appendChild(caption);
        const head = notebookElement("tr");
        ["Trait", "Beta", "SE", "95% CI"].forEach((label) => head.appendChild(notebookElement("th", "", label)));
        table.appendChild(head);
        for (const [trait, beta, se] of [["Exposure", point.betaExposure, point.seExposure], ["Outcome", point.betaOutcome, point.seOutcome]]) {
          const row = notebookElement("tr");
          [trait, primaryScatterFormat(beta), primaryScatterFormat(se), primaryScatterCI(beta, se)].forEach((label) => row.appendChild(notebookElement("td", "", label)));
          table.appendChild(row);
        }
        tooltip.appendChild(table);
        if (point.flipped) tooltip.appendChild(notebookElement("p", "primary-scatter-orientation-note", "Display-only reorientation: both plotted betas were multiplied by −1 to show the exposure-increasing allele. The harmonized values above and the Wald ratio are unchanged."));
      }
      tooltip.hidden = false;
      const hostBounds = host.getBoundingClientRect();
      const pointBounds = node.getBoundingClientRect();
      const left = (event?.clientX ?? pointBounds.x + pointBounds.width / 2) - hostBounds.x;
      const top = (event?.clientY ?? pointBounds.y) - hostBounds.y;
      tooltip.style.left = `${Math.max(0, Math.min(left + 12, host.clientWidth - tooltip.offsetWidth))}px`;
      tooltip.style.top = `${Math.max(0, top - tooltip.offsetHeight - 12)}px`;
    };
    node.addEventListener("pointerenter", show);
    node.addEventListener("pointermove", show);
    node.addEventListener("click", show);
    node.addEventListener("focus", () => show());
    node.addEventListener("blur", hide);
    node.addEventListener("keydown", (event) => { if (event.key === "Escape") hide(); });
  });
  svg.addEventListener("pointerleave", hide);
  svg.addEventListener("pointermove", (event) => { if (!event.target.closest(".primary-scatter-point")) hide(); });
  viewport.addEventListener("scroll", hide);
}
