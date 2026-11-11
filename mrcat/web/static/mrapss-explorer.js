/* The PNG remains the figure; measured coordinates add SNP inspection only. */
function buildMrapssExplorer(file, snapshot, sidecar, version) {
  const figure = buildNotebookFigure(file, snapshot);
  figure.classList.add("mrapss-explorer");
  const hint = notebookElement("p", "mrapss-hint", "Loading SNP interaction data…");
  figure.appendChild(hint);
  let disposed = false, cleanup = () => {};
  figure.dispose = () => { disposed = true; cleanup(); };
  void loadJsonArtifact(snapshot, sidecar, "mr", version).then(data => {
    if (disposed) return;
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
    let zoom = 1, selected = null, active = null;
    const tooltip = notebookElement("div", "primary-scatter-tooltip mrapss-tooltip");
    tooltip.setAttribute("role", "tooltip");
    tooltip.setAttribute("aria-live", "polite");
    tooltip.hidden = true;
    const horizontal = notebookElement("span", "mrapss-highlight horizontal");
    const vertical = notebookElement("span", "mrapss-highlight vertical");
    horizontal.hidden = vertical.hidden = true;
    canvas.append(horizontal, vertical);
    const buttons = [];
    const format = value => Number.isFinite(value) ? Number(value).toPrecision(5) : "Unavailable";
    const positionTooltip = () => {
      if (active == null || disposed) return;
      const bounds = figure.getBoundingClientRect();
      const target = buttons[active].getBoundingClientRect();
      const plotBounds = viewport.getBoundingClientRect();
      const notebookBounds = els.notebookOutput.getBoundingClientRect();
      const cellBounds = figure.closest(".codeact-cell").getBoundingClientRect();
      const visibleTop = Math.max(0, notebookBounds.top, cellBounds.top);
      const visibleBottom = Math.min(innerHeight, notebookBounds.bottom, cellBounds.bottom);
      tooltip.hidden = target.right < plotBounds.left || target.left > plotBounds.right
        || target.bottom < visibleTop || target.top > visibleBottom;
      if (tooltip.hidden) return;
      const minTop = visibleTop - bounds.top + 8;
      const maxTop = visibleBottom - bounds.top - tooltip.offsetHeight - 8;
      const above = target.top - bounds.top - tooltip.offsetHeight - 12;
      const top = above >= minTop ? above : target.bottom - bounds.top + 12;
      tooltip.style.left = `${Math.max(8, Math.min(target.right - bounds.left + 12, figure.clientWidth - tooltip.offsetWidth - 8))}px`;
      tooltip.style.top = `${Math.max(minTop, Math.min(top, maxTop))}px`;
    };
    const inspect = (index, pinned = false) => {
      active = index;
      const point = index == null ? null : data.points[index];
      tooltip.replaceChildren();
      for (const button of buttons) {
        button.classList.toggle("is-selected", button.dataset.snpIndex === String(selected));
        button.setAttribute("aria-pressed", String(button.dataset.snpIndex === String(selected)));
      }
      if (!point) {
        horizontal.hidden = vertical.hidden = true;
        tooltip.hidden = true;
        return;
      }
      const heading = notebookElement("strong", "", point.snp);
      const values = notebookElement("dl", "mrapss-values");
      for (const [name, value] of [["Exposure effect", point.b_exp], ["Outcome effect", point.b_out],
        ["Exposure SE", point.se_exp], ["Outcome SE", point.se_out], ["Exposure P", point.p_exp], ["IV posterior", point.posterior]]) {
        values.append(notebookElement("dt", "", name), notebookElement("dd", "", format(value)));
      }
      tooltip.append(heading, notebookElement("span", "mrapss-pin-state", pinned ? "Pinned" : "Preview"), values);
      tooltip.hidden = false;
      positionTooltip();
      horizontal.hidden = ![point.x_low, point.x_high].every(Number.isFinite);
      vertical.hidden = ![point.y_low, point.y_high].every(Number.isFinite);
      if (!horizontal.hidden) Object.assign(horizontal.style, {left: `${point.x_low * 100}%`, top: `${point.y * 100}%`, width: `${(point.x_high - point.x_low) * 100}%`});
      if (!vertical.hidden) Object.assign(vertical.style, {left: `${point.x * 100}%`, top: `${point.y_low * 100}%`, height: `${(point.y_high - point.y_low) * 100}%`});
    };
    const restore = () => inspect(selected, selected != null);
    data.points.forEach((point, index) => {
      const button = notebookElement("button", "mrapss-snp");
      button.type = "button";
      button.dataset.snpIndex = index;
      button.setAttribute("aria-label", `Inspect SNP ${point.snp}`);
      button.setAttribute("aria-pressed", "false");
      button.style.left = `${point.x * 100}%`;
      button.style.top = `${point.y * 100}%`;
      button.addEventListener("pointerenter", () => { if (selected == null) inspect(index); });
      button.addEventListener("pointerleave", restore);
      button.addEventListener("focus", () => { if (selected == null) inspect(index); });
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
      positionTooltip();
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
    toolbar.appendChild(controls);
    viewport.before(toolbar);
    hint.replaceWith(tooltip);
    canvas.addEventListener("click", event => { if (!event.target.closest("button")) { selected = null; restore(); } });
    figure.addEventListener("keydown", event => { if (event.key === "Escape") { selected = null; restore(); } });
    // Vertical scrolling belongs to the notebook; dragging pans the enlarged PNG horizontally.
    let drag = null;
    viewport.addEventListener("pointerdown", event => {
      if (zoom === 1 || event.pointerType !== "mouse" || event.button !== 0 || event.target.closest("button")) return;
      event.preventDefault();
      drag = {x: event.clientX, left: viewport.scrollLeft};
      viewport.setPointerCapture(event.pointerId);
    });
    viewport.addEventListener("pointermove", event => {
      if (drag) viewport.scrollLeft = drag.left - event.clientX + drag.x;
    });
    viewport.addEventListener("lostpointercapture", () => { drag = null; });
    image.draggable = false;
    setZoom(1);
    restore();
    const resize = new ResizeObserver(positionTooltip);
    resize.observe(canvas);
    viewport.addEventListener("scroll", positionTooltip, {passive: true});
    els.notebookOutput.addEventListener("scroll", positionTooltip, {passive: true});
    cleanup = () => {
      resize.disconnect();
      els.notebookOutput.removeEventListener("scroll", positionTooltip);
    };
  }).catch(() => {
    if (disposed) return;
    hint.textContent = "SNP interaction data could not be loaded. The original figure is still available.";
  });
  return figure;
}
