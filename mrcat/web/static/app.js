const state = {
  sessions: [],
  currentSessionId: null,
  snapshot: null,
  example: null,
  eventSource: null,
  activityConnection: "connecting",
  expandedSearchReportSections: new Set(),
  jsonArtifactCache: new Map(),
  tableArtifactCache: new Map(),
  busy: false,
  expandedDataSearchTargets: new Set(),
  dataSearchSourceFilters: new Map(),
  scanSelection: {},
  studyMethodOptions: [],
  studySourceOptions: [],
  sessionsSidebarCollapsed: false,
  studySetupCollapsed: true,
  studySetupDraft: {
    exposures: [{ name: "", file: null, fileRef: "" }],
    outcomes: [{ name: "", file: null, fileRef: "" }],
    analysisRequest: "",
    sources: [],
    methods: [],
    dirty: false,
  },
  pendingUserMessage: null,
};

const SESSION_REFRESH_INTERVAL_MS = 60000;
const SESSION_STATUS_STORAGE_KEY = "mrcat.showSessionStatus";
const DATA_SEARCH_PREVIEW_LIMIT = 3;

const SOURCE_REGISTRY = {
  opengwas: {
    label: "OpenGWAS",
    icon: "/static/icons/source-opengwas.ico",
    url: "https://opengwas.io/",
    description: "Large harmonized GWAS collection with dataset and API access.",
    aliases: ["open gwas", "open-gwas"],
  },
  gwas_catalog: {
    label: "GWAS Catalog",
    icon: "/static/icons/source-gwas-catalog.ico",
    url: "https://www.ebi.ac.uk/gwas/",
    description: "Curated NHGRI-EBI studies and public summary statistics.",
    aliases: ["gwas catalog", "gwas-catalog"],
  },
  finngen: {
    label: "FinnGen",
    icon: "/static/icons/source-finngen.ico",
    url: "https://www.finngen.fi/en",
    description: "Finnish biobank GWAS results and downloadable releases.",
    aliases: ["finn gen", "finn-gen"],
  },
  pan_ukb: {
    label: "Pan-UKB",
    icon: "/static/icons/source-pan-ukb.ico",
    url: "https://pan.ukbb.broadinstitute.org/",
    description: "Pan-ancestry UK Biobank GWAS summary statistics.",
    aliases: ["pan ukb", "pan-ukb", "pan ukbb", "pan-ukbb"],
  },
};

const SOURCE_ORDER = Object.keys(SOURCE_REGISTRY);

const UI_ICON_ASSETS = {
  search: "/static/icons/skill-search.svg",
  evidence: "/static/icons/skill-evidence-report.svg",
  supporting: "/static/icons/skill-effect-estimates.svg",
  database: "/static/icons/skill-search.svg",
  select: "/static/icons/skill-search.svg",
  check: "/static/icons/skill-check.svg",
  warning: "/static/icons/tabler-alert-triangle.svg",
  workflow: "/static/icons/skill-workflow.svg",
  references: "/static/icons/tabler-link.svg",
  download: "/static/icons/tabler-file-download.svg",
  qc: "/static/icons/skill-quality-data.svg",
  pair: "/static/icons/skill-harmonized-instruments.svg",
  prepare: "/static/icons/skill-harmonized-instruments.svg",
  analysis: "/static/icons/skill-effect-estimates.svg",
  sensitivity: "/static/icons/skill-sensitivity.svg",
  comparison: "/static/icons/skill-method-comparison.svg",
  "post-analysis": "/static/icons/skill-method-comparison.svg",
  report: "/static/icons/skill-evidence-report.svg",
};

const UI_ICON_GLYPHS = {
  website: "◎",
};

const AGENT_ICON_ASSETS = {
  manager: "/static/icons/agent-manager.png",
  search: "/static/icons/agent-search.png",
  mr: "/static/icons/agent-mr.png",
  report: "/static/icons/agent-report.png",
};

const STUDY_METHOD_ALIASES = {
  primary: "mr-primary",
  mr_primary: "mr-primary",
  mrapss: "mr-apss",
  mr_apss: "mr-apss",
  bwmr: "mr-bwmr",
  mr_bwmr: "mr-bwmr",
  divw: "mr-divw",
  mr_divw: "mr-divw",
  raps: "mr-raps",
  mr_raps: "mr-raps",
  presso: "mr-presso",
  mr_presso: "mr-presso",
  mrmix: "mr-mrmix",
  mr_mrmix: "mr-mrmix",
  cml: "mr-cml-ma",
  cml_ma: "mr-cml-ma",
  mr_cml_ma: "mr-cml-ma",
  conmix: "mr-conmix",
  mr_conmix: "mr-conmix",
  lasso: "mr-lasso",
  mr_lasso: "mr-lasso",
  robust: "mr-robust",
  mr_robust: "mr-robust",
  cause: "mr-cause",
  mr_cause: "mr-cause",
};

const STUDY_METHOD_PURPOSES = {
  "mr-primary": "Primary analysis for full local-data workflows; reports IVW, MR-Egger, weighted median, and weighted mode estimates.",
  "mr-bwmr": "Designed to account for SNP-exposure uncertainty and balanced horizontal pleiotropy while adaptively downweighting a small number of outlying instruments.",
  "mr-apss": "Designed for weak or moderately associated instruments when sample structure, sample overlap, and pleiotropy may bias conventional MR.",
  "mr-cml-ma": "Designed for settings where several instruments may be invalid; uses constrained likelihood and model averaging to handle invalid-IV configurations.",
  "mr-conmix": "Designed for invalid instruments when valid instruments are expected to form the largest cluster, while allowing multiple plausible ratio-estimate modes.",
  "mr-divw": "Designed to reduce weak-instrument and selection bias in IVW when many instruments are selected from noisy exposure associations.",
  "mr-lasso": "Designed to identify and penalize a small number of instruments with large direct pleiotropic effects.",
  "mr-mrmix": "Designed for widespread horizontal pleiotropy when valid instruments are expected to form an identifiable mixture component.",
  "mr-raps": "Designed for many weak or moderately associated instruments; corrects weak-IV bias and limits the influence of balanced pleiotropy and outliers.",
  "mr-presso": "Designed to detect horizontal-pleiotropy outliers and compare prespecified raw and outlier-corrected causal estimates.",
  "mr-robust": "Designed as a fast robustness check when a few influential or outlying instruments may be driving the ordinary IVW estimate.",
  "mr-cause": "Designed to distinguish a causal effect from correlated horizontal pleiotropy or genetic sharing between the exposure and outcome.",
};

const DEFAULT_STUDY_METHOD_IDS = ["mr-primary", "mr-apss", "mr-bwmr"];

const els = {
  newChatButton: document.getElementById("new-chat-button"),
  forkSessionButton: document.getElementById("fork-session-button"),
  providerSelect: document.getElementById("provider-select"),
  refreshButton: document.getElementById("refresh-button"),
  sessionList: document.getElementById("session-list"),
  sessionStatusToggle: document.getElementById("session-status-toggle"),
  sessionTitle: document.getElementById("session-title"),
  sessionSubtitle: document.getElementById("session-subtitle"),
  sessionIdentity: document.getElementById("session-identity"),
  sessionId: document.getElementById("session-id"),
  statusChip: document.getElementById("status-chip"),
  timeline: document.getElementById("timeline"),
  workspace: document.querySelector(".workspace"),
  studySetupPanel: document.getElementById("study-setup-panel"),
  studySetupResizer: document.querySelector("[data-study-setup-resizer]"),
  studySetupStatus: document.getElementById("study-setup-status"),
  studySetupContent: document.getElementById("study-setup-content"),
  studySetupToggle: document.getElementById("study-setup-toggle"),
  pendingText: document.getElementById("pending-text"),
  conversationFeed: document.getElementById("conversation-feed"),
  replyForm: document.getElementById("reply-form"),
  replyInput: document.getElementById("reply-input"),
  replyButton: document.getElementById("reply-button"),
  stopJobButton: document.getElementById("stop-job-button"),
  notebookOutput: document.getElementById("notebook-output"),
  notebookStatus: document.getElementById("notebook-status"),
  notebookLatest: document.getElementById("notebook-latest"),
  notebookTaskTab: document.getElementById("notebook-task-tab"),
  notebookBuilderTab: document.getElementById("notebook-builder-tab"),
  notebookBuilderTabStatus: document.getElementById("notebook-builder-tab-status"),
  appShell: document.querySelector(".app-shell"),
  sidebar: document.querySelector(".sidebar"),
  sidebarResizer: document.querySelector("[data-sidebar-resizer]"),
  sessionsSidebarToggle: document.getElementById("sessions-sidebar-toggle"),
  mainGrid: document.querySelector(".main-grid"),
  layoutResizers: Array.from(document.querySelectorAll("[data-layout-resizer]")),
};

const SIDEBAR_RESIZE_LIMITS = {
  min: 240,
  max: 560,
  workspace: 520,
};

const STUDY_SETUP_RESIZE_LIMITS = {
  min: 240,
  max: 560,
  content: 620,
};

const PANEL_RESIZE_LIMITS = {
  conversation: 288,
  side: 288,
  gridChrome: 56,
};

function isReadOnlySession() {
  return Boolean(state.example) || PUBLIC_DEMO_SESSIONS.has(state.currentSessionId);
}

async function requestJson(url, options = {}) {
  if (isReadOnlySession() && options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) {
    throw new Error("This example is read only. Start a new chat to run your own analysis.");
  }
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

async function loadStudyMethodOptions() {
  const payload = await requestJson("/api/methods");
  state.studyMethodOptions = Array.isArray(payload.methods)
    ? payload.methods
      .filter((item) => item && text(item.id) && text(item.label))
      .map((item) => ({
        ...item,
        description: STUDY_METHOD_PURPOSES[item.id] || item.description || "MR method for the selected study setup.",
      }))
    : [];
  state.studySourceOptions = Array.isArray(payload.sources)
    ? payload.sources.filter((item) => item && text(item.id) && text(item.label))
    : [];
}

function text(value) {
  return String(value || "").trim();
}

function normalizedSourceToken(value) {
  return text(value).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function normalizeSourceId(value) {
  const token = normalizedSourceToken(value);
  if (!token) return "";
  for (const sourceId of SOURCE_ORDER) {
    const definition = SOURCE_REGISTRY[sourceId];
    const aliases = [sourceId, definition.label, ...(definition.aliases || [])];
    if (aliases.some((alias) => normalizedSourceToken(alias) === token)) return sourceId;
  }
  return "";
}

function sourceDefinition(value) {
  const sourceId = normalizeSourceId(value);
  return sourceId ? { id: sourceId, ...SOURCE_REGISTRY[sourceId] } : null;
}

function sourceIdsInValue(value) {
  let raw = "";
  if (typeof value === "string") raw = value;
  else if (value !== undefined && value !== null) {
    try {
      raw = JSON.stringify(value);
    } catch {
      raw = String(value);
    }
  }
  const haystack = raw.toLowerCase();
  if (!haystack) return [];
  return SOURCE_ORDER.filter((sourceId) => {
    const definition = SOURCE_REGISTRY[sourceId];
    const aliases = [sourceId, definition.label, ...(definition.aliases || [])];
    return aliases.some((alias) => haystack.includes(text(alias).toLowerCase()));
  });
}

function createSourceIcon(value, options = {}) {
  const definition = sourceDefinition(value);
  if (!definition) {
    const fallback = document.createElement("span");
    fallback.className = `source-icon source-icon-fallback${options.small ? " is-small" : ""}`;
    fallback.textContent = text(value).slice(0, 1).toUpperCase() || "?";
    fallback.setAttribute("aria-hidden", "true");
    return fallback;
  }
  const image = document.createElement("img");
  image.className = `source-icon${options.small ? " is-small" : ""}`;
  image.src = definition.icon;
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  image.setAttribute("aria-hidden", "true");
  return image;
}

function createSourceBadge(value, options = {}) {
  const definition = sourceDefinition(value);
  const rawLabel = text(value).replaceAll("_", " ") || "Unknown source";
  const element = options.link && definition ? document.createElement("a") : document.createElement("span");
  element.className = `source-badge${options.compact ? " is-compact" : ""}${definition ? ` source-${definition.id}` : ""}`;
  if (element instanceof HTMLAnchorElement && definition) {
    element.href = definition.url;
    element.target = "_blank";
    element.rel = "noopener noreferrer";
    element.title = `Open ${definition.label}`;
  }
  element.appendChild(createSourceIcon(value, { small: options.compact }));
  const label = document.createElement("span");
  label.className = "source-badge-label";
  label.textContent = definition?.label || rawLabel;
  element.appendChild(label);
  if (options.count !== undefined && options.count !== null) {
    const count = document.createElement("strong");
    count.className = "source-badge-count";
    count.textContent = formatInteger(options.count);
    element.appendChild(count);
  }
  return element;
}

function createUiIcon(name, options = {}) {
  const icon = document.createElement("span");
  icon.className = `ui-icon ui-icon-${name}`;
  const assetPath = UI_ICON_ASSETS[name];
  if (assetPath) {
    const asset = document.createElement("span");
    asset.className = "ui-icon-asset";
    asset.style.setProperty("--ui-icon-asset", `url("${assetPath}")`);
    icon.appendChild(asset);
  } else {
    icon.textContent = UI_ICON_GLYPHS[name] || "•";
  }
  if (options.label) {
    icon.setAttribute("role", "img");
    icon.setAttribute("aria-label", options.label);
  } else {
    icon.setAttribute("aria-hidden", "true");
  }
  return icon;
}

function messageAgentIconKind(label) {
  const normalized = text(label).toLowerCase();
  if (normalized.startsWith("manager")) return "manager";
  if (normalized.includes("search agent") || normalized === "data search" || normalized === "scan design") return "search";
  if (normalized.includes("mr agent")) return "mr";
  if (normalized.includes("report")) return "report";
  return "";
}

function createAgentIcon(kind) {
  const assetPath = AGENT_ICON_ASSETS[kind];
  if (!assetPath) return null;
  const icon = document.createElement("span");
  icon.className = `agent-icon agent-icon-${kind}`;
  icon.style.setProperty("--agent-icon-asset", `url("${assetPath}")`);
  icon.setAttribute("aria-hidden", "true");
  return icon;
}

function formatInteger(value) {
  const normalized = typeof value === "string" ? value.replaceAll(",", "") : value;
  const number = Number(normalized);
  return Number.isFinite(number) ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(number) : text(value) || "-";
}

function displayAncestry(value) {
  const normalized = text(value).toLowerCase();
  const labels = {
    european: "European",
    finnish: "Finnish",
    east_asian: "East Asian",
    south_asian: "South Asian",
    african: "African",
    multi_ancestry: "Multi-ancestry",
    unknown: "Unknown",
  };
  return labels[normalized] || text(value).replaceAll("_", " ") || "-";
}

function eventText(event) {
  if (!event || typeof event !== "object") return "";
  return text(event.text || event.summary || event.message || event.decision || event.result);
}

function canStopActiveJob(snapshot) {
  return text(snapshot?.active_job?.status) === "running"
    && text(snapshot?.active_job?.kind) !== "benchmark_case";
}

function shortId(value) {
  const raw = text(value);
  if (raw.length <= 24) return raw || "-";
  return `${raw.slice(0, 14)}...${raw.slice(-7)}`;
}

function displaySessionId(value) {
  return shortId(text(value).replace(/^(?:session|bridge)_/, ""));
}

function statusLabel(status) {
  const map = {
    created: "Created",
    search_running: "Search running",
    waiting_user: "Waiting user",
    brief_ready: "Brief ready",
    handoff_waiting: "Handoff waiting",
    mr_running: "MR running",
    double_check_running: "Double check running",
    plot_running: "Plot generation running",
    completed: "Completed",
    failed: "Turn failed",
  };
  return map[text(status)] || text(status).replace(/^[a-z]/, letter => letter.toUpperCase()) || "Idle";
}

function sessionStatusDescription(status) {
  return text(status) === "failed"
    ? "The latest turn did not complete successfully. Earlier results remain available."
    : "";
}

function apiBody(payload) {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
}

function setBusy(isBusy) {
  state.busy = isBusy;
  updateComposer();
  renderStudySetup(state.snapshot);
  document.querySelectorAll("[data-report-action]").forEach(button => {
    button.disabled = Boolean(isBusy || state.snapshot?.active_job);
  });
}

function setStudySetupCollapsed(collapsed) {
  state.studySetupCollapsed = Boolean(collapsed);
  els.workspace?.classList.toggle("study-setup-collapsed", state.studySetupCollapsed);
  els.studySetupPanel?.classList.toggle("is-collapsed", state.studySetupCollapsed);
  if (!els.studySetupToggle) return;
  const expanded = !state.studySetupCollapsed;
  const label = expanded ? "Collapse Study setup" : "Expand Study setup";
  els.studySetupToggle.setAttribute("aria-expanded", String(expanded));
  els.studySetupToggle.setAttribute("aria-label", label);
  els.studySetupToggle.title = label;
  const icon = els.studySetupToggle.querySelector("[aria-hidden='true']");
  if (icon) icon.textContent = expanded ? "‹" : "›";
}

function setSessionStatusVisible(visible, persist = true) {
  const show = Boolean(visible);
  els.appShell.classList.toggle("hide-session-status", !show);
  els.sessionStatusToggle.checked = show;
  if (persist) {
    try {
      window.localStorage.setItem(SESSION_STATUS_STORAGE_KEY, String(show));
    } catch {
      // The switch still works when browser storage is unavailable.
    }
  }
}

function restoreSessionStatusVisibility() {
  let visible = true;
  try {
    visible = window.localStorage.getItem(SESSION_STATUS_STORAGE_KEY) !== "false";
  } catch {
    // Use the default when browser storage is unavailable.
  }
  setSessionStatusVisible(visible, false);
}

function setSessionsSidebarCollapsed(collapsed) {
  state.sessionsSidebarCollapsed = Boolean(collapsed);
  els.appShell?.classList.toggle("sessions-sidebar-collapsed", state.sessionsSidebarCollapsed);
  els.sidebar?.setAttribute("aria-hidden", String(state.sessionsSidebarCollapsed));
  if (!els.sessionsSidebarToggle) return;
  const expanded = !state.sessionsSidebarCollapsed;
  const label = expanded ? "Collapse Sessions" : "Expand Sessions";
  els.sessionsSidebarToggle.setAttribute("aria-expanded", String(expanded));
  els.sessionsSidebarToggle.setAttribute("aria-label", label);
  els.sessionsSidebarToggle.title = label;
  const icon = els.sessionsSidebarToggle.querySelector("[aria-hidden='true']");
  if (icon) icon.textContent = expanded ? "‹" : "›";
}

function clampNumber(value, min, max) {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function setGridSizeVar(name, value) {
  els.mainGrid.style.setProperty(name, `${Math.round(value)}px`);
}

function setShellSizeVar(name, value) {
  els.appShell.style.setProperty(name, `${Math.round(value)}px`);
}

function setWorkspaceSizeVar(name, value) {
  els.workspace.style.setProperty(name, `${Math.round(value)}px`);
}

function initSidebarResizer() {
  if (!els.appShell || !els.sidebar || !els.sidebarResizer) return;
  els.sidebarResizer.addEventListener("pointerdown", startSidebarResize);
}

function initStudySetupResizer() {
  if (!els.workspace || !els.studySetupPanel || !els.studySetupResizer) return;
  els.studySetupResizer.addEventListener("pointerdown", startStudySetupResize);
}

function initPanelResizers() {
  if (!els.mainGrid || els.layoutResizers.length === 0) return;
  for (const handle of els.layoutResizers) {
    handle.addEventListener("pointerdown", startPanelResize);
  }
}

function startSidebarResize(event) {
  if (event.pointerType === "mouse" && event.button !== 0) return;
  if (state.sessionsSidebarCollapsed || els.sessionsSidebarToggle?.contains(event.target)) return;
  if (window.matchMedia("(max-width: 1100px)").matches) return;

  event.preventDefault();
  const handle = event.currentTarget;
  const shellRect = els.appShell.getBoundingClientRect();
  const sidebarRect = els.sidebar.getBoundingClientRect();
  const start = {
    x: event.clientX,
    width: sidebarRect?.width || SIDEBAR_RESIZE_LIMITS.max,
  };

  document.body.classList.add("layout-resizing");
  document.body.style.cursor = "col-resize";
  handle.classList.add("active");
  const pointerId = event.pointerId;
  handle.setPointerCapture(pointerId);

  const onPointerMove = (moveEvent) => {
    resizeSidebar(moveEvent, shellRect, start);
  };
  const stopResize = () => {
    handle.removeEventListener("pointermove", onPointerMove);
    handle.removeEventListener("pointerup", stopResize);
    handle.removeEventListener("pointercancel", stopResize);
    if (handle.hasPointerCapture(pointerId)) {
      handle.releasePointerCapture(pointerId);
    }
    handle.classList.remove("active");
    document.body.classList.remove("layout-resizing");
    document.body.style.cursor = "";
  };

  handle.addEventListener("pointermove", onPointerMove);
  handle.addEventListener("pointerup", stopResize);
  handle.addEventListener("pointercancel", stopResize);
}

function resizeSidebar(event, shellRect, start) {
  const nextWidth = start.width + event.clientX - start.x;
  const maxWidth = Math.min(
    SIDEBAR_RESIZE_LIMITS.max,
    shellRect.width - SIDEBAR_RESIZE_LIMITS.workspace,
  );
  setShellSizeVar(
    "--sidebar-width",
    clampNumber(nextWidth, SIDEBAR_RESIZE_LIMITS.min, maxWidth),
  );
}

function startStudySetupResize(event) {
  if (event.pointerType === "mouse" && event.button !== 0) return;
  if (state.studySetupCollapsed || window.matchMedia("(max-width: 1100px)").matches) return;

  event.preventDefault();
  const handle = event.currentTarget;
  const workspaceRect = els.workspace.getBoundingClientRect();
  const panelRect = els.studySetupPanel.getBoundingClientRect();
  const start = {
    x: event.clientX,
    width: panelRect?.width || 304,
  };

  document.body.classList.add("layout-resizing");
  document.body.style.cursor = "col-resize";
  handle.classList.add("active");
  const pointerId = event.pointerId;
  handle.setPointerCapture(pointerId);

  const onPointerMove = (moveEvent) => {
    resizeStudySetup(moveEvent, workspaceRect, start);
  };
  const stopResize = () => {
    handle.removeEventListener("pointermove", onPointerMove);
    handle.removeEventListener("pointerup", stopResize);
    handle.removeEventListener("pointercancel", stopResize);
    if (handle.hasPointerCapture(pointerId)) {
      handle.releasePointerCapture(pointerId);
    }
    handle.classList.remove("active");
    document.body.classList.remove("layout-resizing");
    document.body.style.cursor = "";
  };

  handle.addEventListener("pointermove", onPointerMove);
  handle.addEventListener("pointerup", stopResize);
  handle.addEventListener("pointercancel", stopResize);
}

function resizeStudySetup(event, workspaceRect, start) {
  const nextWidth = start.width + event.clientX - start.x;
  const maxWidth = Math.min(
    STUDY_SETUP_RESIZE_LIMITS.max,
    workspaceRect.width - STUDY_SETUP_RESIZE_LIMITS.content,
  );
  const width = clampNumber(nextWidth, STUDY_SETUP_RESIZE_LIMITS.min, maxWidth);
  setWorkspaceSizeVar("--study-setup-width", width);
  els.studySetupResizer?.setAttribute("aria-valuenow", String(Math.round(width)));
}

function startPanelResize(event) {
  if (event.pointerType === "mouse" && event.button !== 0) return;
  const handle = event.currentTarget;
  if (window.matchMedia("(max-width: 1100px)").matches) return;

  event.preventDefault();
  const gridRect = els.mainGrid.getBoundingClientRect();
  const conversationRect = document.querySelector(".conversation-panel")?.getBoundingClientRect();

  const start = {
    x: event.clientX,
    conversationWidth: conversationRect?.width || gridRect.width * 0.55,
  };

  document.body.classList.add("layout-resizing");
  document.body.style.cursor = "col-resize";
  handle.classList.add("active");
  const pointerId = event.pointerId;
  handle.setPointerCapture(pointerId);

  const onPointerMove = (moveEvent) => {
    resizeMainColumns(moveEvent, gridRect, start);
  };
  const stopResize = () => {
    handle.removeEventListener("pointermove", onPointerMove);
    handle.removeEventListener("pointerup", stopResize);
    handle.removeEventListener("pointercancel", stopResize);
    if (handle.hasPointerCapture(pointerId)) {
      handle.releasePointerCapture(pointerId);
    }
    handle.classList.remove("active");
    document.body.classList.remove("layout-resizing");
    document.body.style.cursor = "";
  };

  handle.addEventListener("pointermove", onPointerMove);
  handle.addEventListener("pointerup", stopResize);
  handle.addEventListener("pointercancel", stopResize);
}

function resizeMainColumns(event, gridRect, start) {
  const nextWidth = start.conversationWidth + event.clientX - start.x;
  const maxWidth = gridRect.width - PANEL_RESIZE_LIMITS.side - PANEL_RESIZE_LIMITS.gridChrome;
  setGridSizeVar(
    "--conversation-width",
    clampNumber(nextWidth, PANEL_RESIZE_LIMITS.conversation, maxWidth),
  );
}

async function refreshSessions() {
  if (REPLAY_ONLY) return;
  const payload = await requestJson("/api/sessions");
  state.sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
  renderSessions();
}

function refreshSessionsWhenVisible() {
  if (document.hidden) return;
  void refreshSessions();
}

function renderSessions() {
  els.sessionList.innerHTML = "";
  if (state.sessions.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-note";
    empty.textContent = "No MRCAT sessions yet.";
    els.sessionList.appendChild(empty);
    return;
  }

  for (const item of state.sessions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-row";
    if (item.session_id === state.currentSessionId) button.classList.add("active");
    button.addEventListener("click", () => selectSession(item.session_id));

    const title = document.createElement("strong");
    title.textContent = text(item.question) || `Session ${displaySessionId(item.session_id)}`;
    if (PUBLIC_DEMO_SESSIONS.has(item.session_id)) title.textContent = `Public example · ${title.textContent}`;
    button.title = text(item.question) || title.textContent;
    button.setAttribute("aria-current", item.session_id === state.currentSessionId ? "true" : "false");
    const status = document.createElement("span");
    status.className = `mini-status ${text(item.status).replaceAll("_", "-")}`;
    status.textContent = statusLabel(item.status);
    status.title = sessionStatusDescription(item.status);

    button.appendChild(title);
    button.appendChild(status);
    els.sessionList.appendChild(button);
  }
}

async function selectSession(sessionId) {
  if (LIVE_DEMO) clearLiveDemoSetup();
  if (!sessionId) return;
  leaveExample();
  const preservePendingNewSession = Boolean(
    state.pendingUserMessage
    && !state.currentSessionId
    && !state.pendingUserMessage.sessionId
  );
  if (state.pendingUserMessage && !preservePendingNewSession) {
    state.pendingUserMessage = null;
  }
  state.currentSessionId = sessionId;
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${encodeURIComponent(sessionId)}`);
  if (preservePendingNewSession) state.pendingUserMessage.sessionId = sessionId;
  state.snapshot = null;
  state.jsonArtifactCache.clear();
  state.tableArtifactCache.clear();
  state.expandedDataSearchTargets.clear();
  state.dataSearchSourceFilters.clear();
  state.scanSelection = {};
  resetStudySetupDraft();
  renderHeader(null);
  renderTimeline(null);
  renderStudySetup(null);
  renderConversation(null);
  setStudySetupCollapsed(true);
  resetExecutionNotebook();
  renderExecutionNotebook();
  renderSessions();
  connectEvents();
}

function newChat() {
  if (LIVE_DEMO) clearLiveDemoSetup();
  leaveExample();
  state.currentSessionId = null;
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  state.snapshot = null;
  state.pendingUserMessage = null;
  state.jsonArtifactCache.clear();
  state.tableArtifactCache.clear();
  state.expandedDataSearchTargets.clear();
  state.dataSearchSourceFilters.clear();
  state.scanSelection = {};
  resetStudySetupDraft();
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  renderHeader(null);
  renderTimeline(null);
  renderStudySetup(null);
  renderConversation(null);
  setStudySetupCollapsed(true);
  resetExecutionNotebook();
  renderExecutionNotebook();
  renderSessions();
  updateComposer();
  els.replyInput.focus();
}

async function loadSnapshot() {
  if (!state.currentSessionId || state.example) return;
  const sessionId = state.currentSessionId;
  const before = state.snapshot;
  const snapshot = await requestJson(`/api/sessions/${encodeURIComponent(sessionId)}`);
  // A stream update received during this GET is already newer.
  if (state.currentSessionId === sessionId && state.snapshot === before) applySnapshot(snapshot);
}

function resetStudySetupDraft() {
  state.studySetupDraft = {
    exposures: [{ name: "", file: null, fileRef: "" }],
    outcomes: [{ name: "", file: null, fileRef: "" }],
    analysisRequest: "",
    sources: [],
    methods: [],
    dirty: false,
  };
}

function connectEvents() {
  if (!state.currentSessionId || state.example) return;
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  if (LIVE_DEMO) {
    connectLiveDemoPolling();
    return;
  }
  const source = new EventSource(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/events`);
  source.addEventListener("snapshot", (event) => {
    if (state.eventSource !== source) return;
    state.activityConnection = "connected";
    applySnapshot(JSON.parse(event.data));
  });
  source.addEventListener("events", (event) => {
    if (state.eventSource !== source || !state.snapshot) return;
    const changes = JSON.parse(event.data);
    const events = new Map((state.snapshot.mr?.events || []).map(item => [item.id, item]));
    changes.forEach(item => events.set(item.id, item));
    const merged = [...events.values()];
    const snapshot = state.snapshot;
    applySnapshot({ ...snapshot, mr: { ...snapshot.mr, events: merged,
      state: { ...snapshot.mr.state, events: merged } } });
  });
  source.addEventListener("open", () => {
    if (state.eventSource !== source) return;
    state.activityConnection = "connected";
    renderActivity(state.snapshot);
  });
  source.addEventListener("error", () => {
    if (state.eventSource !== source || !state.snapshot) return;
    state.activityConnection = "reconnecting";
    renderActivity(state.snapshot);
  });
  state.activityConnection = "connecting";
  state.eventSource = source;
}

function activityDuration(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
}

function sessionActivity(snapshot, clock = Date.now()) {
  const job = snapshot?.active_job;
  if (!job) return null;
  const started = Date.parse(job.created_at);
  // A resumed session contains older tasks and failures. Describe this job only.
  const events = (snapshot.mr?.events || []).filter(event =>
    Number.isFinite(started) && Date.parse(event.timestamp) >= started);
  const executions = events.filter(event => event.type === "code_execution");
  const execution = executions.at(-1);
  const failed = event => event.details?.status === "exited"
    ? event.details.returncode != null && event.details.returncode !== 0
    : ["timeout", "launch_error", "failed"].includes(event.details?.status);
  const failures = executions.filter(failed).length;
  const last = events.at(-1);
  const d = execution?.details;
  const codeRunning = d?.status === "running";
  let title = "Preparing next step";
  let detail = "No code execution is currently recorded as running.";
  if (codeRunning) {
    const language = {python: "Python", r: "R", bash: "shell"}[d.language] || "analysis";
    title = `${failures ? "Retrying" : "Running"} ${language} code`;
    detail = "Execution is in progress. Open the execution record for output and logs.";
  } else if (last?.type === "executor_handoff") {
    title = "Review requested";
    detail = last.details?.outcome === "blocked"
      ? "Execution was blocked. Review was requested to decide how to proceed."
      : "The executor handed its work to Review for assessment.";
  } else if (last?.type === "evaluation") {
    const route = last.details?.route;
    title = route === "execute" ? (failures ? "Preparing next attempt" : "Preparing next step")
      : route === "replan" ? "Revising plan" : route === "finalize" ? "Preparing response" : "Review decision received";
    detail = route === "execute"
      ? "Review requested another execution. The next execution has not started."
      : "A Review decision was recorded; the next action has not been recorded yet.";
  } else if (last?.type === "code_execution") {
    title = failed(last) ? "Preparing recovery" : "Assessing execution output";
    detail = failed(last) ? "The last execution failed. No new execution has started."
      : "The last execution finished. Its output is available in the execution record.";
  } else if (["user_message", "manager_route", "task_created", "task_revised", "plan_updated"].includes(last?.type)) {
    title = last.type === "user_message" ? "Processing request" : "Preparing analysis";
  } else if (last?.type === "report_started" || last?.type === "report_stage") {
    title = "Preparing report";
    detail = "See the report card for the latest recorded report stage.";
  }
  if (failures) detail += ` ${failures} failed execution${failures === 1 ? "" : "s"} in this run.`;
  const completion = !codeRunning && execution
    ? Date.parse(execution.timestamp) + (Number(d.duration_seconds) || 0) * 1000 : NaN;
  const times = [started, Date.parse(snapshot.state?.updated_at), Date.parse(last?.timestamp), completion]
    .filter(Number.isFinite);
  const updated = times.length ? Math.min(clock, Math.max(...times)) : clock;
  return {title, detail, codeRunning, failures, executionId: d?.execution_id,
    elapsed: Number.isFinite(started) ? Math.max(0, clock - started) : null,
    quiet: Math.max(0, clock - updated)};
}

function renderActivity(snapshot) {
  const panel = document.getElementById("session-activity");
  if (isReadOnlySession()) {
    panel.hidden = true;
    els.statusChip.textContent = "Read only";
    return;
  }
  const activity = sessionActivity(snapshot);
  const disconnected = state.activityConnection === "reconnecting";
  panel.hidden = !activity && !(snapshot && disconnected);
  if (panel.hidden) {
    if (snapshot) els.statusChip.textContent = statusLabel(snapshot.state?.status || "Ready");
    return;
  }
  const title = disconnected ? "Connection interrupted" : activity.title;
  const setText = (id, value) => {
    const node = document.getElementById(id);
    if (node.textContent !== value) node.textContent = value;
  };
  setText("activity-title", title);
  setText("activity-time", activity?.elapsed == null ? "" : `Total ${activityDuration(activity.elapsed)}`);
  setText("activity-detail", disconnected
    ? "Reconnecting to session updates. The current backend activity cannot be confirmed."
    : activity.detail);
  setText("activity-freshness", disconnected ? "Displayed progress may be out of date."
    : activity.quiet >= 1000 ? `No new activity recorded for ${activityDuration(activity.quiet)}.${activity.quiet >= 180000 ? " Completion time is not available." : ""}`
      : "Activity just updated.");
  panel.classList.toggle("is-delayed", disconnected || activity?.quiet >= 180000);
  const button = document.getElementById("activity-execution");
  button.hidden = !activity?.executionId;
  button.onclick = () => focusCodeExecution(activity.executionId);
  els.statusChip.textContent = title;
  if (activity) els.replyInput.placeholder = `${title} · see progress above`;
}

function applySnapshot(snapshot) {
  if (snapshot.session_id === state.snapshot?.session_id
      && text(snapshot.state?.updated_at) < text(state.snapshot.state?.updated_at)) return;
  state.snapshot = snapshot;
  if (state.pendingUserMessage && (snapshot.mr?.events || []).some((event) => event.type === "user_message" && event.content === state.pendingUserMessage.text)) state.pendingUserMessage = null;
  renderHeader(snapshot);
  renderTimeline(snapshot);
  renderStudySetup(snapshot);
  renderConversation(snapshot);
  renderExecutionNotebook();
  renderSessions();
  updateComposer();
}

function renderHeader(snapshot) {
  const session = snapshot?.state || {};
  els.sessionTitle.textContent = text(session.question) || (session.session_id ? "MRCAT session" : "New chat");
  els.sessionTitle.title = els.sessionTitle.textContent;
  els.sessionSubtitle.textContent = "";
  els.sessionSubtitle.hidden = true;
  els.sessionId.textContent = session.session_id || "";
  els.sessionIdentity.hidden = !session.session_id;
  els.statusChip.textContent = sessionActivity(snapshot)?.title || statusLabel(session.status || "Ready");
  els.statusChip.className = "status-chip";
  els.pendingText.hidden = !text(snapshot?.pending_question);
  els.pendingText.disabled = !(snapshot?.mr?.events || []).some(event => event.type === "question");
  renderActivity(snapshot);
}

function focusPendingQuestion() {
  const question = [...els.conversationFeed.querySelectorAll(".message-question")].at(-1);
  if (!question) return;
  const feed = els.conversationFeed;
  const top = feed.scrollTop + question.getBoundingClientRect().top - feed.getBoundingClientRect().top - 12;
  feed.scrollTo({top, behavior: "smooth"});
  question.focus({preventScroll: true});
}

function renderTimeline(snapshot) {
  const events = snapshot?.mr?.events || [];
  const running = Boolean(snapshot?.active_job);
  const activity = sessionActivity(snapshot);
  const latestPlan = [...events].reverse().find(event => event.type === "plan_updated");
  const lastUserIndex = events.findLastIndex(event => event.type === "user_message");
  const lastPlanIndex = events.findLastIndex(event => event.type === "plan_updated");
  const route = [...events].reverse().find(event => event.type === "manager_route");
  const planning = running && snapshot?.state?.active_agent === "mr" && ["propose", "revise"].includes(route?.details?.action) && lastUserIndex > lastPlanIndex;
  els.timeline.replaceChildren();
  for (const [label, tone] of [["Plan", planning ? "active" : latestPlan ? "done" : "pending"], ["Execution", activity?.codeRunning ? "active" : running ? "pending" : events.some(e => e.type === "code_execution") ? "done" : "pending"], ["Results", snapshot?.state?.status === "completed" ? "done" : "pending"]]) {
    const item = document.createElement(label === "Plan" ? "button" : "div");
    item.className = `timeline-item ${tone}`;
    if (label === "Plan") {
      item.type = "button";
      item.disabled = !latestPlan;
      item.title = planning ? "A new plan is being prepared; view the previous plan" : "View current plan";
      item.setAttribute("aria-label", item.title);
      item.addEventListener("click", () => {
        const card = [...els.conversationFeed.querySelectorAll("details[data-plan-id]")].find(node => node.dataset.planId === latestPlan?.id);
        if (card) {
          card.open = true;
          const feed = els.conversationFeed;
          const top = feed.scrollTop + card.getBoundingClientRect().top - feed.getBoundingClientRect().top - 12;
          feed.scrollTo({top, behavior: "smooth"});
          card.querySelector("summary").focus({preventScroll: true});
        }
      });
    }
    item.appendChild(document.createElement("span"));
    const title = document.createElement("strong"); title.textContent = label === "Plan" && planning ? "Planning…" : label === "Execution" && activity ? activity.title : label; item.appendChild(title);
    els.timeline.appendChild(item);
  }
}

function captureConversationScroll() {
  const feed = els.conversationFeed;
  const distanceFromBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight;
  return {
    distanceFromBottom: Math.max(0, distanceFromBottom),
    scrollTop: feed.scrollTop,
    stickToBottom: distanceFromBottom < 96,
  };
}

function restoreConversationScroll(scrollState) {
  if (!scrollState) return;
  const feed = els.conversationFeed;
  if (scrollState.stickToBottom) {
    feed.scrollTop = feed.scrollHeight;
    return;
  }
  feed.scrollTop = Math.min(scrollState.scrollTop, feed.scrollHeight);
}

function createSkillLabel(skillId) {
  const label = document.createElement("span");
  label.className = "skill-label";
  label.appendChild(createUiIcon(skillVisualKind(skillId)));
  const name = document.createElement("span");
  name.className = "skill-label-name";
  name.textContent = skillId;
  label.appendChild(name);
  return label;
}

function decoratePlanSkills(content) {
  // Annotate explicit skill names without turning the prose plan into execution state.
  const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    if (!walker.currentNode.parentElement.closest("pre, a, .skill-label")) nodes.push(walker.currentNode);
  }
  for (const node of nodes) {
    const matches = [...node.textContent.matchAll(/\b(?:gwas|mr|analysis|phenome-scan)-[a-z0-9]+(?:-[a-z0-9]+)*\b/g)];
    if (!matches.length) continue;
    const fragment = document.createDocumentFragment();
    let start = 0;
    for (const match of matches) {
      fragment.append(node.textContent.slice(start, match.index), createSkillLabel(match[0]));
      start = match.index + match[0].length;
    }
    fragment.append(node.textContent.slice(start));
    node.replaceWith(fragment);
  }
}

function planTaskForEvent(event, snapshot) {
  if (event.details?.draft) return null;
  const tasks = [snapshot?.mr?.state?.active_task, ...(snapshot?.mr?.state?.task_history || [])].filter(Boolean);
  // Only the recorded task and exact plan revision may supply live progress.
  return tasks.find(task => task.task_id === event.details?.task_id && task.plan === event.content) || null;
}

function buildReadablePlan(event, current, open, detailOpen, snapshot) {
  const card = document.createElement("details");
  card.className = "plan-workflow-card readable-plan";
  card.dataset.planId = event.id;
  card.dataset.currentPlan = String(current);
  card.open = open;
  const heading = document.createElement("summary");
  const identity = document.createElement("span");
  identity.className = "readable-plan-heading";
  const title = document.createElement("strong");
  title.textContent = current ? (event.details?.draft ? "Proposed plan" : "Analysis plan") : "Previous plan";
  identity.appendChild(title);
  const task = planTaskForEvent(event, snapshot);
  const progress = document.createElement("span");
  progress.className = "readable-plan-meta";
  if (task?.plan_items?.length) {
    const completed = task.plan_items.filter(item => task.completed_items?.[item.step_id]).length;
    progress.textContent = `${completed} / ${task.plan_items.length} completed`;
  } else {
    progress.textContent = event.details?.draft ? "Awaiting confirmation" : "";
  }
  if (progress.textContent) identity.appendChild(progress);
  heading.append(identity);
  const content = document.createElement("div");
  content.className = "codeact-plan";
  content.innerHTML = renderMarkdown(event.content);
  decoratePlanSkills(content);
  let number = 0;
  for (const list of content.querySelectorAll(":scope > ol, :scope > ul")) {
    list.classList.add("readable-plan-steps");
    for (const item of list.children) {
      number++;
      const copy = document.createElement("div");
      copy.className = "readable-plan-copy";
      copy.append(...item.childNodes);
      const firstText = copy.firstChild?.nodeType === Node.TEXT_NODE ? copy.firstChild : copy.querySelector("p")?.firstChild;
      const match = firstText?.nodeType === Node.TEXT_NODE && firstText.textContent.match(/^\[([a-z][a-z0-9_]*)\]\s*/);
      const stepId = match ? match[1] : "";
      if (match) firstText.textContent = firstText.textContent.slice(match[0].length);
      const planned = task?.plan_items?.find(step => step.step_id === stepId);
      const completed = planned && task.completed_items?.[stepId];
      const active = planned && task.current_item_id === stepId;
      const executions = completed?.execution_ids || (active ? task.item_execution_ids || [] : []);
      const savedEvents = codeExecutionEvents(snapshot).filter(e => executions.includes(e.details.execution_id));
      const lastExecution = savedEvents.at(-1);
      let tone = completed ? "completed" : "pending";
      let label = completed ? "Completed" : planned ? "Pending" : event.details?.draft ? "Proposed" : "Planned";
      if (active && !completed) {
        if (snapshot.active_job && task === snapshot.mr.state.active_task && task.status === "running") {
          tone = "running"; label = "Running";
        } else { tone = "paused"; label = "Paused"; }
        if (lastExecution && codeExecutionTone(lastExecution.details) === "failed" && !snapshot.active_job) {
          tone = "failed"; label = "Needs attention";
        }
      }
      item.className = `readable-plan-step is-${tone}`;
      const marker = document.createElement("span");
      marker.className = "readable-plan-number";
      marker.setAttribute("aria-hidden", "true");
      marker.textContent = completed ? "✓" : String(number).padStart(2, "0");
      const body = document.createElement("div");
      body.className = "readable-plan-step-body";
      const detail = document.createElement("details");
      detail.className = "readable-plan-description";
      detail.dataset.planDetail = `${event.id}:${number}`;
      detail.open = detailOpen.has(detail.dataset.planDetail) ? detailOpen.get(detail.dataset.planDetail) : tone === "running";
      const summary = document.createElement("summary");
      const title = document.createElement("strong");
      const rawTitle = planned?.title || copy.querySelector("strong")?.textContent || copy.textContent.replace(/^\d+[.)]\s+/, "").split(/(?<=[.!?])\s/)[0];
      title.className = "readable-plan-step-title";
      title.textContent = rawTitle;
      title.title = rawTitle;
      const status = document.createElement("span");
      status.className = `readable-plan-status is-${tone}`;
      status.textContent = label;
      summary.append(title, status);
      // Details contain only the text after the title, preserving its Markdown.
      const leadingText = copy.textContent.trimStart();
      if (leadingText.startsWith(rawTitle.trim())) {
        let remaining = copy.textContent.length - leadingText.length + rawTitle.trim().length;
        const walker = document.createTreeWalker(copy, NodeFilter.SHOW_TEXT);
        while (remaining > 0 && walker.nextNode()) {
          const node = walker.currentNode;
          const removed = Math.min(remaining, node.textContent.length);
          node.textContent = node.textContent.slice(removed);
          remaining -= removed;
        }
      }
      if (copy.textContent.trim()) {
        detail.append(summary, copy);
        body.appendChild(detail);
      } else {
        // The title is complete; there is no additional detail to disclose.
        const row = document.createElement("div");
        row.className = "readable-plan-summary";
        row.append(title, status);
        body.appendChild(row);
      }
      const actions = document.createElement("div");
      actions.className = "readable-plan-step-actions";
      if (planned?.skill_id) actions.appendChild(createSkillLabel(planned.skill_id));
      if (savedEvents.length) {
        const output = document.createElement("button");
        output.type = "button";
        output.className = "readable-plan-output";
        output.textContent = "View outputs →";
        output.setAttribute("aria-label", `View outputs for ${rawTitle}`);
        output.addEventListener("click", () => {
          // A step can have retries and multiple executions; open its first cell.
          focusCodeExecution(savedEvents[0].details.execution_id);
        });
        actions.appendChild(output);
      }
      if (actions.childElementCount) body.appendChild(actions);
      item.append(marker, body);
    }
  }
  card.append(heading, content);
  return card;
}

function groupConversationExecutions(openGroups) {
  const rows = [...els.conversationFeed.children];
  const isExecution = row => row?.matches(".message-execution.message-agent-mr");
  for (let index = 0; index < rows.length; index += 1) {
    const first = rows[index];
    if (!isExecution(first)) continue;
    const rest = [];
    while (isExecution(rows[index + 1])
        && rows[index + 1].dataset.taskId === first.dataset.taskId) {
      rest.push(rows[++index]);
    }
    if (!rest.length) continue;
    const panel = document.createElement("div");
    panel.className = "conversation-executions";
    const details = document.createElement("details");
    details.className = "conversation-execution-rest";
    details.dataset.executionGroup = first.dataset.executionId;
    details.open = openGroups.get(first.dataset.executionId) || false;
    const summary = document.createElement("summary");
    const updateLabel = () => {
      summary.textContent = `${details.open ? "Hide" : "Show"} ${rest.length} more ${rest.length === 1 ? "cell" : "cells"}`;
    };
    updateLabel();
    details.addEventListener("toggle", updateLabel);
    details.append(summary, ...rest);
    first.replaceWith(panel);
    panel.append(first, details);
  }
}

function renderConversation(snapshot) {
  const scroll = captureConversationScroll();
  const previousCurrent = els.conversationFeed.querySelector('details[data-current-plan="true"]')?.dataset.planId;
  const planOpen = new Map([...els.conversationFeed.querySelectorAll("details[data-plan-id]")].map(node => [node.dataset.planId, node.open]));
  const planDetailOpen = new Map([...els.conversationFeed.querySelectorAll("details[data-plan-detail]")].map(node => [node.dataset.planDetail, node.open]));
  const executionOpen = new Map([...els.conversationFeed.querySelectorAll("details[data-execution-group]")].map(node => [node.dataset.executionGroup, node.open]));
  for (const row of els.conversationFeed.querySelectorAll(".message-report-html")) row.dispose?.();
  els.conversationFeed.replaceChildren();
  const events = snapshot?.mr?.events || [];
  const latestPlan = [...events].reverse().find(event => event.type === "plan_updated");
  const executionNumbers = new Map(codeExecutionEvents(snapshot).map((event, index) => [event.details.execution_id, index + 1]));
  const agentLabel = event => ({manager: "Manager", search: "Search Agent", mr: "MR Agent", report: "Report Agent"}[event.details?.agent] || "MRCAT");
  for (const [index, event] of events.entries()) {
    // The executor emits its optional message immediately before the execution
    // event, whose content repeats that message. Render the execution once.
    const next = events[index + 1];
    if (event.type === "assistant_message" && next?.type === "code_execution"
        && event.content === next.content && event.details?.agent === next.details?.agent
        && event.details?.task_id === next.details?.task_id) continue;
    if (event.type === "plan_updated") {
      const row = appendMessage("assistant", "Plan", "", {kind: "plan"});
      const card = buildReadablePlan(event, event === latestPlan,
        event !== latestPlan && event.id === previousCurrent ? false
          : planOpen.has(event.id) ? planOpen.get(event.id) : event === latestPlan, planDetailOpen, snapshot);
      row.querySelector(".message-body").appendChild(card);
    } else if (event.type === "manager_route" && event.details?.route !== "respond") {
      const role = {search: "Search Agent", mr: "MR Agent", report: "Report Agent"}[event.details?.route] || "MRCAT";
      appendMessage("system", "Manager", `→ ${role}`, {compact: true});
    } else if (["task_created", "task_revised", "task_cancelled"].includes(event.type)) {
      appendMessage("system", "MR task", event.content || "", {compact: true});
    } else if (event.type === "report_started") {
      if (!events.slice(index + 1).some(item => item.type === "report_started" && item.details?.run_id === event.details?.run_id)) {
        renderNativeReport(snapshot, event, events.slice(index + 1));
      }
    } else if (event.type === "report_failed") {
      appendMessage("assistant", "Report Agent · Paused", event.content || "Report interrupted.");
    } else if (event.type === "skill_loaded" && text(event.content)) {
      const row = appendMessage("assistant", `${agentLabel(event)} · Execute`, "", {kind: "skill-guide"});
      row.dataset.agent = event.details?.agent || "";
      row.dataset.taskId = event.details?.task_id || "";
      row.querySelector(".message-body").appendChild(createSkillLabel(text(event.content)));
    } else if (event.type === "code_execution") {
      const d = event.details;
      const number = executionNumbers.get(d.execution_id);
      const row = document.createElement("section");
      row.className = "message assistant message-execution";
      if (d.agent === "mr") row.classList.add("message-agent-mr");
      row.setAttribute("aria-label", `${agentLabel(event)} · Code execution`);
      row.dataset.executionId = d.execution_id;
      row.dataset.agent = d.agent || "";
      row.dataset.taskId = d.task_id || "";
      row.dataset.tone = codeExecutionTone(d);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "codeact-execution-link";
      const icon = document.createElement("span");
      icon.className = "codeact-execution-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = {completed: "✓", failed: "×", running: "◌", neutral: "·"}[row.dataset.tone];
      const status = document.createElement("span");
      status.className = "codeact-execution-status";
      status.textContent = `Cell ${number} · ${codeExecutionStatus(d)}`;
      const view = document.createElement("span");
      view.className = "codeact-execution-view";
      view.textContent = "↗";
      view.setAttribute("aria-hidden", "true");
      button.append(icon, status, view);
      button.title = `View Cell ${number} in Execution notebook`;
      button.setAttribute("aria-label", button.title);
      button.setAttribute("aria-controls", `codeact-cell-${d.execution_id}`);
      button.addEventListener("click", () => focusCodeExecution(d.execution_id));
      row.appendChild(button);
      els.conversationFeed.appendChild(row);
    } else if (["user_message", "assistant_message", "question", "final", "error", "evaluation_failed", "interrupted"].includes(event.type)) {
      const user = event.type === "user_message";
      // MR Review repeats its routing reason after evaluation and optional item acceptance.
      const review = events[index - 1]?.type === "plan_item_completed" ? events[index - 2] : events[index - 1];
      const isReview = event.type === "assistant_message" && event.details?.agent === "mr"
        && review?.type === "evaluation" && review.details?.agent === "mr"
        && review.details?.route === "replan" && review.details?.task_id === event.details?.task_id
        && review.content === event.content;
      const kind = {assistant_message: isReview ? "Review" : "Analysis / update", question: "Question", final: "Answer", error: "Error", evaluation_failed: event.content?.startsWith("MR finalize ") ? "Summary unavailable" : "Review unavailable", interrupted: "Paused"}[event.type];
      const label = user ? "You" : `${agentLabel(event)} · ${kind}`;
      const row = appendMessage(user ? "user" : "assistant", label, codeactArtifactLinks(event.content || "", snapshot), {markdown: !user, kind: event.type === "final" ? "answer" : event.type === "question" ? "question" : undefined});
      if (event.type === "final") bindAnswerArtifactLinks(row, snapshot);
      if (event.type === "final" && event.details?.agent === "report") void renderReportAnswer(row, event, snapshot);
      if (event.type === "question") row.tabIndex = -1;
      if (["final", "question"].includes(event.type) && event.details?.agent === "mr") {
        const tasks = [...(snapshot.mr?.state?.task_history || []), snapshot.mr?.state?.active_task].filter(Boolean);
        const task = tasks.find(task => task.task_id === event.details?.task_id);
        const summary = (task?.artifacts || []).find(path => path.endsWith("/final_summary.md"));
        if (summary && event.content === task.final_summary) {
          const link = document.createElement("a");
          link.className = "mr-summary-download";
          link.href = "data:text/markdown;charset=utf-8," + encodeURIComponent(task.final_summary + "\n");
          link.download = `${task.task_id}_final_summary.md`;
          link.textContent = "Download summary Markdown";
          row.querySelector(".message-body").appendChild(link);
          const generate = document.createElement("button");
          generate.type = "button";
          generate.dataset.reportAction = "generate";
          generate.textContent = "Generate scientific report";
          generate.disabled = Boolean(snapshot.active_job || state.busy);
          generate.addEventListener("click", event => sendReply(event, `Generate a scientific report from the saved MR results for ${task.task_id}.`));
          row.querySelector(".message-body").appendChild(generate);
        }
      }
    }
  }
  if (state.pendingUserMessage && !events.some(e => e.type === "user_message" && e.content === state.pendingUserMessage.text)) appendMessage("user", "You", state.pendingUserMessage.text);
  if (!els.conversationFeed.children.length) appendEmptyConversation(LIVE_DEMO ? "Write a question, or choose an example below and edit it before sending." : "Ask a research question or describe a coding task.");
  groupConversationExecutions(executionOpen);
  for (const guide of els.conversationFeed.querySelectorAll(".message-skill-guide")) {
    const next = guide.nextElementSibling;
    const execution = next?.matches(".conversation-executions") ? next.firstElementChild : next;
    if (!execution?.matches(".message-execution") || execution.dataset.agent !== guide.dataset.agent
        || execution.dataset.taskId !== guide.dataset.taskId) continue;
    guide.classList.add("has-execution");
    const skill = guide.querySelector(".skill-label");
    skill.title = skill.textContent;
    guide.querySelector(".message-body").appendChild(next);
  }
  restoreConversationScroll(scroll);
}

async function renderReportAnswer(row, event, snapshot) {
  const path = event.content?.match(/\]\((workspace\/reports\/[A-Za-z0-9_-]+\/scientific_report\.html)\)/)?.[1];
  if (!path || !notebookOutputFiles(snapshot).some(file => file.path === path)) return;
  const url = artifactRawUrl(snapshot, path);
  if (!url) return;
  const body = row.querySelector(".message-body");
  const controller = new AbortController();
  let resize;
  row.classList.add("message-report-html");
  row.dispose = () => { controller.abort(); resize?.disconnect(); };
  const open = buildExternalLink(url, "Open full report ↗");
  const loading = document.createElement("p");
  loading.className = "muted";
  loading.textContent = "Loading report…";
  body.replaceChildren(loading, open);
  try {
    const saved = snapshot.final_report;
    let html = saved?.summary === path.replace("scientific_report.html", "final_summary.md") ? saved.html : "";
    if (!html) {
      const response = await fetch(url, {signal: controller.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      html = await response.text();
    }
    if (controller.signal.aborted || !row.isConnected) return;
    if (!html.trim()) throw new Error("Empty report");
    const reportDocument = new DOMParser().parseFromString(html, "text/html");
    const policy = reportDocument.createElement("meta");
    policy.httpEquiv = "Content-Security-Policy";
    policy.content = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none';";
    reportDocument.head.prepend(policy);
    for (const link of reportDocument.querySelectorAll("a[href]")) {
      if (!link.getAttribute("href").startsWith("#")) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
    }
    const frame = window.document.createElement("iframe");
    frame.className = "report-inline-frame";
    frame.title = "Final scientific report";
    frame.dataset.reportPath = path;
    // Same-origin access measures layout; report scripts remain blocked.
    frame.setAttribute("sandbox", "allow-same-origin allow-popups allow-popups-to-escape-sandbox");
    frame.addEventListener("load", () => {
      if (!frame.isConnected || controller.signal.aborted) return;
      const content = frame.contentDocument;
      if (!content?.body) return;
      const fit = () => {
        const height = Math.ceil(content.documentElement.getBoundingClientRect().height);
        if (height > 0 && frame.style.height !== `${height}px`) frame.style.height = `${height}px`;
      };
      resize?.disconnect();
      resize = new ResizeObserver(fit);
      resize.observe(content.body);
      fit();
    });
    frame.srcdoc = "<!doctype html>" + reportDocument.documentElement.outerHTML;
    body.replaceChildren(frame, open);
  } catch (error) {
    if (controller.signal.aborted || !row.isConnected) return;
    loading.textContent = "Report preview unavailable.";
  }
}

function renderNativeReport(snapshot, started, laterEvents) {
  const run = text(started.details?.run_id);
  const prefix = `workspace/reports/${run}/`;
  const files = snapshot.mr?.manifest?.artifacts?.[snapshot.mr.run_id]?.files || [];
  const paths = new Set(files.map(file => file.path));
  const finalPath = prefix + "scientific_report.html";
  const draftPath = prefix + "scientific_report_draft.html";
  const html = paths.has(finalPath) ? finalPath : paths.has(draftPath) ? draftPath : null;
  const stages = laterEvents.filter(event => event.type === "report_stage" && event.details?.run_id === run);
  const last = stages.at(-1)?.details;
  const failed = laterEvents.some(event => event.type === "report_failed" && event.details?.run_id === run);
  const current = started === (snapshot.mr?.events || []).findLast(event => event.type === "report_started");
  const interrupted = current && snapshot.state?.active_agent === "report" && ["paused", "stopped", "failed"].includes(snapshot.state?.status);
  const running = Boolean(current && snapshot.active_job && snapshot.state?.active_agent === "report" && !failed && !paths.has(finalPath));
  const names = {evidence: "Selecting analysis evidence", evidence_selection: "Selecting analysis evidence",
    literature: "Searching and verifying literature", writer: "Writing report", validate: "Checking report format",
    save_draft: "Saving draft", judge: "Reviewing report",
    judge_revision: "Reviewing revised report", revise: "Revising report", writer_revision: "Revising report",
    export: "Exporting report", save_report: "Saving report"};
  const title = paths.has(finalPath) ? "Final report · Review passed" : failed || interrupted ? "Report interrupted" :
    running ? names[last?.stage] || "Preparing report" : html ? "Draft · Review has not passed" : "Report paused";
  const row = appendMessage("assistant", "Report Agent", "", {kind: "report"});
  const card = document.createElement("div"); card.className = "scientific-report-card";
  const heading = document.createElement("strong"); heading.textContent = title; card.appendChild(heading);
  const actions = document.createElement("div"); actions.className = "scientific-report-actions";
  const addLink = (path, label, download = false) => {
    if (!paths.has(path)) return;
    const link = document.createElement("a"); link.href = artifactRawUrl(snapshot, path);
    link.textContent = label; link.target = "_blank"; link.rel = "noopener";
    if (download) link.download = path.split("/").at(-1);
    actions.appendChild(link);
  };
  if (html) {
    addLink(html, paths.has(finalPath) ? "Open final report" : "Open draft");
    addLink(html, "Download HTML", true);
    addLink(prefix + (paths.has(finalPath) ? "final_summary.md" : "report_draft.md"), "Download Markdown", true);
  }
  addLink(prefix + "report_review.json", "Judge result");
  addLink(prefix + "report_execution.json", "Stage timings");
  if (current && !snapshot.active_job && (failed || interrupted || !html)) {
    const button = document.createElement("button"); button.type = "button";
    button.dataset.reportAction = "continue";
    button.textContent = "Continue report"; button.disabled = state.busy;
    button.addEventListener("click", event => sendReply(event, "Continue the interrupted scientific report."));
    actions.appendChild(button);
  }
  card.appendChild(actions); row.querySelector(".message-body").appendChild(card);
}

function appendEmptyConversation(message) {
  const empty = document.createElement("div");
  empty.className = "empty-note";
  empty.textContent = message || "No session selected.";
  els.conversationFeed.appendChild(empty);
}

function appendMessage(role, label, body, options = {}) {
  const row = document.createElement("section");
  row.className = `message ${role}`;
  if (options.kind) row.classList.add(`message-${options.kind}`);
  if (options.compact) row.classList.add("compact");
  if (options.error) row.classList.add("error");

  const tag = document.createElement("div");
  tag.className = "message-tag";
  const agentKind = messageAgentIconKind(label);
  if (agentKind) {
    row.classList.add(`message-agent-${agentKind}`);
    tag.appendChild(createAgentIcon(agentKind));
    const tagLabel = document.createElement("span");
    tagLabel.textContent = label;
    tag.appendChild(tagLabel);
  } else {
    tag.textContent = label;
  }
  row.appendChild(tag);

  const content = document.createElement("div");
  content.className = "message-body";
  if (options.markdown) {
    row.classList.add("markdown-message");
    content.innerHTML = renderMarkdown(normalizeMessageParagraphs(body));
  } else if (options.html) {
    row.classList.add("markdown-message");
    content.innerHTML = body || "";
  } else {
    content.textContent = body || "";
  }
  row.appendChild(content);
  els.conversationFeed.appendChild(row);
  return row;
}

function parseSearchReportMarkdown(value) {
  const source = String(value || "").replace(/\r\n?/g, "\n").trim();
  if (!source) return null;

  const preamble = [];
  const sections = [];
  let currentSection = null;
  for (const line of source.split("\n")) {
    const heading = line.match(/^\s{0,3}##\s+(.+?)\s*$/);
    if (heading) {
      if (currentSection) {
        currentSection.markdown = cleanSearchReportSectionBody(currentSection.lines);
        delete currentSection.lines;
        sections.push(currentSection);
      }
      currentSection = { heading: heading[1], lines: [] };
      continue;
    }
    if (currentSection) currentSection.lines.push(line);
    else preamble.push(line);
  }
  if (currentSection) {
    currentSection.markdown = cleanSearchReportSectionBody(currentSection.lines);
    delete currentSection.lines;
    sections.push(currentSection);
  }
  if (sections.length < 2) return null;

  let query = "";
  let title = "";
  const introLines = [...preamble];
  const queryIndex = introLines.findIndex((line) => /^\s*Search query\s*:/i.test(line));
  if (queryIndex >= 0) {
    query = introLines[queryIndex].replace(/^\s*Search query\s*:\s*/i, "").trim();
    introLines.splice(queryIndex, 1);
  }
  const titleIndex = introLines.findIndex((line) => /^\s{0,3}#\s+/.test(line));
  if (titleIndex >= 0) {
    title = introLines[titleIndex].replace(/^\s{0,3}#\s+/, "").trim();
    introLines.splice(titleIndex, 1);
  }

  const referenceSections = sections.filter((section) => isSearchReferencesHeading(section.heading));
  const referenceCount = referenceSections.reduce(
    (count, section) => count + ((section.markdown.match(/^\s*(?:[-*]\s*)?\[\d+\]\s+/gm) || []).length),
    0,
  );
  return {
    title: title || "Search findings",
    query,
    introMarkdown: cleanSearchReportSectionBody(introLines),
    sections,
    mainSectionCount: sections.length - referenceSections.length,
    referenceCount,
  };
}

function cleanSearchReportSectionBody(lines) {
  const cleanLines = [...lines];
  while (cleanLines.length > 0 && (!text(cleanLines[0]) || text(cleanLines[0]) === "---")) {
    cleanLines.shift();
  }
  while (
    cleanLines.length > 0
    && (!text(cleanLines[cleanLines.length - 1]) || text(cleanLines[cleanLines.length - 1]) === "---")
  ) {
    cleanLines.pop();
  }
  return cleanLines.join("\n").trim();
}

function isSearchReferencesHeading(value) {
  return text(value).replace(/^\d+[.)]\s*/, "").replace(/:$/, "").toLowerCase() === "references";
}

function searchReportDisplayHeading(value) {
  const original = text(value);
  const match = original.match(/^(\d+[.)])\s*(.+)$/);
  const prefix = match ? `${match[1]} ` : "";
  const heading = text(match ? match[2] : original);
  const replacements = {
    "direct evidence found": "Primary Mendelian Randomization Evidence",
    "related or indirect evidence": "Supporting Genetic and Contextual Evidence",
    "relevant datasets or gwas sources": "GWAS Data Resources",
    "evidence gaps and uncertainty": "Limitations and Evidence Gaps",
    "brief mr handoff": "Recommended MR Analysis Plan",
  };
  return `${prefix}${replacements[heading.replace(/:.*$/, "").toLowerCase()] || heading}`;
}

function searchReportSectionKind(value) {
  const heading = text(value).replace(/^\d+[.)]\s*/, "").replace(/:.*$/, "").toLowerCase();
  const kinds = {
    "direct evidence found": "evidence",
    "primary mendelian randomization evidence": "evidence",
    "related or indirect evidence": "supporting",
    "supporting genetic and contextual evidence": "supporting",
    "relevant datasets or gwas sources": "database",
    "gwas data resources": "database",
    "evidence gaps and uncertainty": "warning",
    "limitations and evidence gaps": "warning",
    "brief mr handoff": "workflow",
    "recommended mr analysis plan": "workflow",
    references: "references",
  };
  return kinds[heading] || "supporting";
}

function searchReportSectionCountLabel(section) {
  if (!isSearchReferencesHeading(section?.heading)) return "";
  const count = Array.isArray(section.references) ? section.references.length
    : (text(section.markdown).match(/^\s*(?:[-*]\s*)?\[\d+\]\s+/gm) || []).length;
  return count > 0 ? `${count} reference${count === 1 ? "" : "s"}` : "";
}

function searchReportKeyFinding(report) {
  const primary = report?.sections?.find((section) => searchReportSectionKind(section?.heading) === "evidence");
  const match = text(primary?.markdown).match(/^\s*[-*+]\s+(.+)$/m);
  return text(match?.[1]);
}

function buildSearchReportKeyFinding(report) {
  const finding = searchReportKeyFinding(report);
  if (!finding) return null;
  const panel = document.createElement("section");
  panel.className = "search-report-key-finding";
  panel.appendChild(createUiIcon("evidence"));
  const copy = document.createElement("div");
  const label = document.createElement("span");
  label.textContent = "Key finding";
  const body = document.createElement("div");
  body.innerHTML = renderMarkdown(finding);
  copy.appendChild(label);
  copy.appendChild(body);
  panel.appendChild(copy);
  return panel;
}

function buildSearchSourceResources(markdown) {
  const sourceIds = sourceIdsInValue(markdown);
  if (sourceIds.length === 0) return null;
  const resources = document.createElement("div");
  resources.className = "search-source-resources";
  for (const sourceId of sourceIds) {
    const definition = SOURCE_REGISTRY[sourceId];
    const link = document.createElement("a");
    link.className = `search-source-card source-${sourceId}`;
    link.href = definition.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.appendChild(createSourceIcon(sourceId));
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = definition.label;
    const description = document.createElement("span");
    description.textContent = definition.description;
    copy.appendChild(title);
    copy.appendChild(description);
    link.appendChild(copy);
    const arrow = document.createElement("span");
    arrow.className = "search-source-card-arrow";
    arrow.textContent = "↗";
    arrow.setAttribute("aria-hidden", "true");
    link.appendChild(arrow);
    resources.appendChild(link);
  }
  return resources;
}

function parseSearchReferences(markdown) {
  const references = [];
  for (const line of String(markdown || "").split("\n")) {
    const match = line.match(/^\s*(?:[-*]\s*)?\[(\d+)\]\s+\[([^\]]+)\]\((.+)\)\s*$/);
    if (!match) continue;
    const url = sanitizeUrl(match[3]);
    if (!url) continue;
    references.push({ number: match[1], title: match[2], url });
  }
  return references;
}

function sourceIdForUrl(value) {
  let hostname = "";
  try {
    hostname = new URL(value).hostname.toLowerCase();
  } catch {
    return "";
  }
  if (hostname.endsWith("opengwas.io")) return "opengwas";
  if (hostname.endsWith("ebi.ac.uk")) return "gwas_catalog";
  if (hostname.endsWith("finngen.fi")) return "finngen";
  if (hostname.includes("pan.ukbb.broadinstitute.org") || hostname.includes("pan-ukb")) return "pan_ukb";
  return "";
}

function buildWebsiteIcon(value) {
  const shell = document.createElement("span");
  shell.className = "website-icon";
  const sourceId = sourceIdForUrl(value);
  if (sourceId) {
    shell.appendChild(createSourceIcon(sourceId, { small: true }));
    return shell;
  }
  let origin = "";
  let hostname = "";
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol)) throw new Error("unsupported protocol");
    origin = url.origin;
    hostname = url.hostname.replace(/^www\./, "");
  } catch {
    hostname = "website";
  }
  const fallback = document.createElement("span");
  fallback.className = "website-icon-fallback";
  fallback.textContent = hostname.slice(0, 1).toUpperCase() || "↗";
  shell.appendChild(fallback);
  if (origin) {
    const image = document.createElement("img");
    image.src = `${origin}/favicon.ico`;
    image.alt = "";
    image.loading = "lazy";
    image.decoding = "async";
    image.addEventListener("load", () => shell.classList.add("has-image"));
    image.addEventListener("error", () => image.remove());
    shell.appendChild(image);
  }
  return shell;
}

function buildSearchReferenceList(markdown, references = parseSearchReferences(markdown)) {
  if (references.length === 0) return null;
  const panel = document.createElement("div");
  panel.className = "search-reference-panel";
  const list = document.createElement("div");
  list.className = "search-reference-list";
  for (const reference of references) {
    let hostname = "Website";
    try {
      hostname = new URL(reference.url).hostname.replace(/^www\./, "");
    } catch {
      hostname = "Website";
    }
    const link = document.createElement("a");
    link.className = "search-reference-item";
    if (reference.id) link.dataset.citationId = reference.id;
    link.href = reference.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.appendChild(buildWebsiteIcon(reference.url));
    const copy = document.createElement("span");
    copy.className = "search-reference-copy";
    const title = document.createElement("strong");
    title.textContent = reference.title;
    const domain = document.createElement("span");
    domain.textContent = `${reference.number}. ${hostname}`;
    copy.appendChild(title);
    copy.appendChild(domain);
    link.appendChild(copy);
    const arrow = document.createElement("span");
    arrow.className = "search-reference-arrow";
    arrow.textContent = "↗";
    arrow.setAttribute("aria-hidden", "true");
    link.appendChild(arrow);
    list.appendChild(link);
  }
  panel.appendChild(list);
  if (references.length > 5) {
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "search-reference-toggle";
    toggle.textContent = `Show all ${references.length} references`;
    toggle.addEventListener("click", () => {
      const expanded = list.classList.toggle("is-expanded");
      toggle.textContent = expanded ? "Show top 5 references" : `Show all ${references.length} references`;
      toggle.setAttribute("aria-expanded", String(expanded));
    });
    panel.appendChild(toggle);
  }
  return panel;
}

function buildSearchReportSectionBody(section) {
  const body = document.createElement("div");
  body.className = "search-report-section-body";
  if (isSearchReferencesHeading(section?.heading)) {
    const references = buildSearchReferenceList(section?.markdown, section?.references);
    if (references) {
      body.appendChild(references);
      return body;
    }
  }
  if (searchReportSectionKind(section?.heading) === "database") {
    const resources = buildSearchSourceResources(section?.markdown);
    if (resources) body.appendChild(resources);
  }
  const markdown = document.createElement("div");
  markdown.className = "search-report-section-markdown";
  markdown.innerHTML = renderMarkdown(section?.markdown);
  body.appendChild(markdown);
  return body;
}

function searchReportEventKey(event, body) {
  return [
    text(state.currentSessionId) || "session",
    text(event?.run_id),
    text(event?.created_at || event?.timestamp),
    compactSummary(body).slice(0, 96),
  ].join("|");
}

function searchReportSectionKey(event, body, section, index) {
  return `${searchReportEventKey(event, body)}|${index}|${text(section?.heading)}`;
}

function buildSearchReportCard(report, event, body) {
  const card = document.createElement("article");
  card.className = "search-report-card";

  const head = document.createElement("div");
  head.className = "search-report-head";
  const identity = document.createElement("div");
  identity.className = "search-report-identity";
  identity.appendChild(createUiIcon("search", { label: "Search findings" }));
  const heading = document.createElement("div");
  heading.className = "search-report-heading";
  const title = document.createElement("strong");
  title.textContent = report.title;
  const meta = document.createElement("span");
  if (report.referenceCount > 0) {
    meta.textContent = `${report.referenceCount} reference${report.referenceCount === 1 ? "" : "s"}`;
  }
  heading.appendChild(title);
  if (meta.textContent) heading.appendChild(meta);
  identity.appendChild(heading);
  head.appendChild(identity);

  const actions = document.createElement("div");
  actions.className = "search-report-actions";
  const expandAll = document.createElement("button");
  expandAll.type = "button";
  expandAll.textContent = "Expand all";
  const collapseAll = document.createElement("button");
  collapseAll.type = "button";
  collapseAll.textContent = "Collapse all";
  actions.appendChild(expandAll);
  actions.appendChild(collapseAll);
  head.appendChild(actions);
  card.appendChild(head);

  if (report.query) {
    const query = document.createElement("div");
    query.className = "search-report-query";
    const label = document.createElement("span");
    label.textContent = "Query";
    const value = document.createElement("code");
    value.textContent = report.query;
    query.appendChild(label);
    query.appendChild(value);
    card.appendChild(query);
  }

  if (report.introMarkdown) {
    const intro = document.createElement("div");
    intro.className = "search-report-intro";
    intro.innerHTML = renderMarkdown(report.introMarkdown);
    card.appendChild(intro);
  }

  const keyFinding = buildSearchReportKeyFinding(report);
  if (keyFinding) card.appendChild(keyFinding);

  const sectionList = document.createElement("div");
  sectionList.className = "search-report-sections";
  const detailsElements = [];
  report.sections.forEach((section, index) => {
    const sectionKey = searchReportSectionKey(event, body, section, index);
    const details = document.createElement("details");
    details.className = "search-report-section";
    if (isSearchReferencesHeading(section.heading)) {
      details.classList.add("is-references");
    }
    details.open = state.expandedSearchReportSections.has(sectionKey);

    const summary = document.createElement("summary");
    const summaryCopy = document.createElement("span");
    summaryCopy.className = "search-report-section-summary";
    const sectionKind = searchReportSectionKind(section.heading);
    summaryCopy.appendChild(createUiIcon(sectionKind));
    const sectionHeading = document.createElement("span");
    sectionHeading.className = "search-report-section-heading";
    const sectionTitle = document.createElement("strong");
    sectionTitle.textContent = searchReportDisplayHeading(section.heading);
    sectionHeading.appendChild(sectionTitle);
    const sectionCount = searchReportSectionCountLabel(section);
    if (sectionCount) {
      const count = document.createElement("span");
      count.textContent = sectionCount;
      sectionHeading.appendChild(count);
    }
    summaryCopy.appendChild(sectionHeading);
    summary.appendChild(summaryCopy);

    const sectionBody = buildSearchReportSectionBody(section);
    details.appendChild(summary);
    details.appendChild(sectionBody);
    details.addEventListener("toggle", () => {
      if (details.open) state.expandedSearchReportSections.add(sectionKey);
      else state.expandedSearchReportSections.delete(sectionKey);
    });
    detailsElements.push({ details, sectionKey });
    sectionList.appendChild(details);
  });
  card.appendChild(sectionList);

  expandAll.addEventListener("click", () => {
    for (const { details, sectionKey } of detailsElements) {
      state.expandedSearchReportSections.add(sectionKey);
      details.open = true;
    }
  });
  collapseAll.addEventListener("click", () => {
    for (const { details, sectionKey } of detailsElements) {
      state.expandedSearchReportSections.delete(sectionKey);
      details.open = false;
    }
  });
  return card;
}

function skillVisualKind(skillId) {
  const normalizedSkillId = text(skillId).toLowerCase();
  if (normalizedSkillId.includes("analysis-sensitivity")) return "sensitivity";
  if (normalizedSkillId.includes("analysis-method-comparison")) return "comparison";
  if (normalizedSkillId.includes("analysis-result-synthesis")) return "report";
  if (normalizedSkillId.startsWith("analysis-")) return "post-analysis";
  if (
    normalizedSkillId.includes("gwas-search")
    || normalizedSkillId.includes("gwas-select")
  ) return "database";
  if (normalizedSkillId.includes("select")) return "select";
  if (normalizedSkillId.includes("download")) return "download";
  if (normalizedSkillId.includes("pair-prepare")) return "pair";
  if (normalizedSkillId.includes("gwas-qc")) return "qc";
  if (normalizedSkillId.includes("prepare")) return "prepare";
  if (normalizedSkillId.includes("synthesis")) return "report";
  if (normalizedSkillId.startsWith("mr-")) return "analysis";
  return "workflow";
}

function studyDisplayTrait(study, fallback = "") {
  return text(
    study?.label
    || study?.trait
    || study?.study_metadata?.trait
    || fallback
  );
}

function studyDisplayId(study) {
  return text(study?.study_id || study?.study_metadata?.study_id);
}

function buildExternalLink(url, label) {
  const link = document.createElement("a");
  link.className = "skill-inline-link";
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = label;
  return link;
}

function formatPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${formatEstimate(number)}%` : "-";
}

function buildMrMethodResultTable(rows, options = {}) {
  const scroll = document.createElement("div");
  scroll.className = "mr-method-result-table";
  const table = document.createElement("table");
  table.setAttribute("aria-label", "MR method results");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const label of ["Method", "Beta", "95% CI", "P value", "IVs"]) {
    const cell = document.createElement("th");
    cell.textContent = label;
    headRow.appendChild(cell);
  }
  head.appendChild(headRow);
  table.appendChild(head);

  const body = document.createElement("tbody");
  for (const result of rows) {
    const row = document.createElement("tr");
    const values = [
      text(result.method) || "MR",
      formatMethodEstimate(result),
      formatMethodConfidenceInterval(result),
      formatPValue(result.pval ?? result.pvalue),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    }
    const ivCell = document.createElement("td");
    const ivCount = document.createElement("strong");
    ivCount.textContent = result.nsnp === undefined || result.nsnp === null ? "-" : formatInteger(result.nsnp);
    ivCell.appendChild(ivCount);
    const thresholdText = methodIvThresholdLabel(result, options);
    if (thresholdText) {
      const thresholdLabel = document.createElement("span");
      thresholdLabel.className = "mr-method-iv-threshold";
      thresholdLabel.textContent = thresholdText;
      ivCell.appendChild(thresholdLabel);
    }
    row.appendChild(ivCell);
    body.appendChild(row);
  }
  table.appendChild(body);
  scroll.appendChild(table);
  return scroll;
}

function methodResultRows(payload) {
  return Array.isArray(payload?.methods)
    ? payload.methods.filter((row) => row && typeof row === "object")
    : [];
}

function methodResultThreshold(result) {
  const threshold = Number(result?.Threshold ?? result?.threshold ?? result?.pvalue_threshold);
  return Number.isFinite(threshold) && threshold > 0 ? threshold : null;
}

function isMrapssMethodRow(result) {
  return text(result?.method).toLowerCase() === "mr-apss";
}

function methodIvThresholdLabel(result, options = {}) {
  if (isMrapssMethodRow(result)) {
    const threshold = mrapssSelectionThreshold(options.snapshot, options.event, options.planItem);
    return threshold === null ? "" : `Selected at p ≤ ${formatThreshold(threshold)}`;
  }
  const threshold = methodResultThreshold(result);
  return threshold === null ? "" : `Method p ≤ ${formatThreshold(threshold)}`;
}

function mrapssSelectionThreshold(snapshot, event, planItem) {
  const currentTaskId = skillResultTaskId(snapshot, event);
  const target = planReferenceTarget(planItem?.input_json?.mrdat_path, currentTaskId);
  if (!target.stepId) return null;
  const events = Array.isArray(snapshot?.mr?.events) ? snapshot.mr.events : [];
  const eventIndex = events.indexOf(event);
  const startIndex = eventIndex >= 0 ? eventIndex - 1 : events.length - 1;
  for (let index = startIndex; index >= 0; index -= 1) {
    const candidate = events[index];
    if (text(candidate?.type || candidate?.message_type) !== "skill_result") continue;
    if (skillResultSkillId(candidate) !== "gwas-pair-prepare") continue;
    if (text(candidate?.task_id) !== target.taskId) continue;
    if (text(candidate?.plan_item_id) !== target.stepId) continue;
    const match = eventText(candidate).match(/(?:^|[\s,;])iv_threshold\s*=\s*([0-9.eE+-]+)/i);
    const threshold = Number(match?.[1]);
    if (Number.isFinite(threshold) && threshold > 0) return threshold;
  }
  const pairPlanItem = planItemForSnapshot(snapshot, target.taskId, target.stepId);
  const threshold = Number(pairPlanItem?.input_json?.iv_threshold);
  return Number.isFinite(threshold) && threshold > 0 ? threshold : null;
}

function formatMethodEstimate(row) {
  const value = Number(row?.["beta.hat"] ?? row?.beta);
  if (!Number.isFinite(value)) return formatEstimate(row?.["beta.hat"] ?? row?.beta);
  return formatEstimate(value);
}

function formatMethodConfidenceInterval(row) {
  const ranges = Array.isArray(row?.ci?.ranges) ? row.ci.ranges : [];
  const range = ranges.find((item) => (
    item
    && Number.isFinite(Number(item.lower))
    && Number.isFinite(Number(item.upper))
  ));
  return range
    ? `${formatEstimate(range.lower)} to ${formatEstimate(range.upper)}`
    : "-";
}

function formatEstimate(value) {
  if (value == null || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return text(value) || "-";
  if (number === 0) return "0";
  if (Math.abs(number) < 0.001 || Math.abs(number) >= 1000) return number.toExponential(2);
  return Number(number.toPrecision(4)).toString();
}

function formatPValue(value) {
  if (value == null || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return text(value) || "-";
  if (number === 0) return "<1e-300";
  if (number < 0.001) return number.toExponential(2);
  return Number(number.toPrecision(3)).toString();
}

function formatThreshold(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return text(value) || "-";
  if (number === 0) return "0";
  if (number < 0.001) {
    const [mantissa, exponent] = number.toExponential(3).split("e");
    return `${Number(mantissa)}e${Number(exponent)}`;
  }
  return Number(number.toPrecision(4)).toString();
}

function buildAggregateAnalysisTable(rows, mediation = false) {
  const scroll = document.createElement("div");
  scroll.className = "aggregate-analysis-table";
  const table = document.createElement("table");
  table.setAttribute("aria-label", mediation ? "MR mediation results" : "Aggregate MR results");
  const columns = mediation
    ? [
      ["Mediator", (row) => text(row.mediator) || "-"],
      ["Method", (row) => text(row.method) || "-"],
      ["Indirect effect", (row) => formatEstimate(row.indirect_effect)],
      ["95% CI", (row) => formatMethodConfidenceInterval({ ci: row.indirect_ci })],
      ["P value", (row) => formatPValue(row.indirect_pval)],
      ["Mediation proportion", (row) => Number.isFinite(Number(row.mediation_proportion)) ? formatPercent(Number(row.mediation_proportion) * 100) : "-"],
    ]
    : [
      ["Exposure", (row) => text(row.exposure || row.trait_x) || "-"],
      ["Outcome", (row) => text(row.outcome || row.trait_y) || "-"],
      ["Analysis", (row) => text(row.analysis_name || row.direction) || "-"],
      ["Method", (row) => text(row.method) || "-"],
      ["Effect", (row) => formatEstimate(row["beta.hat"] ?? row.beta)],
      ["95% CI", (row) => formatMethodConfidenceInterval(row)],
      ["P value", (row) => formatPValue(row.pval ?? row.pvalue)],
      ["IVs", (row) => row.nsnp == null ? "-" : formatInteger(row.nsnp)],
    ];
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach(([label]) => {
    const cell = document.createElement("th");
    cell.textContent = label;
    headRow.appendChild(cell);
  });
  head.appendChild(headRow);
  table.appendChild(head);
  const body = document.createElement("tbody");
  rows.forEach((row) => {
    const tableRow = document.createElement("tr");
    columns.forEach(([, render]) => {
      const cell = document.createElement("td");
      cell.textContent = render(row);
      tableRow.appendChild(cell);
    });
    body.appendChild(tableRow);
  });
  table.appendChild(body);
  scroll.appendChild(table);
  return scroll;
}

const SKILL_SUMMARY_METRICS = [
  ["canonical_rows", "Canonical rows"],
  ["formatted_rows", "Formatted rows"],
  ["clumped_rows", "Clumped rows"],
  ["mdat_rows", "Mdat rows"],
  ["iv_threshold", "IV threshold"],
  ["fit_input_rows", "Fit instruments"],
  ["nsnp", "Instruments"],
  ["nvalid", "Valid instruments"],
  ["beta.hat", "Beta"],
  ["beta", "Beta"],
  ["se", "SE"],
  ["pval", "P value"],
  ["pvalue", "P value"],
  ["plots", "Plots"],
  ["rows", "Rows"],
];

function extractSkillSummaryMetrics(value) {
  const summary = text(value);
  const metrics = [];
  const seen = new Set();
  const add = (key, label, rawValue) => {
    const normalizedKey = key === "beta.hat"
      ? "beta"
      : (["pval", "pvalue"].includes(key) ? "pvalue" : key);
    if (seen.has(normalizedKey) || rawValue === undefined || rawValue === null || !text(rawValue)) return;
    seen.add(normalizedKey);
    metrics.push({ key: normalizedKey, label, value: formatSkillMetricValue(normalizedKey, rawValue) });
  };

  const candidateMatch = summary.match(/found\s+([\d,]+)\s+downloadable candidate/i);
  if (candidateMatch) add("candidates", "Candidates", candidateMatch[1]);
  const selectionMatch = summary.match(/selected\s+([\d,]+)\s+reusable stud/i);
  if (selectionMatch) add("selected", "Selected studies", selectionMatch[1]);

  for (const [key, label] of SKILL_SUMMARY_METRICS) {
    const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = new RegExp(`(?:^|[\\s,(;])${escaped}\\s*=\\s*([^,;\\s.)]+)`, "i");
    const match = summary.match(pattern);
    if (match) add(key, label, match[1]);
  }

  const canonical = numericMetric(metrics, "canonical_rows");
  const formatted = numericMetric(metrics, "formatted_rows");
  if (canonical > 0 && formatted >= 0) {
    add("retained", "Rows retained", `${(formatted / canonical) * 100}%`);
  }
  return metrics;
}

function numericMetric(metrics, key) {
  const metric = metrics.find((item) => item.key === key);
  if (!metric) return Number.NaN;
  return Number(String(metric.value).replaceAll(",", "").replace("%", ""));
}

function formatSkillMetricValue(key, value) {
  const raw = text(value);
  if (raw.endsWith("%")) {
    const percent = Number(raw.slice(0, -1));
    return Number.isFinite(percent) ? `${percent.toFixed(percent < 1 ? 2 : 1)}%` : raw;
  }
  const number = Number(raw.replaceAll(",", ""));
  if (!Number.isFinite(number)) return raw;
  if (key === "iv_threshold") return formatThreshold(number);
  if (["beta", "beta.hat", "se", "pval", "pvalue"].includes(key)) {
    if (number === 0) return "0";
    if (Math.abs(number) < 0.001) return number.toExponential(2);
    return Number(number.toPrecision(4)).toString();
  }
  return formatInteger(number);
}

function buildSkillMetricGrid(metrics, options = {}) {
  const grid = document.createElement("div");
  grid.className = "skill-summary-metrics";
  const limit = Math.max(1, Number(options.limit) || 4);
  for (const metric of metrics.slice(0, limit)) {
    const item = document.createElement("div");
    item.className = "skill-summary-metric";
    const value = document.createElement("strong");
    value.textContent = metric.value;
    const label = document.createElement("span");
    label.textContent = metric.label;
    item.appendChild(value);
    item.appendChild(label);
    grid.appendChild(item);
  }
  return grid;
}

function skillMetric(metrics, ...keys) {
  return metrics.find((metric) => keys.includes(metric.key)) || null;
}

function buildQcRetentionVisual(metrics) {
  const canonicalMetric = skillMetric(metrics, "canonical_rows");
  const formattedMetric = skillMetric(metrics, "formatted_rows");
  const retainedMetric = skillMetric(metrics, "retained");
  const canonical = numericMetric(metrics, "canonical_rows");
  const formatted = numericMetric(metrics, "formatted_rows");
  if (!canonicalMetric || !formattedMetric || !Number.isFinite(canonical) || canonical <= 0) return null;
  const retained = Math.max(0, Math.min(100, (formatted / canonical) * 100));
  const visual = document.createElement("div");
  visual.className = "skill-retention-visual";

  const values = document.createElement("div");
  values.className = "skill-retention-values";
  for (const [labelText, metric] of [["Canonical", canonicalMetric], ["Formatted", formattedMetric]]) {
    const value = document.createElement("div");
    const label = document.createElement("span");
    label.textContent = labelText;
    const number = document.createElement("strong");
    number.textContent = metric.value;
    value.appendChild(label);
    value.appendChild(number);
    values.appendChild(value);
  }

  const progress = document.createElement("div");
  progress.className = "skill-retention-progress";
  const progressHead = document.createElement("div");
  const progressLabel = document.createElement("span");
  progressLabel.textContent = "Rows retained";
  const progressValue = document.createElement("strong");
  progressValue.textContent = retainedMetric?.value || `${retained.toFixed(retained < 1 ? 2 : 1)}%`;
  progressHead.appendChild(progressLabel);
  progressHead.appendChild(progressValue);
  const track = document.createElement("div");
  track.className = "skill-retention-track";
  track.setAttribute("role", "progressbar");
  track.setAttribute("aria-label", "Rows retained after quality control");
  track.setAttribute("aria-valuemin", "0");
  track.setAttribute("aria-valuemax", "100");
  track.setAttribute("aria-valuenow", retained.toFixed(2));
  const fill = document.createElement("span");
  fill.style.width = `${retained}%`;
  track.appendChild(fill);
  progress.appendChild(progressHead);
  progress.appendChild(track);
  visual.appendChild(values);
  visual.appendChild(progress);
  return visual;
}

function planReferenceTarget(value, currentTaskId) {
  const reference = text(value);
  if (reference.startsWith("$ref:")) {
    return {
      taskId: text(currentTaskId),
      stepId: text(reference.slice(5).split("/")[0]),
    };
  }
  if (reference.startsWith("$taskref:")) {
    const parts = reference.slice(9).split("/").filter(Boolean);
    return { taskId: text(parts.shift()), stepId: text(parts.shift()) };
  }
  return { taskId: text(currentTaskId), stepId: "" };
}

function buildPairPreparationVisual(metrics, studies = {}) {
  const visual = document.createElement("div");
  visual.className = "skill-pair-visual";
  const flow = document.createElement("div");
  flow.className = "skill-pair-flow";
  const inputs = document.createElement("div");
  inputs.className = "skill-pair-inputs";
  for (const [role, labelText] of [["exposure", "Exposure"], ["outcome", "Outcome"]]) {
    const study = studies?.[role] && typeof studies[role] === "object" ? studies[role] : {};
    const node = document.createElement("div");
    node.className = "skill-pair-node";
    node.appendChild(
      text(study?.source)
        ? createSourceIcon(study.source, { small: true })
        : createUiIcon("database", { label: labelText }),
    );
    const copy = document.createElement("div");
    const label = document.createElement("span");
    label.className = "skill-pair-node-role";
    label.textContent = labelText;
    const title = document.createElement("strong");
    title.textContent = studyDisplayTrait(study, `${labelText} dataset`);
    const meta = document.createElement("span");
    meta.className = "skill-pair-node-meta";
    meta.textContent = [
      studyDisplayId(study),
      sourceDefinition(study?.source)?.label,
    ].filter(Boolean).join(" · ") || "Study ID unavailable";
    copy.appendChild(label);
    copy.appendChild(title);
    copy.appendChild(meta);
    node.appendChild(copy);
    inputs.appendChild(node);
  }
  const connector = document.createElement("span");
  connector.className = "skill-pair-connector";
  connector.setAttribute("aria-hidden", "true");
  const output = document.createElement("div");
  output.className = "skill-pair-node is-output";
  output.appendChild(createUiIcon("pair", { label: "Preprocessed dataset" }));
  const outputLabel = document.createElement("span");
  outputLabel.textContent = "Preprocessed dataset";
  output.appendChild(outputLabel);
  flow.appendChild(inputs);
  flow.appendChild(connector);
  flow.appendChild(output);
  visual.appendChild(flow);
  const harmonized = skillMetric(metrics, "mdat_rows");
  const clumped = skillMetric(metrics, "clumped_rows");
  const ivThreshold = skillMetric(metrics, "iv_threshold");
  if (harmonized && clumped) {
    const retention = document.createElement("div");
    retention.className = `skill-pair-retention${ivThreshold ? " has-threshold" : ""}`;
    const stages = [
      ["Harmonized SNPs", harmonized],
      ...(ivThreshold ? [["P-value threshold", ivThreshold]] : []),
      ["Clumped SNPs", clumped],
    ];
    for (const [labelText, metric] of stages) {
      const stage = document.createElement("div");
      const value = document.createElement("strong");
      value.textContent = metric.key === "iv_threshold" ? `p ≤ ${metric.value}` : metric.value;
      const label = document.createElement("span");
      label.textContent = labelText;
      stage.appendChild(value);
      stage.appendChild(label);
      retention.appendChild(stage);
    }
    visual.appendChild(retention);
    const note = document.createElement("p");
    note.className = "skill-pair-method-note";
    note.textContent = "Final IV selection is method-specific.";
    visual.appendChild(note);
  } else if (metrics.length > 0) {
    visual.appendChild(buildSkillMetricGrid(metrics, { limit: 3 }));
  }
  return visual;
}

function buildSkillDataPreview(views, snapshot, options = {}) {
  const panel = document.createElement("section");
  panel.className = `skill-data-preview${options.compact ? " is-compact" : ""}`;
  const head = document.createElement("div");
  head.className = "skill-data-preview-head";
  const selector = document.createElement("div");
  selector.className = "skill-data-preview-tabs";
  const actions = document.createElement("div");
  actions.className = "skill-data-preview-actions";
  const body = document.createElement("div");
  body.className = "skill-data-preview-body";
  const description = document.createElement("p");
  description.className = "skill-data-preview-description";
  const buttons = [];
  let requestVersion = 0;

  const showView = (index) => {
    const view = views[index];
    if (!view) return;
    requestVersion += 1;
    const currentVersion = requestVersion;
    for (const [buttonIndex, button] of buttons.entries()) {
      button.classList.toggle("is-active", buttonIndex === index);
      button.setAttribute("aria-pressed", String(buttonIndex === index));
    }
    description.textContent = view.description;
    actions.replaceChildren();
    const download = document.createElement("a");
    download.href = artifactRawUrl(snapshot, view.artifact.path);
    download.download = artifactBasename(view.artifact.path);
    download.textContent = "Download full data";
    actions.appendChild(download);
    body.classList.remove("has-table");
    body.textContent = "Loading data preview...";
    void loadTableArtifact(snapshot, view.artifact.path)
      .then((payload) => {
        if (currentVersion !== requestVersion) return;
        renderSpreadsheetPreview(body, payload, { maxRows: options.compact ? 5 : 50 });
        body.classList.add("has-table");
      })
      .catch((error) => {
        if (currentVersion !== requestVersion) return;
        body.textContent = `Data preview failed to load: ${error.message}`;
      });
  };

  for (const [index, view] of views.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.path = view.artifact.path;
    button.textContent = view.label;
    button.addEventListener("click", () => showView(index));
    buttons.push(button);
    selector.appendChild(button);
  }
  head.appendChild(selector);
  head.appendChild(actions);
  panel.appendChild(head);
  panel.appendChild(description);
  panel.appendChild(body);
  showView(0);
  return panel;
}

function loadJsonArtifact(snapshot, path, phase = "mr", version = "") {
  const baseUrl = artifactRawUrl(snapshot, path, phase);
  const url = baseUrl && version ? `${baseUrl}${baseUrl.includes("?") ? "&" : "?"}v=${encodeURIComponent(version)}` : baseUrl;
  if (!url) return Promise.reject(new Error("Artifact URL is unavailable."));
  const cached = state.jsonArtifactCache.get(url);
  if (cached) return cached;
  const request = requestJson(url);
  state.jsonArtifactCache.set(url, request);
  void request.catch(() => {
    if (state.jsonArtifactCache.get(url) === request) {
      state.jsonArtifactCache.delete(url);
    }
  });
  return request;
}

function renderGwasSearchShortlistTable(container, payload) {
  container.replaceChildren();
  container.classList.remove("has-table");
  const candidates = Array.isArray(payload?.candidates)
    ? payload.candidates.filter((item) => item && typeof item === "object" && !Array.isArray(item))
    : [];
  if (candidates.length === 0) {
    container.textContent = "No shortlist candidates were returned.";
    return 0;
  }

  const flattened = candidates.map((candidate) => flattenShortlistCandidate(candidate));
  const headers = [];
  const seenHeaders = new Set();
  for (const candidate of flattened) {
    for (const key of Object.keys(candidate)) {
      if (seenHeaders.has(key)) continue;
      seenHeaders.add(key);
      headers.push(key);
    }
  }

  const scroll = document.createElement("div");
  scroll.className = "gwas-search-shortlist-scroll";
  const table = document.createElement("table");
  table.className = "gwas-search-shortlist-table";
  const tableHead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const header of ["Rank", ...headers]) {
    const cell = document.createElement("th");
    cell.textContent = header;
    headRow.appendChild(cell);
  }
  tableHead.appendChild(headRow);
  table.appendChild(tableHead);

  const tableBody = document.createElement("tbody");
  for (const [index, candidate] of flattened.entries()) {
    const row = document.createElement("tr");
    const rank = document.createElement("td");
    rank.textContent = String(index + 1);
    row.appendChild(rank);
    for (const header of headers) {
      const value = candidate[header];
      const cell = document.createElement("td");
      const normalizedHeader = header.toLowerCase();
      if (normalizedHeader === "source" || normalizedHeader.endsWith(".source")) {
        cell.appendChild(createSourceBadge(value, { compact: true, link: true }));
      } else if (normalizedHeader.endsWith("sample_size") || normalizedHeader.endsWith(".sample_size")) {
        cell.textContent = formatInteger(value);
      } else if (normalizedHeader === "ancestry" || normalizedHeader.endsWith(".ancestry")) {
        cell.textContent = displayAncestry(value);
      } else {
        cell.textContent = formatShortlistCell(value);
      }
      cell.title = text(cell.textContent);
      row.appendChild(cell);
    }
    tableBody.appendChild(row);
  }
  table.appendChild(tableBody);
  scroll.appendChild(table);
  container.appendChild(scroll);
  container.classList.add("has-table");
  return candidates.length;
}

function flattenShortlistCandidate(candidate) {
  const flattened = {};
  const visit = (value, prefix) => {
    if (Array.isArray(value)) {
      flattened[prefix] = JSON.stringify(value);
      return;
    }
    if (value && typeof value === "object") {
      const entries = Object.entries(value);
      if (entries.length === 0) {
        flattened[prefix] = "{}";
        return;
      }
      for (const [key, nestedValue] of entries) {
        visit(nestedValue, prefix ? `${prefix}.${key}` : key);
      }
      return;
    }
    flattened[prefix] = value;
  };
  visit(candidate, "");
  delete flattened[""];
  return flattened;
}

function formatShortlistCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function formatDuration(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) {
    const precision = seconds < 10 ? 2 : 1;
    return `${seconds.toFixed(precision).replace(/\.?0+$/, "")} s`;
  }
  const totalSeconds = Math.round(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return remainingSeconds > 0 ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
}

function artifactUiIcon(artifact) {
  const kind = text(artifact?.kind || artifactKind(artifact?.path)).toLowerCase();
  if (["tsv", "tsv.gz", "csv", "csv.gz", "xlsx", "json", "jsonl", "rds"].includes(kind)) return "database";
  if (["png", "jpg", "jpeg", "webp", "svg", "pdf"].includes(kind)) return "evidence";
  if (["txt", "log"].includes(kind)) return "workflow";
  return "download";
}

function isPreviewableTableArtifact(artifact) {
  const name = artifactBasename(artifact?.path).toLowerCase();
  return [".xlsx", ".tsv", ".csv", ".tsv.gz", ".csv.gz"].some((suffix) => name.endsWith(suffix));
}

function artifactBelongsToExecutionScope(path, executionScope) {
  const cleanPath = text(path).replaceAll("\\", "/").replace(/\/+$/, "");
  const cleanScope = text(executionScope).replaceAll("\\", "/").replace(/\/+$/, "");
  if (!cleanPath || !cleanScope) return false;
  if (cleanPath === cleanScope || cleanPath.startsWith(`${cleanScope}/`)) return true;
  const scopeTail = cleanScope.split("/skills/").pop();
  return Boolean(scopeTail) && (
    cleanPath.includes(`/skills/${scopeTail}/`)
    || cleanPath.endsWith(`/skills/${scopeTail}`)
  );
}

function artifactBasename(path) {
  const clean = text(path).replaceAll("\\", "/");
  return clean.split("/").filter(Boolean).pop() || clean;
}

function artifactKind(path) {
  const name = artifactBasename(path).toLowerCase();
  for (const suffix of [".tsv.gz", ".txt.gz", ".csv.gz", ".jsonl", ".json", ".tsv", ".csv", ".txt", ".png", ".pdf", ".md", ".rds"]) {
    if (name.endsWith(suffix)) return suffix.slice(1);
  }
  const match = name.match(/\.([a-z0-9]+)$/);
  return match ? match[1] : "file";
}

function artifactRawUrl(snapshot, path, phase = "mr") {
  if (state.example) return exampleArtifactUrl(path);
  const sessionId = text(state.currentSessionId || snapshot?.session_id || snapshot?.state?.session_id);
  const summary = text(path);
  if (!sessionId || !summary) return "";
  const artifactPhase = phase === "search" ? "search" : "mr";
  const runId = text(snapshot?.mr?.run_id);
  let url = artifactPhase === "search"
    ? `/api/sessions/${encodeURIComponent(sessionId)}/artifacts/raw?phase=search&summary=${encodeURIComponent(summary)}`
    : `/api/sessions/${encodeURIComponent(sessionId)}/artifacts/raw?phase=mr&summary=${encodeURIComponent(summary)}`;
  if (artifactPhase === "mr" && runId) url += `&run_id=${encodeURIComponent(runId)}`;
  return url;
}

function artifactSpreadsheetUrl(snapshot, summary) {
  if (state.example) return exampleArtifactUrl(summary, true);
  const sessionId = text(state.currentSessionId || snapshot?.session_id || snapshot?.state?.session_id);
  const runId = text(snapshot?.mr?.run_id);
  let url = `/api/sessions/${encodeURIComponent(sessionId)}/artifacts/spreadsheet?phase=mr&summary=${encodeURIComponent(summary)}`;
  if (runId) url += `&run_id=${encodeURIComponent(runId)}`;
  return url;
}

function loadTableArtifact(snapshot, path) {
  const url = artifactSpreadsheetUrl(snapshot, path);
  const cached = state.tableArtifactCache.get(url);
  if (cached) return cached;
  const request = requestJson(url);
  state.tableArtifactCache.set(url, request);
  void request.catch(() => {
    if (state.tableArtifactCache.get(url) === request) {
      state.tableArtifactCache.delete(url);
    }
  });
  return request;
}

function renderSpreadsheetPreview(container, payload, options = {}) {
  container.replaceChildren();
  const sheets = Array.isArray(payload?.sheets) ? payload.sheets : [];
  if (sheets.length === 0) {
    container.textContent = "This workbook has no visible sheets.";
    return;
  }

  const tabs = document.createElement("div");
  tabs.className = "spreadsheet-tabs";
  const tableHost = document.createElement("div");
  tableHost.className = "spreadsheet-table-host";
  const buttons = [];

  const showSheet = (index) => {
    tableHost.replaceChildren();
    for (const [buttonIndex, button] of buttons.entries()) {
      button.classList.toggle("is-active", buttonIndex === index);
    }
    const sheet = sheets[index] || {};
    const wrapper = document.createElement("div");
    wrapper.className = "spreadsheet-table-wrap";
    const table = document.createElement("table");
    table.className = "spreadsheet-table";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    const headers = Array.isArray(sheet.headers) ? sheet.headers : [];
    for (const header of headers) {
      const cell = document.createElement("th");
      cell.textContent = text(header);
      headRow.appendChild(cell);
    }
    head.appendChild(headRow);
    table.appendChild(head);

    const body = document.createElement("tbody");
    const rawRows = Array.isArray(sheet.rows) ? sheet.rows : [];
    const maxRows = Math.max(1, Number(options.maxRows) || rawRows.length || 1);
    const visibleRows = rawRows.slice(0, maxRows);
    for (const rawRow of visibleRows) {
      const row = document.createElement("tr");
      for (const value of Array.isArray(rawRow) ? rawRow : []) {
        const cell = document.createElement("td");
        cell.textContent = value === null || value === undefined ? "" : String(value);
        row.appendChild(cell);
      }
      body.appendChild(row);
    }
    table.appendChild(body);
    wrapper.appendChild(table);
    tableHost.appendChild(wrapper);
    if (sheet.truncated || visibleRows.length < rawRows.length) {
      const caption = document.createElement("caption");
      caption.className = "spreadsheet-preview-label";
      caption.textContent = `Preview · ${visibleRows.length} rows`;
      table.prepend(caption);
    }
  };

  for (const [index, sheet] of sheets.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "spreadsheet-tab";
    button.textContent = text(sheet?.name) || `Sheet ${index + 1}`;
    button.addEventListener("click", () => showSheet(index));
    buttons.push(button);
    tabs.appendChild(button);
  }
  if (sheets.length > 1) container.appendChild(tabs);
  container.appendChild(tableHost);
  showSheet(0);
}

function compactSummary(value) {
  const raw = text(value).replace(/\s+/g, " ");
  return raw.length > 150 ? `${raw.slice(0, 147)}...` : raw;
}

function buildScanTraitTable(side, items, artifactPath, exposureCount, outcomeCount, onToggle = null) {
  const section = document.createElement("section");
  section.className = "candidate-table-section scan-trait-section";
  section.dataset.scanSide = side;
  const heading = document.createElement("h4");
  heading.textContent = side === "exposure" ? "Exposure traits" : "Outcome traits";
  section.appendChild(heading);
  if (items.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-note";
    empty.textContent = "No traits.";
    section.appendChild(empty);
    return section;
  }
  const table = document.createElement("table");
  table.className = "candidate-table scan-trait-table";
  const thead = document.createElement("thead");
  thead.innerHTML = "<tr><th></th><th>Trait</th><th>Aliases</th></tr>";
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  const selection = scanSelectionForArtifact(artifactPath, exposureCount, outcomeCount);
  const selected = new Set(normalizeScanIndices(selection[side], items.length));
  for (const [index, item] of items.entries()) {
    const active = selected.has(index);
    const tr = document.createElement("tr");
    if (active) tr.classList.add("selected");
    const selectCell = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "candidate-select";
    button.textContent = active ? "Selected" : "Select";
    button.dataset.scanIndex = String(index);
    button.setAttribute("aria-pressed", String(active));
    button.setAttribute("aria-label", `${active ? "Deselect" : "Select"} ${side}: ${text(item?.trait)}`);
    button.addEventListener("click", () => {
      if (onToggle) onToggle(side, index);
      else toggleScanTrait(artifactPath, side, index, exposureCount, outcomeCount);
    });
    selectCell.appendChild(button);
    tr.appendChild(selectCell);
    const traitCell = document.createElement("td");
    traitCell.textContent = text(item?.trait) || "-";
    tr.appendChild(traitCell);
    const aliasCell = document.createElement("td");
    aliasCell.textContent = scanTraitAliases(item);
    tr.appendChild(aliasCell);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  section.appendChild(table);
  return section;
}

function scanSelectionForArtifact(path, exposureCount = 0, outcomeCount = 0) {
  const key = text(path) || "__latest_scan_design";
  if (!state.scanSelection[key]) {
    state.scanSelection[key] = {
      exposure: defaultScanIndices(exposureCount),
      outcome: defaultScanIndices(outcomeCount),
    };
  }
  return state.scanSelection[key];
}

function defaultScanIndices(count) {
  return Array.from({ length: Math.max(0, Number(count) || 0) }, (_, index) => index);
}

function normalizeScanIndices(value, count) {
  const limit = Math.max(0, Number(count) || 0);
  const seen = new Set();
  const result = [];
  for (const item of Array.isArray(value) ? value : []) {
    const index = Number(item);
    if (!Number.isInteger(index) || index < 0 || index >= limit || seen.has(index)) continue;
    seen.add(index);
    result.push(index);
  }
  return result.sort((left, right) => left - right);
}

function toggleScanTrait(artifactPath, side, index, exposureCount, outcomeCount) {
  const selection = scanSelectionForArtifact(artifactPath, exposureCount, outcomeCount);
  const current = normalizeScanIndices(selection[side], side === "exposure" ? exposureCount : outcomeCount);
  const active = current.includes(index);
  selection[side] = active
    ? current.filter((item) => item !== index)
    : [...current, index].sort((left, right) => left - right);
  renderConversation(state.snapshot);
  renderExecutionNotebook();
}

function scanTraitAliases(item) {
  const aliases = Array.isArray(item?.aliases) ? item.aliases.map(text).filter(Boolean) : [];
  return aliases.length > 0 ? aliases.join(", ") : "-";
}

function renderStudySetup(snapshot) {
  if (!els.studySetupContent) return;
  const persisted = snapshot?.state?.study_setup && typeof snapshot.state.study_setup === "object"
    ? snapshot.state.study_setup
    : {};
  const draft = state.studySetupDraft;
  if (!draft.dirty) {
    draft.exposures = studyDatasetDrafts(persisted.exposures);
    draft.outcomes = studyDatasetDrafts(persisted.outcomes);
    if (!text(draft.analysisRequest)) {
      draft.analysisRequest = text(snapshot?.state?.question);
    }
    const persistedSources = Array.isArray(persisted.sources)
      ? persisted.sources.filter((id) => state.studySourceOptions.some((option) => option.id === id))
      : [];
    draft.sources = persistedSources.slice(0, 1);
    const persistedMethods = Array.isArray(persisted.methods)
      ? persisted.methods
        .map(normalizeStudyMethodId)
        .filter((id) => state.studyMethodOptions.some((option) => option.id === id))
      : [];
    draft.methods = persistedMethods.length > 0
      ? persistedMethods
      : DEFAULT_STUDY_METHOD_IDS.filter((id) => state.studyMethodOptions.some((option) => option.id === id));
  }

  const status = studySetupStatus(snapshot, draft);
  if (els.studySetupStatus) els.studySetupStatus.textContent = status.label;
  els.studySetupContent.replaceChildren();

  const exposureGroup = buildStudySetupSide(
    "exposure",
    "Exposure datasets",
    draft.exposures,
    status,
    snapshot,
  );
  const outcomeGroup = buildStudySetupSide(
    "outcome",
    "Outcome datasets",
    draft.outcomes,
    status,
    snapshot,
  );
  els.studySetupContent.appendChild(exposureGroup);
  els.studySetupContent.appendChild(outcomeGroup);

  const requestGroup = document.createElement("section");
  requestGroup.className = "study-setup-group";
  const requestLabel = document.createElement("label");
  requestLabel.htmlFor = "study-analysis-request";
  requestLabel.textContent = "Analysis request";
  const requestInput = document.createElement("textarea");
  requestInput.id = "study-analysis-request";
  requestInput.rows = 4;
  requestInput.value = draft.analysisRequest;
  requestInput.placeholder = "Example: Compare all exposures against CAD and prioritize the risk factors using MR-APSS.";
  requestInput.disabled = Boolean(state.busy || status.locked);
  requestInput.addEventListener("input", () => {
    state.studySetupDraft.analysisRequest = requestInput.value;
    state.studySetupDraft.dirty = true;
    syncStudySetupView(snapshot);
  });
  const requestNote = document.createElement("p");
  requestNote.className = "study-setup-note";
  requestNote.textContent = "Specify the pairs. Multiple datasets do not imply all pairs or MVMR.";
  requestNote.hidden = draft.exposures.length <= 1 && draft.outcomes.length <= 1;
  requestGroup.appendChild(requestLabel);
  requestGroup.appendChild(requestInput);
  requestGroup.appendChild(requestNote);
  els.studySetupContent.appendChild(requestGroup);

  const sourceGroup = document.createElement("section");
  sourceGroup.className = "study-setup-group";
  const sourceLabel = document.createElement("label");
  sourceLabel.textContent = "Data source";
  const sourcePicker = document.createElement("div");
  sourcePicker.id = "study-data-source";
  sourcePicker.className = "study-source-picker";
  sourcePicker.setAttribute("role", "radiogroup");
  sourcePicker.setAttribute("aria-label", "Data source");
  const sourceChoices = [
    {
      id: "",
      label: "Automatic",
      description: "Search all supported sources.",
    },
    ...state.studySourceOptions.map((option) => ({
      ...option,
      description: SOURCE_REGISTRY[normalizeSourceId(option.id)]?.description || `${option.label} only`,
    })),
  ];
  for (const option of sourceChoices) {
    const selected = (draft.sources[0] || "") === option.id;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `study-source-option${selected ? " selected" : ""}`;
    button.disabled = Boolean(state.busy || status.locked);
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(selected));
    button.setAttribute("aria-description", option.description);
    button.addEventListener("click", () => {
      state.studySetupDraft.sources = option.id ? [option.id] : [];
      state.studySetupDraft.dirty = true;
      renderStudySetup(snapshot);
      syncStudySetupView(snapshot);
    });

    const visual = document.createElement("span");
    visual.className = "study-source-visual";
    if (option.id) {
      visual.appendChild(createSourceIcon(option.id));
    } else {
      const stack = document.createElement("span");
      stack.className = "source-icon-stack";
      for (const sourceId of SOURCE_ORDER) stack.appendChild(createSourceIcon(sourceId, { small: true }));
      visual.appendChild(stack);
    }
    const copy = document.createElement("span");
    copy.className = "study-source-copy";
    const title = document.createElement("strong");
    title.textContent = option.label;
    copy.appendChild(title);
    const check = document.createElement("span");
    check.className = "study-source-check";
    check.textContent = selected ? "✓" : "";
    check.setAttribute("aria-hidden", "true");
    button.appendChild(visual);
    button.appendChild(copy);
    button.appendChild(check);
    sourcePicker.appendChild(button);
  }
  sourceGroup.appendChild(sourceLabel);
  sourceGroup.appendChild(sourcePicker);
  const sourceHelp = document.createElement("details");
  sourceHelp.className = "study-source-help";
  const sourceHelpTitle = document.createElement("summary");
  sourceHelpTitle.textContent = "About data sources";
  sourceHelp.appendChild(sourceHelpTitle);
  for (const option of sourceChoices) {
    const description = document.createElement("p");
    description.className = "study-setup-note";
    const name = document.createElement("strong");
    name.textContent = `${option.label}: `;
    description.append(name, option.description);
    sourceHelp.appendChild(description);
  }
  sourceGroup.appendChild(sourceHelp);
  els.studySetupContent.appendChild(sourceGroup);

  const methodGroup = document.createElement("section");
  methodGroup.className = "study-setup-group";
  const methodHeading = document.createElement("h4");
  methodHeading.textContent = "MR methods";
  methodGroup.appendChild(methodHeading);
  const methodList = document.createElement("div");
  methodList.className = "study-method-list";
  for (const option of state.studyMethodOptions) {
    const label = document.createElement("label");
    label.className = "study-method-option";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = draft.methods.includes(option.id);
    checkbox.disabled = Boolean(state.busy || status.locked);
    checkbox.addEventListener("change", () => {
      const selected = new Set(state.studySetupDraft.methods);
      if (checkbox.checked) selected.add(option.id);
      else selected.delete(option.id);
      state.studySetupDraft.methods = state.studyMethodOptions
        .map((item) => item.id)
        .filter((id) => selected.has(id));
      state.studySetupDraft.dirty = true;
      syncStudySetupView(snapshot);
    });
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = option.label;
    const description = document.createElement("span");
    description.textContent = option.description;
    copy.appendChild(title);
    copy.appendChild(description);
    label.appendChild(checkbox);
    label.appendChild(copy);
    methodList.appendChild(label);
  }
  methodGroup.appendChild(methodList);
  els.studySetupContent.appendChild(methodGroup);

  const actions = document.createElement("section");
  actions.className = "study-setup-actions";
  const submit = document.createElement("button");
  submit.id = "study-setup-submit";
  submit.type = "button";
  submit.className = "primary-button";
  submit.textContent = state.currentSessionId ? "Run MR" : "Start MR";
  submit.disabled = Boolean(
    state.busy
    || status.locked
    || !studySetupReady(draft),
  );
  submit.addEventListener("click", () => void submitStudySetup());
  actions.appendChild(submit);
  const note = document.createElement("p");
  note.className = "study-setup-note";
  note.textContent = status.note;
  actions.appendChild(note);
  els.studySetupContent.appendChild(actions);
}

function emptyStudyDatasetDraft() {
  return { name: "", file: null, fileRef: "" };
}

function studyDatasetDrafts(value) {
  const datasets = Array.isArray(value)
    ? value
      .filter((item) => item && typeof item === "object")
      .map((item) => ({
        name: text(item.name),
        file: null,
        fileRef: text(item.file_ref),
      }))
      .filter((item) => item.name || item.fileRef)
    : [];
  return datasets.length > 0 ? datasets : [emptyStudyDatasetDraft()];
}

function studyDatasetDefaultName(filename) {
  return basename(filename)
    .replace(/\.(?:gz|bgz)$/i, "")
    .replace(/\.(?:tsv|csv|txt)$/i, "")
    .replaceAll("_", " ")
    .trim();
}

function studyDatasetList(side) {
  return side === "exposure"
    ? state.studySetupDraft.exposures
    : state.studySetupDraft.outcomes;
}

function buildStudySetupSide(side, labelText, datasets, status, snapshot) {
  const group = document.createElement("section");
  group.className = "study-setup-group";
  const heading = document.createElement("h4");
  heading.textContent = labelText;
  group.appendChild(heading);

  const fileLabel = document.createElement("div");
  fileLabel.className = "study-dataset-upload";
  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.multiple = true;
  fileInput.hidden = true;
  fileInput.disabled = Boolean(state.busy || status.locked);
  const chooseFiles = document.createElement("button");
  chooseFiles.type = "button";
  chooseFiles.textContent = "Choose files";
  chooseFiles.setAttribute("aria-label", `Choose ${side} GWAS files`);
  chooseFiles.disabled = fileInput.disabled;
  chooseFiles.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    const selectedFiles = Array.from(fileInput.files || []);
    if (selectedFiles.length === 0) return;
    const additions = selectedFiles.map((file) => ({
      name: studyDatasetDefaultName(file.name),
      file,
      fileRef: "",
    }));
    const current = studyDatasetList(side);
    if (
      current.length === 1
      && !text(current[0].name)
      && !current[0].file
      && !text(current[0].fileRef)
    ) {
      current.splice(0, 1, ...additions);
    } else {
      current.push(...additions);
    }
    state.studySetupDraft.dirty = true;
    renderStudySetup(snapshot);
  });
  fileLabel.append(chooseFiles, fileInput);
  group.appendChild(fileLabel);

  const datasetList = document.createElement("div");
  datasetList.className = "study-dataset-list";
  datasets.forEach((dataset, index) => {
    const row = document.createElement("div");
    row.className = "study-dataset-row";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = dataset.name;
    nameInput.placeholder = `${side === "exposure" ? "Exposure" : "Outcome"} trait name`;
    nameInput.setAttribute("aria-label", `${labelText} ${index + 1} trait name`);
    nameInput.disabled = Boolean(state.busy || status.locked);
    nameInput.addEventListener("input", () => {
      dataset.name = nameInput.value;
      state.studySetupDraft.dirty = true;
      syncStudySetupView(snapshot);
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "study-dataset-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Remove ${side} dataset ${index + 1}`);
    remove.title = "Remove dataset";
    remove.disabled = Boolean(state.busy || status.locked);
    remove.addEventListener("click", () => {
      const current = studyDatasetList(side);
      current.splice(index, 1);
      if (current.length === 0) current.push(emptyStudyDatasetDraft());
      state.studySetupDraft.dirty = true;
      renderStudySetup(snapshot);
    });

    row.append(nameInput, remove);
    const filename = dataset.file?.name || (dataset.fileRef ? basename(dataset.fileRef) : "");
    if (filename) {
      const fileNote = document.createElement("span");
      fileNote.className = "study-dataset-source local";
      fileNote.textContent = filename;
      row.appendChild(fileNote);
    }
    datasetList.appendChild(row);
  });
  group.appendChild(datasetList);

  const addTrait = document.createElement("button");
  addTrait.type = "button";
  addTrait.className = "study-dataset-add";
  addTrait.textContent = "+";
  addTrait.setAttribute("aria-label", `Add ${side} trait`);
  addTrait.title = `Add ${side} trait`;
  addTrait.disabled = Boolean(state.busy || status.locked || datasets.length >= 20);
  addTrait.addEventListener("click", () => {
    studyDatasetList(side).push(emptyStudyDatasetDraft());
    state.studySetupDraft.dirty = true;
    renderStudySetup(snapshot);
  });
  group.appendChild(addTrait);
  return group;
}

function basename(value) {
  const parts = text(value).split(/[\\/]/);
  return parts[parts.length - 1] || "";
}

function normalizeStudyMethodId(value) {
  const normalized = text(value).toLowerCase().replaceAll("-", "_");
  return STUDY_METHOD_ALIASES[normalized] || normalized.replaceAll("_", "-");
}

function studyDatasetRowsValid(datasets) {
  return Array.isArray(datasets)
    && datasets.length > 0
    && datasets.length <= 20
    && datasets.every((dataset) => Boolean(text(dataset?.name)));
}

function studySetupReady(draft) {
  return Boolean(
    studyDatasetRowsValid(draft.exposures)
    && studyDatasetRowsValid(draft.outcomes)
    && text(draft.analysisRequest)
    && draft.methods.length > 0
  );
}

function studySetupStatus(snapshot, draft) {
  const running = Boolean(snapshot?.active_job);
  if (running) {
    return { label: "Running", note: "The current MRCAT task is running.", locked: true };
  }
  if (draft.dirty) {
    return { label: "Draft", note: "Provide every trait label, an analysis request, and at least one method. Uploads remain optional.", locked: false };
  }
  if (studySetupReady(draft)) {
    const exposureCount = draft.exposures.length;
    const outcomeCount = draft.outcomes.length;
    return {
      label: "Ready",
      note: `${exposureCount} exposure dataset${exposureCount === 1 ? "" : "s"} and ${outcomeCount} outcome dataset${outcomeCount === 1 ? "" : "s"} are ready.`,
      locked: false,
    };
  }
  return { label: "Not specified", note: "Add exposure and outcome traits, describe the analysis, and select at least one method.", locked: false };
}

function syncStudySetupView(snapshot) {
  if (els.studySetupStatus) els.studySetupStatus.textContent = "Draft";
  const submit = document.getElementById("study-setup-submit");
  if (submit) {
    submit.disabled = Boolean(
      state.busy
      || Boolean(snapshot?.active_job)
      || !studySetupReady(state.studySetupDraft),
    );
  }
}

function buildDataSearchPanel(dataSearch, artifactPath, onChange = () => renderConversation(state.snapshot)) {
  const panel = document.createElement("div");
  panel.className = "data-search-panel";
  const targets = Array.isArray(dataSearch?.targets)
    ? dataSearch.targets.filter((item) => item && typeof item === "object")
    : [];
  const candidateCount = targets.reduce(
    (total, item) => total + (Array.isArray(item?.candidates) ? item.candidates.length : 0),
    0,
  );

  const title = document.createElement("div");
  title.className = "data-search-summary";
  title.appendChild(createUiIcon("database"));
  const titleCopy = document.createElement("div");
  const titleLabel = document.createElement("strong");
  titleLabel.textContent = "Downloadable GWAS candidates";
  const titleMeta = document.createElement("span");
  titleMeta.textContent = `${targets.length} target${targets.length === 1 ? "" : "s"} · ${formatInteger(candidateCount)} candidate${candidateCount === 1 ? "" : "s"}`;
  titleCopy.appendChild(titleLabel);
  titleCopy.appendChild(titleMeta);
  title.appendChild(titleCopy);
  panel.appendChild(title);

  if (targets.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-note";
    empty.textContent = "No Data Search targets were returned.";
    panel.appendChild(empty);
    return panel;
  }

  const sourceCounts = new Map();
  for (const target of targets) {
    for (const candidate of Array.isArray(target?.candidates) ? target.candidates : []) {
      const rawSource = text(candidate?.source) || "unknown";
      const sourceKey = normalizeSourceId(rawSource) || normalizedSourceToken(rawSource) || "unknown";
      const current = sourceCounts.get(sourceKey) || { count: 0, value: rawSource };
      current.count += 1;
      sourceCounts.set(sourceKey, current);
    }
  }
  const activeFilter = dataSearchSourceFilter(artifactPath, sourceCounts);
  panel.appendChild(buildDataSearchSourceFilters(artifactPath, sourceCounts, candidateCount, activeFilter, onChange));

  const groups = document.createElement("div");
  groups.className = "data-search-target-list";
  targets.forEach((target, index) => {
    groups.appendChild(buildDataSearchTarget(target, artifactPath, index, onChange));
  });
  panel.appendChild(groups);
  return panel;
}

function dataSearchSourceFilter(artifactPath, sourceCounts) {
  const active = text(state.dataSearchSourceFilters.get(artifactPath));
  if (active && sourceCounts.has(active)) return active;
  if (active) state.dataSearchSourceFilters.delete(artifactPath);
  return "";
}

function buildDataSearchSourceFilters(artifactPath, sourceCounts, candidateCount, activeFilter, onChange) {
  const filters = document.createElement("div");
  filters.className = "data-search-source-filters";
  filters.setAttribute("aria-label", "Filter candidates by source");

  const addFilter = (sourceKey, sourceValue, count) => {
    const active = sourceKey === activeFilter;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `data-search-source-filter${active ? " active" : ""}`;
    button.setAttribute("aria-pressed", String(active));
    if (sourceKey) {
      button.appendChild(createSourceBadge(sourceValue, { compact: true, count }));
    } else {
      button.appendChild(createUiIcon("database"));
      const label = document.createElement("span");
      label.textContent = "All sources";
      button.appendChild(label);
      const total = document.createElement("strong");
      total.textContent = formatInteger(count);
      button.appendChild(total);
    }
    button.addEventListener("click", () => {
      if (sourceKey) state.dataSearchSourceFilters.set(artifactPath, sourceKey);
      else state.dataSearchSourceFilters.delete(artifactPath);
      onChange();
    });
    filters.appendChild(button);
  };

  addFilter("", "", candidateCount);
  const orderedKeys = [
    ...SOURCE_ORDER.filter((sourceId) => sourceCounts.has(sourceId)),
    ...Array.from(sourceCounts.keys()).filter((sourceId) => !SOURCE_ORDER.includes(sourceId)).sort(),
  ];
  for (const sourceKey of orderedKeys) {
    const source = sourceCounts.get(sourceKey);
    addFilter(sourceKey, source.value, source.count);
  }
  return filters;
}

function buildDataSearchTarget(target, artifactPath, targetIndex, onChange) {
  const section = document.createElement("section");
  section.className = "candidate-table-section data-search-target";

  const targetSpec = target?.target && typeof target.target === "object" ? target.target : {};
  const resolvedTarget = target?.resolved_target && typeof target.resolved_target === "object"
    ? target.resolved_target
    : {};
  const label = text(targetSpec.trait || targetSpec.study_id || resolvedTarget.value) || `Target ${targetIndex + 1}`;
  const candidates = Array.isArray(target?.candidates)
    ? target.candidates.filter((item) => item && typeof item === "object")
    : [];
  const activeFilter = text(state.dataSearchSourceFilters.get(artifactPath));
  const filteredCandidates = activeFilter
    ? candidates.filter((candidate) => (
      (normalizeSourceId(candidate?.source) || normalizedSourceToken(candidate?.source) || "unknown") === activeFilter
    ))
    : candidates;
  const status = text(target?.status) || (candidates.length > 0 ? "found" : "not_found");
  const head = document.createElement("div");
  head.className = "data-search-target-head";
  const heading = document.createElement("h4");
  heading.textContent = label;
  const meta = document.createElement("span");
  meta.className = `data-search-target-meta ${status.replaceAll("_", "-")}`;
  meta.textContent = status === "found"
    ? (activeFilter
      ? `${filteredCandidates.length} of ${candidates.length} candidates`
      : `${candidates.length} candidate${candidates.length === 1 ? "" : "s"}`)
    : status.replaceAll("_", " ");
  head.appendChild(heading);
  head.appendChild(meta);
  section.appendChild(head);

  if (candidates.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-note";
    empty.textContent = text(target?.summary) || (
      status === "blocked"
        ? "GWAS search was blocked."
        : "No downloadable candidates were found."
    );
    section.appendChild(empty);
    return section;
  }

  if (filteredCandidates.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-note";
    empty.textContent = "No candidates from this source for the current target.";
    section.appendChild(empty);
    return section;
  }

  const expansionKey = `${artifactPath}::${targetIndex}`;
  const expanded = state.expandedDataSearchTargets.has(expansionKey);
  const visibleCandidates = expanded
    ? filteredCandidates
    : filteredCandidates.slice(0, DATA_SEARCH_PREVIEW_LIMIT);
  const tableBody = document.createElement("div");
  tableBody.className = "gwas-search-shortlist-body data-search-shortlist-body";
  renderGwasSearchShortlistTable(tableBody, { candidates: visibleCandidates });
  section.appendChild(tableBody);

  if (filteredCandidates.length > DATA_SEARCH_PREVIEW_LIMIT) {
    const actions = document.createElement("div");
    actions.className = "data-search-target-actions";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "data-search-toggle";
    toggle.textContent = expanded
      ? `Show top ${DATA_SEARCH_PREVIEW_LIMIT}`
      : `Show all ${filteredCandidates.length}`;
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.addEventListener("click", () => {
      if (expanded) state.expandedDataSearchTargets.delete(expansionKey);
      else state.expandedDataSearchTargets.add(expansionKey);
      onChange();
    });
    actions.appendChild(toggle);
    section.appendChild(actions);
  }
  return section;
}

function skillResultSkillId(event, details = {}) {
  return text(event?.skill_id || details.skill_id || details.skill_name || event?.decision_name);
}

function planItemForSnapshot(snapshot, taskId, planItemId) {
  const wantedTask = text(taskId);
  const wanted = text(planItemId);
  if (!wanted) return null;
  for (const task of mrTasksInOrder(snapshot)) {
    if (wantedTask && text(task?.task_id) !== wantedTask) continue;
    const items = Array.isArray(task?.plan?.items) ? task.plan.items : [];
    const match = items.find((item) => text(item?.item_id || item?.id) === wanted);
    if (match) return match;
  }
  return null;
}

function activeMrTask(snapshot) {
  const active = snapshot?.mr?.state?.active_task;
  return active && typeof active === "object" ? active : null;
}

function mrTasksInOrder(snapshot) {
  const mrState = snapshot?.mr?.state;
  if (!mrState || typeof mrState !== "object") return [];
  const tasks = [];
  const seen = new Set();
  const addTask = (task) => {
    const taskId = text(task?.task_id);
    if (!taskId || seen.has(taskId)) return;
    seen.add(taskId);
    tasks.push(task);
  };
  for (const task of Array.isArray(mrState.task_history) ? mrState.task_history : []) {
    if (task && typeof task === "object") addTask(task);
  }
  if (mrState.active_task && typeof mrState.active_task === "object") {
    addTask(mrState.active_task);
  }
  return tasks.sort((left, right) => {
    const leftNo = Number(left?.task_no);
    const rightNo = Number(right?.task_no);
    if (Number.isFinite(leftNo) && Number.isFinite(rightNo) && leftNo !== rightNo) {
      return leftNo - rightNo;
    }
    const leftTime = Date.parse(text(left?.created_at));
    const rightTime = Date.parse(text(right?.created_at));
    if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
      return leftTime - rightTime;
    }
    return 0;
  });
}

function skillResultTaskId(snapshot, event) {
  const direct = text(event?.task_id || event?.details?.task_id);
  if (direct) return direct;
  const eventTime = Date.parse(text(event?.created_at || event?.timestamp));
  if (!Number.isFinite(eventTime)) return "";
  let matchedTaskId = "";
  let matchedStart = Number.NEGATIVE_INFINITY;
  for (const task of mrTasksInOrder(snapshot)) {
    const taskId = text(task?.task_id);
    const startedAt = Date.parse(text(task?.created_at));
    const finishedAt = Date.parse(text(task?.updated_at));
    if (!taskId || !Number.isFinite(startedAt) || eventTime < startedAt) continue;
    const isActive = task === activeMrTask(snapshot);
    if (!isActive && Number.isFinite(finishedAt) && eventTime > finishedAt) continue;
    if (startedAt >= matchedStart) {
      matchedStart = startedAt;
      matchedTaskId = taskId;
    }
  }
  return matchedTaskId;
}

function formatParameterValue(value) {
  if (value === null) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function updateComposer() {
  const running = Boolean(state.snapshot?.active_job);
  const locked = state.busy || running || isReadOnlySession();
  els.newChatButton.disabled = state.busy;
  els.forkSessionButton.disabled = locked || !state.snapshot;
  els.replyInput.disabled = locked; els.replyButton.disabled = locked;
  document.querySelectorAll("[data-search-action]").forEach(button => {
    button.disabled = locked || button.dataset.emptySelection === "true";
  });
  els.stopJobButton.hidden = !running || isReadOnlySession(); els.stopJobButton.disabled = state.busy || !running || isReadOnlySession();
  els.providerSelect.disabled = state.busy || Boolean(state.currentSessionId);
  els.replyButton.textContent = state.currentSessionId ? "Send" : "Start";
  els.replyInput.placeholder = isReadOnlySession() ? "Read-only example · Start a new chat to run an analysis" : running ? `${sessionActivity(state.snapshot).title} · see progress above` : "Describe what you want to do";
  document.querySelectorAll("[data-report-action]").forEach(button => { button.disabled = locked; });
  updateLiveDemo();
}

async function forkCurrentSession() {
  if (!state.currentSessionId || state.busy || state.snapshot?.active_job) return;
  const sourceId = state.currentSessionId;
  setBusy(true);
  els.forkSessionButton.textContent = "Copying session…";
  try {
    const payload = await requestJson(`/api/sessions/${encodeURIComponent(sourceId)}/fork`, { method: "POST" });
    await refreshSessions();
    await selectSession(payload.session.session_id);
  } catch (error) {
    alert(`Copy failed: ${error.message}`);
  } finally {
    els.forkSessionButton.textContent = "Continue in a copy";
    setBusy(false);
  }
}

function applyAcknowledgement(payload) {
  const session = payload?.session;
  if (!session || session.session_id !== state.currentSessionId || !state.snapshot) return;
  if (text(session.state?.updated_at) < text(state.snapshot.state?.updated_at)) return;
  state.snapshot = { ...state.snapshot, state: session.state,
    active_job: session.active_job, latest_job: session.latest_job };
  renderHeader(state.snapshot);
  updateComposer();
}

function refreshAfterCommand() {
  // SSE also delivers the committed state; this GET covers reconnects.
  loadSnapshot().catch(() => { state.activityConnection = "reconnecting"; });
}

async function stopActiveJob() {
  if (!state.currentSessionId || !canStopActiveJob(state.snapshot)) return;
  setBusy(true);
  try {
    const payload = await requestJson(
      `/api/sessions/${encodeURIComponent(state.currentSessionId)}/stop`,
      { method: "POST" },
    );
    applyAcknowledgement(payload);
    state.pendingUserMessage = null;
    refreshAfterCommand();
  } catch (error) {
    alert(`Stop failed: ${error.message}`);
  } finally {
    setBusy(false);
  }
}

async function startSessionWithQuestion(question) {
  state.pendingUserMessage = {
    text: question,
    sessionId: null,
  };
  els.replyInput.value = "";
  renderConversation(state.snapshot);
  setBusy(true);
  try {
    const payload = await requestJson("/api/sessions", apiBody({
      question,
      provider: els.providerSelect.value,
    }));
    const sessionId = payload.session?.session_id || payload.session?.state?.session_id;
    await refreshSessions();
    await selectSession(sessionId);
  } catch (error) {
    state.pendingUserMessage = null;
    els.replyInput.value = question;
    renderConversation(null);
    alert(`Start failed: ${error.message}`);
  } finally {
    setBusy(false);
  }
}

async function sendReply(event, request = null) {
  event.preventDefault();
  if (state.busy) return;
  const reply = request || text(els.replyInput.value);
  if (!reply) return;
  if (LIVE_DEMO && liveDemoSelection) {
    await sendLiveDemoSetup(reply);
    return;
  }
  if (!state.currentSessionId) {
    await startSessionWithQuestion(reply);
    return;
  }

  const snapshot = state.snapshot || {};
  const endpoint = `/api/sessions/${encodeURIComponent(state.currentSessionId)}/mr/reply`;

  state.pendingUserMessage = {
    text: reply,
    sessionId: state.currentSessionId,
  };
  if (!request) els.replyInput.value = "";
  renderConversation(snapshot);
  setBusy(true);
  try {
    applyAcknowledgement(await requestJson(endpoint, apiBody({ reply })));
    refreshAfterCommand();
  } catch (error) {
    state.pendingUserMessage = null;
    if (!request) els.replyInput.value = reply;
    renderConversation(state.snapshot);
    alert(`Reply failed: ${error.message}`);
  } finally {
    setBusy(false);
  }
}

async function submitStudySetup() {
  if (isReadOnlySession()) return;
  const draft = state.studySetupDraft;
  if (!studySetupReady(draft)) return;
  const form = new FormData();
  const exposureManifest = buildStudyDatasetManifest(
    draft.exposures,
    form,
    "exposure_files",
  );
  const outcomeManifest = buildStudyDatasetManifest(
    draft.outcomes,
    form,
    "outcome_files",
  );
  form.append("exposure_manifest", JSON.stringify(exposureManifest));
  form.append("outcome_manifest", JSON.stringify(outcomeManifest));
  form.append("analysis_request", text(draft.analysisRequest));
  form.append("methods", JSON.stringify(draft.methods));
  form.append("sources", JSON.stringify(draft.sources));
  if (!state.currentSessionId) {
    form.append("provider", text(els.providerSelect.value) || "deepseek");
  }
  setBusy(true);
  try {
    const endpoint = state.currentSessionId
      ? `/api/sessions/${encodeURIComponent(state.currentSessionId)}/study-setup`
      : "/api/manual-sessions";
    const response = await requestJson(endpoint, { method: "POST", body: form });
    draft.dirty = false;
    for (const dataset of [...draft.exposures, ...draft.outcomes]) {
      dataset.file = null;
    }
    const sessionId = text(response?.session?.session_id);
    if (!state.currentSessionId && sessionId) {
      await selectSession(sessionId);
    }
    await loadSnapshot();
  } catch (error) {
    alert(`Study setup failed: ${error.message}`);
  } finally {
    setBusy(false);
  }
}

function buildStudyDatasetManifest(datasets, form, fieldName) {
  let fileIndex = 0;
  return datasets.map((dataset) => {
    const item = { name: text(dataset.name) };
    if (dataset.file) {
      item.file_index = fileIndex;
      form.append(fieldName, dataset.file);
      fileIndex += 1;
    } else if (text(dataset.fileRef)) {
      item.file_ref = text(dataset.fileRef);
    }
    return item;
  });
}

function normalizeMessageParagraphs(value) {
  // Repair escaped paragraph breaks in prose while preserving code and single escapes.
  return String(value || "").replace(
    /(```[\s\S]*?(?:```|$)|`[^`]*`)|(\\n){2,}/g,
    (match, code) => code || "\n".repeat(match.length / 2),
  );
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const html = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!text(line)) {
      index += 1;
      continue;
    }

    if (/^\s*```/.test(line)) {
      const code = [];
      index += 1;
      while (index < lines.length && !/^\s*```/.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      html.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }

    const heading = line.match(/^\s{0,3}(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      const table = parseTable(lines, index);
      html.push(table.html);
      index = table.nextIndex;
      continue;
    }

    const list = parseList(lines, index);
    if (list) {
      html.push(list.html);
      index = list.nextIndex;
      continue;
    }

    if (/^\s*>/.test(line)) {
      const quote = [];
      while (index < lines.length && /^\s*>/.test(lines[index])) {
        quote.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      html.push(`<blockquote>${renderMarkdown(quote.join("\n"))}</blockquote>`);
      continue;
    }

    const paragraph = [];
    while (index < lines.length && text(lines[index]) && !isBlockStart(lines, index)) {
      paragraph.push(lines[index]);
      index += 1;
    }
    html.push(`<p>${renderInline(paragraph.join("\n")).replace(/\n/g, "<br>")}</p>`);
  }

  return html.join("\n");
}

function isBlockStart(lines, index) {
  const line = lines[index] || "";
  return /^\s*```/.test(line)
    || /^\s{0,3}#{1,4}\s+/.test(line)
    || /^\s*>/.test(line)
    || /^\s*[-*+]\s+/.test(line)
    || /^\s*\d+[.)]\s+/.test(line)
    || isTableStart(lines, index);
}

function parseList(lines, start) {
  const first = lines[start] || "";
  const ordered = /^\s*\d+[.)]\s+/.test(first);
  const unordered = /^\s*[-*+]\s+/.test(first);
  if (!ordered && !unordered) return null;
  const items = [];
  let index = start;
  const pattern = ordered ? /^\s*\d+[.)]\s+(.+)$/ : /^\s*[-*+]\s+(.+)$/;
  while (index < lines.length) {
    const match = (lines[index] || "").match(pattern);
    if (!match) break;
    items.push(`<li>${renderInline(match[1])}</li>`);
    index += 1;
  }
  const tag = ordered ? "ol" : "ul";
  return { html: `<${tag}>${items.join("")}</${tag}>`, nextIndex: index };
}

function isTableStart(lines, index) {
  const line = lines[index] || "";
  const next = lines[index + 1] || "";
  return line.includes("|") && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(next);
}

function parseTable(lines, start) {
  const headers = splitTableRow(lines[start]);
  let index = start + 2;
  const rows = [];
  while (index < lines.length && lines[index].includes("|") && text(lines[index])) {
    rows.push(splitTableRow(lines[index]));
    index += 1;
  }
  const headHtml = headers.map((cell) => `<th>${renderInline(cell)}</th>`).join("");
  const bodyHtml = rows.map((row) => `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join("")}</tr>`).join("");
  return {
    html: `<div class="table-scroll"><table><thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`,
    nextIndex: index,
  };
}

function splitTableRow(line) {
  let value = String(line || "").trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|")) value = value.slice(0, -1);
  return value.split("|").map((cell) => cell.trim());
}

function renderInline(value) {
  const codeParts = [];
  let source = String(value || "").replace(/`([^`]+)`/g, (_, code) => {
    const token = `\u0000CODE${codeParts.length}\u0000`;
    codeParts.push(`<code>${escapeHtml(code)}</code>`);
    return token;
  });
  source = escapeHtml(source);
  source = source.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, label, rawUrl) => {
    const cleanUrl = sanitizeUrl(rawUrl.replace(/&amp;/g, "&"));
    if (!cleanUrl) return match;
    return `<a href="${escapeAttr(cleanUrl)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });
  source = source.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  source = source.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  source = source.replace(/\u0000CODE(\d+)\u0000/g, (_, index) => codeParts[Number(index)] || "");
  return source;
}

function sanitizeUrl(value) {
  const url = text(value);
  const lower = url.toLowerCase().replace(/\s+/g, "");
  if (!url || lower.startsWith("javascript:") || lower.startsWith("data:") || lower.startsWith("vbscript:")) {
    return "";
  }
  return url;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#96;");
}

function bindEvents() {
  initSidebarResizer();
  initStudySetupResizer();
  initPanelResizers();
  els.sessionsSidebarToggle?.addEventListener("click", () => {
    setSessionsSidebarCollapsed(!state.sessionsSidebarCollapsed);
  });
  els.studySetupToggle?.addEventListener("click", () => {
    setStudySetupCollapsed(!state.studySetupCollapsed);
  });
  els.pendingText.addEventListener("click", focusPendingQuestion);
  els.notebookLatest.addEventListener("click", scrollToLatestNotebookCell);
  els.notebookTaskTab.addEventListener("click", () => setNotebookView("task"));
  els.notebookBuilderTab.addEventListener("click", () => setNotebookView("builder"));
  for (const tab of [els.notebookTaskTab, els.notebookBuilderTab]) {
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const nextView = tab === els.notebookTaskTab ? "builder" : "task";
      setNotebookView(nextView);
      (nextView === "task" ? els.notebookTaskTab : els.notebookBuilderTab).focus();
    });
  }
  els.newChatButton.addEventListener("click", newChat);
  els.forkSessionButton.addEventListener("click", forkCurrentSession);
  els.replyForm.addEventListener("submit", sendReply);
  els.stopJobButton.addEventListener("click", stopActiveJob);
  els.replyInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      els.replyForm.requestSubmit();
    }
  });
  els.refreshButton.addEventListener("click", refreshSessions);
  els.sessionStatusToggle.addEventListener("change", () => {
    setSessionStatusVisible(els.sessionStatusToggle.checked);
  });
  document.addEventListener("visibilitychange", refreshSessionsWhenVisible);

}

async function bootstrap() {
  restoreSessionStatusVisibility();
  bindEvents();
  document.getElementById("result4-example-button").addEventListener("click", openResult4Example);
  setSessionsSidebarCollapsed(false);
  setStudySetupCollapsed(true);
  resetExecutionNotebook();
  if (REPLAY_ONLY) {
    await openResult4Example();
    return;
  }
  await initLiveDemo();
  await loadStudyMethodOptions();
  await refreshSessions();
  if (state.example) {
    // A user may open the example while the initial session list is loading.
  } else if (window.location.hash.slice(1) === RESULT4_EXAMPLE_ID) {
    await openResult4Example();
  } else if (state.sessions.length > 0) {
    const selectedId = window.location.hash.slice(1);
    const selected = state.sessions.find(session => session.session_id === selectedId) || state.sessions[0];
    await selectSession(selected.session_id);
  } else {
    renderHeader(null);
    renderTimeline(null);
    renderStudySetup(null);
    renderConversation(null);
    renderExecutionNotebook();
    updateComposer();
  }
  window.setInterval(refreshSessionsWhenVisible, SESSION_REFRESH_INTERVAL_MS);
  window.setInterval(() => {
    if (!document.hidden) renderActivity(state.snapshot);
  }, 1000);
}

function codeactArtifactLinks(content, snapshot) {
  return content.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, "[$1]($2)").replace(/\]\(<?(?:\.\/)?((?:workspace|executions)\/[^)>]+)>?\)/g, (_, path) => `](${artifactRawUrl(snapshot, path)})`);
}

function bindAnswerArtifactLinks(row, snapshot) {
  const paths = new Set(notebookOutputFiles(snapshot).map(file => file.path));
  const endpoint = `/api/sessions/${encodeURIComponent(state.currentSessionId)}/artifacts/raw`;
  for (const link of row.querySelectorAll("a[href]")) {
    if (link.hasAttribute("download")) continue;
    let url;
    try { url = new URL(link.href, window.location.href); }
    catch { continue; }
    if (url.origin !== window.location.origin || url.pathname !== endpoint
        || (url.searchParams.has("phase") && url.searchParams.get("phase") !== "mr")
        || (url.searchParams.has("run_id") && url.searchParams.get("run_id") !== text(snapshot?.mr?.run_id))) continue;
    const path = url.searchParams.get("summary");
    if (!paths.has(path)) continue;
    link.dataset.artifactPath = path;
    link.title = "View referenced output in the results panel";
    link.setAttribute("aria-controls", "notebook-output");
    link.addEventListener("click", event => {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      if (focusNotebookArtifact(path)) event.preventDefault();
    });
  }
}

bootstrap().catch((error) => {
  els.statusChip.setAttribute("role", "alert");
  els.statusChip.textContent = `boot failed: ${error.message}`;
});
