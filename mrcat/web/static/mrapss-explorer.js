/* The PNG remains the figure; measured coordinates add SNP inspection only. */
function buildMrapssExplorer(file, snapshot, sidecar, version) {
  const figure = buildNotebookFigure(file, snapshot);
  figure.classList.add("mrapss-explorer");
  const hint = notebookElement("p", "mrapss-hint", "Loading SNP interaction data…");
  figure.appendChild(hint);
  void loadJsonArtifact(snapshot, sidecar, "mr", version).then(data => {
    if (data?.kind !== "mrapss" || !Array.isArray(data.points) || !data.points.length
        || !data.points.every(point => typeof point.snp === "string" && Number.isFinite(point.x) && Number.isFinite(point.y)
          && point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1)) {
      throw new Error("Invalid SNP coordinates");
    }
    const original = figure.querySelector(".notebook-figure-link");
    const image = original.querySelector("img");
    const viewport = notebookElement("div", "mrapss-viewport");
    viewport.tabIndex = 0;
    viewport.setAttribute("aria-label", "MR-APSS plot. Tab to SNPs; Enter pins details; Escape clears selection.");
    const canvas = notebookElement("div", "mrapss-canvas");
    canvas.appendChild(image);
    viewport.appendChild(canvas);
    original.replaceWith(viewport);
    const toolbar = notebookElement("div", "mrapss-toolbar");
    const controls = notebookElement("div", "mrapss-zoom-controls");
    const zoomLabel = notebookElement("span", "mrapss-zoom-label", "100%");
    let zoom = 1, selected = null;
    const inspector = notebookElement("div", "mrapss-inspector");
    inspector.setAttribute("role", "status");
    inspector.setAttribute("aria-live", "polite");
    const horizontal = notebookElement("span", "mrapss-highlight horizontal");
    const vertical = notebookElement("span", "mrapss-highlight vertical");
    horizontal.hidden = vertical.hidden = true;
    canvas.append(horizontal, vertical);
    const buttons = [];
    const format = value => Number.isFinite(value) ? Number(value).toPrecision(5) : "Unavailable";
    const inspect = (point, pinned = false) => {
      inspector.replaceChildren();
      for (const button of buttons) {
        button.classList.toggle("is-selected", button.dataset.snpIndex === String(selected));
        button.setAttribute("aria-pressed", String(button.dataset.snpIndex === String(selected)));
      }
      if (!point) {
        horizontal.hidden = vertical.hidden = true;
        inspector.appendChild(notebookElement("span", "", "Hover or focus a SNP to inspect it. Click to pin its details."));
        return;
      }
      const heading = notebookElement("strong", "", point.snp);
      const values = notebookElement("dl", "mrapss-values");
      for (const [name, value] of [["Exposure effect", point.b_exp], ["Outcome effect", point.b_out],
        ["Exposure SE", point.se_exp], ["Outcome SE", point.se_out], ["Exposure P", point.p_exp], ["IV posterior", point.posterior]]) {
        values.append(notebookElement("dt", "", name), notebookElement("dd", "", format(value)));
      }
      inspector.append(heading, notebookElement("span", "mrapss-pin-state", pinned ? "Pinned" : "Preview"), values);
      horizontal.hidden = ![point.x_low, point.x_high].every(Number.isFinite);
      vertical.hidden = ![point.y_low, point.y_high].every(Number.isFinite);
      if (!horizontal.hidden) Object.assign(horizontal.style, {left: `${point.x_low * 100}%`, top: `${point.y * 100}%`, width: `${(point.x_high - point.x_low) * 100}%`});
      if (!vertical.hidden) Object.assign(vertical.style, {left: `${point.x * 100}%`, top: `${point.y_low * 100}%`, height: `${(point.y_high - point.y_low) * 100}%`});
    };
    const restore = () => inspect(selected == null ? null : data.points[selected], selected != null);
    data.points.forEach((point, index) => {
      const button = notebookElement("button", "mrapss-snp");
      button.type = "button";
      button.dataset.snpIndex = index;
      button.setAttribute("aria-label", `Inspect SNP ${point.snp}`);
      button.setAttribute("aria-pressed", "false");
      button.title = point.snp;
      button.style.left = `${point.x * 100}%`;
      button.style.top = `${point.y * 100}%`;
      button.addEventListener("pointerenter", () => { if (selected == null) inspect(point); });
      button.addEventListener("pointerleave", restore);
      button.addEventListener("focus", () => { if (selected == null) inspect(point); });
      button.addEventListener("blur", restore);
      button.addEventListener("click", () => { selected = selected === index ? null : index; restore(); });
      buttons.push(button);
      canvas.appendChild(button);
    });
    const setZoom = value => {
      zoom = Math.max(1, Math.min(4, value));
      canvas.style.width = `${zoom * 100}%`;
      zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
      zoomOut.disabled = zoom === 1;
      zoomIn.disabled = zoom === 4;
      if (zoom === 1) viewport.scrollTo(0, 0);
    };
    const control = (label, action) => {
      const button = notebookElement("button", "", label);
      button.type = "button";
      button.addEventListener("click", action);
      return button;
    };
    const zoomOut = control("−", () => setZoom(zoom - .5));
    zoomOut.setAttribute("aria-label", "Zoom out MR-APSS plot");
    const zoomIn = control("+", () => setZoom(zoom + .5));
    zoomIn.setAttribute("aria-label", "Zoom in MR-APSS plot");
    const reset = control("Reset view", () => { selected = null; setZoom(1); restore(); });
    controls.append(zoomOut, zoomLabel, zoomIn, reset);
    toolbar.append(notebookElement("span", "", `${data.points.length} SNPs · Click a point to inspect`), controls);
    viewport.before(toolbar);
    hint.replaceWith(inspector);
    canvas.addEventListener("click", event => { if (!event.target.closest("button")) { selected = null; restore(); } });
    figure.addEventListener("keydown", event => { if (event.key === "Escape") { selected = null; restore(); } });
    // Native touch scrolling and mouse dragging both pan the enlarged PNG.
    let drag = null;
    viewport.addEventListener("pointerdown", event => {
      if (zoom === 1 || event.pointerType !== "mouse" || event.button !== 0 || event.target.closest("button")) return;
      event.preventDefault();
      drag = {x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop};
      viewport.setPointerCapture(event.pointerId);
    });
    viewport.addEventListener("pointermove", event => {
      if (drag) viewport.scrollTo(drag.left - event.clientX + drag.x, drag.top - event.clientY + drag.y);
    });
    viewport.addEventListener("lostpointercapture", () => { drag = null; });
    image.draggable = false;
    setZoom(1);
    restore();
  }).catch(() => {
    hint.textContent = "SNP interaction data could not be loaded. The original figure is still available.";
  });
  return figure;
}
