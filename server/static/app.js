const form = document.getElementById("claim-form");
const input = document.getElementById("claim-input");
const submitBtn = document.getElementById("submit-btn");
const exampleChips = document.querySelectorAll(".example-chip");

// Plain <textarea> doesn't auto-grow — with a fixed native height (from
// rows="1") and resize:none, a claim that wraps to a second line was
// getting clipped at the box's bottom edge instead of the box growing to
// fit it. min-height/max-height in CSS just bound this; they don't cause
// it to happen.
function autoGrowInput() {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
}
input.addEventListener("input", autoGrowInput);

const traceSection = document.getElementById("trace");
const traceList = document.getElementById("trace-list");

const verdictSection = document.getElementById("verdict");
const unresolvedBox = document.getElementById("verdict-unresolved");
const unresolvedReason = document.getElementById("verdict-unresolved-reason");
const resolvedBox = document.getElementById("verdict-resolved");

const verdictStamp = document.getElementById("verdict-stamp");
const verdictCaseId = document.getElementById("verdict-case-id");
const verdictSummary = document.getElementById("verdict-summary");
const directionMarker = document.getElementById("direction-marker");
const meterCoverage = document.getElementById("meter-coverage");
const findingTallyRow = document.getElementById("finding-tally-row");
const tallyContradicts = document.getElementById("tally-contradicts");
const tallyContext = document.getElementById("tally-context");
const tallySupports = document.getElementById("tally-supports");
const findingTallyLabel = document.getElementById("finding-tally-label");
const directionValue = document.getElementById("direction-value");
const coverageValue = document.getElementById("coverage-value");
const confidenceExplanation = document.getElementById("confidence-explanation");
const contradictingList = document.getElementById("contradicting-list");
const supportingList = document.getElementById("supporting-list");
const gapsSection = document.getElementById("gaps-section");
const gapsList = document.getElementById("gaps-list");
const subClaimsSection = document.getElementById("sub-claims-section");
const subClaimsList = document.getElementById("sub-claims-list");
const sources = document.getElementById("sources");

const locationPanel = document.getElementById("location-panel");
const locationCaption = document.getElementById("location-caption");
const timelapseLink = document.getElementById("timelapse-link");
const timelapseEmbed = document.getElementById("timelapse-embed");
const mapFrame = document.getElementById("map-frame");
const mapLegendOverlay = document.getElementById("map-legend-overlay");
const mapModeBtns = document.querySelectorAll(".map-mode-btn");
const layersToggleBtn = document.getElementById("layers-toggle-btn");
const fullscreenBtn = document.getElementById("fullscreen-btn");

const claimResultHeader = document.getElementById("claim-result-header");
const claimResultTitle = document.getElementById("claim-result-title");
const metaLocation = document.getElementById("meta-location");
const metaPlace = document.getElementById("meta-place");
const metaDatetime = document.getElementById("meta-datetime");

const shareBtn = document.getElementById("share-btn");
const exportBtn = document.getElementById("export-btn");
const helpBtn = document.getElementById("help-btn");
const themeBtn = document.getElementById("theme-btn");

const evidenceOverviewSection = document.getElementById("evidence-overview");
const cardLandValue = document.getElementById("card-land-value");
const cardLandContext = document.getElementById("card-land-context");
const cardVegetationSub = document.getElementById("card-vegetation-sub");
const cardVegetationValue = document.getElementById("card-vegetation-value");
const cardVegetationContext = document.getElementById("card-vegetation-context");
const cardWaterValue = document.getElementById("card-water-value");
const cardCarbonValue = document.getElementById("card-carbon-value");
const cardCarbonContext = document.getElementById("card-carbon-context");
const cardEcologyValue = document.getElementById("card-ecology-value");
const cardEcologyContext = document.getElementById("card-ecology-context");

const timelineSection = document.getElementById("timeline-section");
const timelineSteps = document.getElementById("timeline-steps");

const historyList = document.getElementById("history-list");
const traceProgress = document.getElementById("trace-progress");

const navItems = document.querySelectorAll(".nav-item");
const views = document.querySelectorAll(".view");
const newInvestigationBtn = document.getElementById("new-investigation-btn");
const homeStartBtn = document.getElementById("home-start-btn");

function showView(name) {
  for (const v of views) v.hidden = v.id !== `view-${name}`;
  for (const n of navItems) n.classList.toggle("active", n.dataset.view === name);
}

function resetInvestigationForm() {
  showView("investigations");
  input.value = "";
  autoGrowInput();
  traceSection.hidden = true;
  hideTraceLoading();
  verdictSection.hidden = true;
  claimResultHeader.hidden = true;
  evidenceOverviewSection.hidden = true;
  timelineSection.hidden = true;
  lastVerdict = null;
  exportBtn.disabled = true;
  resetMap();
  input.focus();
}

for (const item of navItems) {
  item.addEventListener("click", () => showView(item.dataset.view));
}
newInvestigationBtn.addEventListener("click", resetInvestigationForm);
homeStartBtn.addEventListener("click", resetInvestigationForm);

helpBtn.addEventListener("click", () => showView("home"));

function applyTheme(theme) {
  if (theme === "dark") {
    document.documentElement.dataset.theme = "dark";
  } else {
    delete document.documentElement.dataset.theme;
  }
  themeBtn.classList.toggle("is-active", theme === "dark");
  themeBtn.title = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
}

// The <head> inline script already set the attribute before paint (to
// avoid a light-then-dark flash) — this just reads that same state back
// so the button's title/active styling agree with what's on screen.
applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");

themeBtn.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  try {
    localStorage.setItem("origin-theme", next);
  } catch (e) {
    // Private-browsing localStorage restrictions shouldn't break the
    // toggle itself, just the persistence-across-reload part of it.
  }
});

const SHARE_ICON = shareBtn.innerHTML;
const SHARE_CHECK_ICON =
  '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7"/></svg>';

shareBtn.addEventListener("click", async () => {
  const claim = input.value.trim();
  if (!claim) return;
  const url = `${location.origin}${location.pathname}?demo_claim=${encodeURIComponent(claim)}`;
  let copied = false;
  try {
    await navigator.clipboard.writeText(url);
    copied = true;
  } catch (e) {
    // Clipboard API needs a secure context/permission that isn't always
    // available (e.g. plain http:// on a LAN demo box) — fall back to a
    // manual copy dialog rather than failing silently.
    window.prompt("Copy this link:", url);
  }
  // A title-attribute change alone is invisible until the button is
  // hovered again — swapping to a checkmark icon is feedback you actually
  // see at the moment you click, not feedback you have to go looking for.
  const originalTitle = shareBtn.title;
  shareBtn.innerHTML = SHARE_CHECK_ICON;
  shareBtn.title = copied ? "Link copied!" : "Link ready to copy";
  shareBtn.classList.add("is-active");
  setTimeout(() => {
    shareBtn.innerHTML = SHARE_ICON;
    shareBtn.title = originalTitle;
    shareBtn.classList.remove("is-active");
  }, 1500);
});

// Set by renderVerdict() whenever a resolved investigation is shown —
// export downloads exactly that object, so it's always in sync with
// whatever's actually on screen (live result or a reopened saved report).
let lastVerdict = null;

exportBtn.addEventListener("click", () => {
  if (!lastVerdict) return;
  // A real PDF via the browser's native print dialog ("Save as PDF" is a
  // destination on every major browser/OS) rather than pulling in a
  // client-side PDF library — the print stylesheet below hides everything
  // except the claim title and verdict card, so what prints is a clean
  // report, not a screenshot of the whole dashboard.
  window.print();
});

// Location Grounding, Claim Decomposition, Land Analysis, Ecology, Water
// Risk, Visual Inspection, Vegetation Trend, Carbon Registry, Climate
// Trend, Cross-Reference, Verdict Synthesis — kept in sync with
// orchestrator/pipeline.py's _MESSAGE_KEYS, in the same order, since the
// timeline is a compact "which stages are done" view of the exact same
// progress stream the vertical trace list already renders in full.
const TIMELINE_STEPS = [
  { agent: "Location Grounding", label: "Location Resolved" },
  { agent: "Claim Decomposition", label: "Claim Decomposed" },
  { agent: "Land Analysis", label: "Land Analyzed" },
  { agent: "Ecology", label: "Ecology Checked" },
  { agent: "Water Risk", label: "Water Risk Evaluated" },
  { agent: "Visual Inspection", label: "Imagery Retrieved" },
  { agent: "Vegetation Trend", label: "Vegetation Analyzed" },
  { agent: "Carbon Registry", label: "Carbon Checked" },
  { agent: "Climate Trend", label: "Climate Analyzed" },
  { agent: "Cross-Reference", label: "Cross-Reference Complete" },
  { agent: "Verdict Synthesis", label: "Verdict Generated" },
];

const CHECK_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7"/></svg>';

function buildTimeline() {
  timelineSteps.innerHTML = "";
  for (const step of TIMELINE_STEPS) {
    const li = document.createElement("li");
    li.className = "timeline-step";
    li.dataset.agent = step.agent;

    const circle = document.createElement("span");
    circle.className = "timeline-step-circle";
    circle.innerHTML = CHECK_ICON;

    const label = document.createElement("span");
    label.className = "timeline-step-label";
    label.textContent = step.label;

    li.appendChild(circle);
    li.appendChild(label);
    timelineSteps.appendChild(li);
  }
}

function markTimelineStepDone(agentLabel) {
  const stepEl = timelineSteps.querySelector(
    `.timeline-step[data-agent="${CSS.escape(agentLabel)}"]`
  );
  if (stepEl) stepEl.classList.add("is-done");
}

function resetEvidenceCards() {
  cardLandValue.textContent = "—";
  cardLandValue.classList.remove("is-empty");
  cardLandContext.textContent = "—";
  cardLandContext.className = "evidence-card-context";
  cardVegetationSub.textContent = "NDVI change";
  cardVegetationValue.textContent = "—";
  cardVegetationValue.classList.remove("is-empty");
  cardVegetationContext.textContent = "—";
  cardVegetationContext.className = "evidence-card-context";
  cardWaterValue.textContent = "—";
  cardWaterValue.classList.remove("is-empty");
  cardCarbonValue.textContent = "—";
  cardCarbonValue.classList.remove("is-empty");
  cardCarbonContext.textContent = "—";
  cardEcologyValue.textContent = "—";
  cardEcologyValue.classList.remove("is-empty");
  cardEcologyContext.textContent = "—";
}

function updateLandCard(stats, radiusKm) {
  if (!stats) return;
  cardLandValue.textContent = stats.years_with_data
    ? `${stats.years_with_data} year(s)`
    : "No data";
  cardLandValue.classList.toggle("is-empty", !stats.years_with_data);
  const lossy = stats.total_loss_ha_last_5_years > 0;
  cardLandContext.textContent = typeof radiusKm === "number" ? `within ${radiusKm.toFixed(1)} km` : "";
  cardLandContext.className = `evidence-card-context ${lossy ? "is-negative" : "is-positive"}`;
}

function updateVegetationCard(stats) {
  if (!stats) return;
  if (!stats.available) {
    cardVegetationSub.textContent = "NDVI change";
    cardVegetationValue.textContent = "No signal";
    cardVegetationValue.classList.add("is-empty");
    cardVegetationContext.textContent = "";
    cardVegetationContext.className = "evidence-card-context";
    return;
  }
  // ndvi_change is a raw NDVI-scale delta (NDVI itself runs -1..1), not a
  // percentage of baseline — matches how the same number is already
  // phrased in cross-reference prose elsewhere ("NDVI change of -0.09"),
  // so the card and the verdict text never disagree about what the
  // number means.
  const change = stats.ndvi_change ?? 0;
  cardVegetationSub.textContent = change >= 0 ? "NDVI increase" : "NDVI decrease";
  cardVegetationValue.textContent = `${change >= 0 ? "+" : ""}${change.toFixed(2)}`;
  cardVegetationValue.classList.remove("is-empty");
  cardVegetationContext.textContent = `from ${stats.baseline_year} to ${stats.recent_year}`;
  cardVegetationContext.className = "evidence-card-context";
}

function updateWaterCard(stats) {
  if (!stats) return;
  if (!stats.has_coverage) {
    cardWaterValue.textContent = "No signal";
    cardWaterValue.classList.add("is-empty");
    return;
  }
  const hasEvents = stats.event_count > 0;
  cardWaterValue.textContent = hasEvents ? `${stats.event_count} event(s)` : "No events";
  cardWaterValue.classList.toggle("is-empty", !hasEvents);
}

function updateCarbonCard(stats, radiusKm) {
  if (!stats) return;
  const found = stats.count > 0;
  cardCarbonValue.textContent = found ? `${stats.count} found` : "None";
  cardCarbonValue.classList.toggle("is-empty", !found);
  cardCarbonContext.textContent = typeof radiusKm === "number" ? `within ${radiusKm.toFixed(1)} km` : "";
}

function updateEcologyCard(stats, radiusKm) {
  if (!stats) return;
  const found = stats.count > 0;
  cardEcologyValue.textContent = found ? `${stats.count}` : "None";
  cardEcologyValue.classList.toggle("is-empty", !found);
  cardEcologyContext.textContent = typeof radiusKm === "number" ? `within ${radiusKm.toFixed(1)} km` : "";
}

// Location Grounding, Claim Decomposition, Land Analysis, Ecology, Water
// Risk, Visual Inspection, Vegetation Trend, Carbon Registry, Climate
// Trend, Cross-Reference, Verdict Synthesis — kept in sync with
// orchestrator/pipeline.py's _MESSAGE_KEYS.
const TOTAL_AGENTS = 11;
let completedAgents = 0;

const RADIUS_COLORS = {
  "Land Analysis": "#a9762c",
  Ecology: "#2f5d43",
  "Water Risk": "#3a6a8c",
  "Visual Inspection": "#7a4fa0",
  "Vegetation Trend": "#1f8a8c",
  "Carbon Registry": "#b8860b",
};

// Same colors as RADIUS_COLORS/the map legend, matched against evidence
// citation text ("... (source: X)") so a reader can recognize where a
// piece of evidence came from without reading the citation itself. Climate
// Trend has no map radius circle (it's a point query, not an area search)
// but still gets a tag color here for the same recognizability.
const SOURCE_TAG_COLORS = [
  { match: /global forest watch/i, color: "#a9762c" },
  { match: /wdpa|world database on protected areas/i, color: "#2f5d43" },
  { match: /gdacs/i, color: "#3a6a8c" },
  { match: /gemini vision/i, color: "#7a4fa0" },
  { match: /earth engine/i, color: "#1f8a8c" },
  { match: /verra|gold standard|puro|carbonmark/i, color: "#b8860b" },
  { match: /nasa power/i, color: "#c9622a" },
];

function sourceColorFor(text) {
  for (const { match, color } of SOURCE_TAG_COLORS) {
    if (match.test(text)) return color;
  }
  return null;
}

let map = null;
let siteMarker = null;
let radiusCircles = [];
let baseLayers = [];
let mapMode = "satellite";

function resetMap() {
  if (map) {
    map.remove();
    map = null;
  }
  siteMarker = null;
  radiusCircles = [];
  baseLayers = [];
  locationPanel.hidden = true;
  mapFrame.classList.remove("is-fullscreen");
}

// Split out from showSite() so the Satellite/Map toggle can swap just the
// base tiles without tearing down the marker/search-radius circles that
// already arrived from earlier progress events.
function applyBaseLayers() {
  if (!map) return;
  for (const layer of baseLayers) map.removeLayer(layer);
  baseLayers = [];

  if (mapMode === "satellite") {
    baseLayers.push(
      L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        { attribution: "Esri World Imagery", maxZoom: 18 }
      ),
      L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        { attribution: "Esri", maxZoom: 18 }
      )
    );
  } else {
    baseLayers.push(
      L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        { attribution: "Esri World Street Map", maxZoom: 18 }
      )
    );
  }
  // Leaflet's tile pane stacks by DOM/add order, and the GFW loss overlay
  // and marker/circles are added once in showSite() and never touched
  // again here — bringToBack keeps a freshly-swapped base layer from
  // ending up drawn on top of that overlay.
  for (const layer of baseLayers) {
    layer.addTo(map);
    layer.bringToBack();
  }
}

function showSite(lat, lon) {
  locationPanel.hidden = false;
  locationCaption.textContent = `${lat.toFixed(4)}, ${lon.toFixed(4)}`;

  // Fixed zoom close enough to read the 5-10km land/ecology circles clearly —
  // deliberately not auto-fit to the widest (50km water) circle, which would
  // zoom out so far the tighter, more informative circles nearly disappear.
  map = L.map("map-canvas", { zoomControl: true, attributionControl: true }).setView(
    [lat, lon],
    13
  );

  applyBaseLayers();

  // GFW's own tree-cover-loss tiles (UMD/Hansen dataset), the same layer
  // used on globalforestwatch.org — public, no API key. 512px tiles, so
  // Leaflet needs tileSize/zoomOffset set or every tile renders at 2x scale
  // and misaligns with the 256px basemap grid.
  L.tileLayer(
    "https://tiles.globalforestwatch.org/umd_tree_cover_loss/latest/tcd_30/{z}/{x}/{y}.png",
    { attribution: "Hansen/UMD/GFW", maxZoom: 18, tileSize: 512, zoomOffset: -1, opacity: 0.75 }
  ).addTo(map);

  L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);

  const timelapseUrl = `https://earthengine.google.com/timelapse#v=${lat},${lon},9,latLng`;
  timelapseLink.href = timelapseUrl;
  // Embedded directly (not behind a click-to-reveal toggle) — the
  // previous toggle version was easy to miss entirely, which read as "the
  // embed doesn't work" when it was really just never opened.
  timelapseEmbed.src = timelapseUrl;

  siteMarker = L.circleMarker([lat, lon], {
    radius: 6,
    color: "#faf8f4",
    weight: 2,
    fillColor: "#1c1b19",
    fillOpacity: 1,
  }).addTo(map);
}

for (const btn of mapModeBtns) {
  btn.addEventListener("click", () => {
    mapMode = btn.dataset.mode;
    for (const b of mapModeBtns) b.classList.toggle("active", b === btn);
    applyBaseLayers();
  });
}

layersToggleBtn.addEventListener("click", () => {
  mapLegendOverlay.classList.toggle("is-hidden");
});

fullscreenBtn.addEventListener("click", () => {
  mapFrame.classList.toggle("is-fullscreen");
  // Leaflet caches its container size — invalidateSize() must run after
  // the layout change actually takes effect, hence the rAF instead of
  // calling it synchronously.
  requestAnimationFrame(() => {
    if (map) map.invalidateSize();
  });
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && mapFrame.classList.contains("is-fullscreen")) {
    mapFrame.classList.remove("is-fullscreen");
    requestAnimationFrame(() => {
      if (map) map.invalidateSize();
    });
  }
});

function addSearchRadius(agentLabel, radiusKm) {
  if (!map || !siteMarker || !radiusKm) return;
  const color = RADIUS_COLORS[agentLabel];
  if (!color) return;

  const circle = L.circle(siteMarker.getLatLng(), {
    radius: radiusKm * 1000,
    color,
    weight: 1.5,
    fillColor: color,
    fillOpacity: 0.06,
    dashArray: "4 4",
  }).addTo(map);
  radiusCircles.push(circle);
}

function directionLabel(score) {
  if (score < 0.35) return "leans contradicts";
  if (score > 0.65) return "leans supports";
  return "mixed / inconclusive";
}

function directionStatusClass(score) {
  if (score == null) return "mixed";
  if (score < 0.35) return "contradicts";
  if (score > 0.65) return "supports";
  return "mixed";
}

function verdictStampInfo(verdict) {
  const coverage = verdict.confidence?.evidence_coverage ?? 0;
  const direction = verdict.confidence?.direction_score ?? 0.5;
  // Zero coverage means no evidence was decisive either way — a distinct
  // case from "mixed" (which means real evidence pulled in both
  // directions). Conflating them would misrepresent an absence of
  // evidence as if it were balanced evidence.
  if (coverage === 0) return { text: "Insufficient evidence", className: "insufficient" };
  const cls = directionStatusClass(direction);
  if (cls === "contradicts") return { text: "Contradicted", className: cls };
  if (cls === "supports") return { text: "Supported", className: cls };
  return { text: "Mixed signals", className: cls };
}

function historyStatusClass(row) {
  if (!row.resolved) return "unresolved";
  return directionStatusClass(row.direction_score);
}

function historyStatusText(row) {
  if (!row.resolved) return "unresolved";
  const cls = historyStatusClass(row);
  return cls === "mixed" ? "mixed" : cls;
}

function formatRelativeTime(isoString) {
  // claims_log.py writes Python's datetime.isoformat() on a UTC-aware
  // datetime, which already includes a numeric "+00:00" offset — parseable
  // by Date() as-is. (An earlier version of this tried to also append "Z",
  // producing an invalid double-suffixed string and "NaNd ago" everywhere.)
  const then = new Date(isoString);
  const diffSeconds = Math.round((Date.now() - then.getTime()) / 1000);
  if (diffSeconds < 60) return "just now";
  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.round(diffHours / 24)}d ago`;
}

function verdictFromHistoryRow(row) {
  if (!row.resolved) {
    return { resolved: false, reason: row.verdict_summary };
  }
  let evidence = {};
  try {
    evidence = JSON.parse(row.evidence_summary || "{}");
  } catch (e) {
    evidence = {};
  }
  let sources = [];
  try {
    sources = JSON.parse(row.sources || "[]");
  } catch (e) {
    sources = [];
  }
  return {
    resolved: true,
    investigation_id: row.investigation_id,
    claim: row.claim_text,
    location: row.location_display_name,
    confidence: {
      direction_score: row.direction_score,
      evidence_coverage: row.evidence_coverage,
      explanation: "",
    },
    supporting_evidence: evidence.supporting || [],
    contradicting_evidence: evidence.contradicting || [],
    gaps: evidence.gaps || [],
    summary: row.verdict_summary,
    sources,
    sub_claims: [],
  };
}

function showHistoryItem(row) {
  showView("investigations");
  traceSection.hidden = true;
  hideTraceLoading();
  // Past investigations weren't logged with the per-agent stat fields the
  // live SSE stream carries (claims_log stores the final verdict, not
  // every intermediate progress event) — showing empty/stale cards would
  // be worse than not showing the section at all.
  evidenceOverviewSection.hidden = true;
  timelineSection.hidden = true;
  resetMap();

  claimResultHeader.hidden = false;
  claimResultTitle.textContent = row.claim_text;
  metaPlace.textContent = row.location_display_name || "";
  metaDatetime.textContent = row.logged_at
    ? new Date(row.logged_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
    : "";
  metaLocation.textContent = "";

  if (row.resolved && typeof row.location_lat === "number" && typeof row.location_lon === "number") {
    showSite(row.location_lat, row.location_lon);
    metaLocation.textContent = `${row.location_lat.toFixed(4)}, ${row.location_lon.toFixed(4)}`;
  }
  renderVerdict(verdictFromHistoryRow(row));
  verdictSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadHistory() {
  try {
    const resp = await fetch("/api/history?limit=10");
    const data = await resp.json();
    const rows = data.investigations || [];

    historyList.innerHTML = "";
    if (rows.length === 0) {
      const li = document.createElement("li");
      li.className = "history-empty";
      li.textContent = "No investigations yet — run one from the Investigations tab.";
      historyList.appendChild(li);
      return;
    }

    for (const row of rows) {
      const li = document.createElement("li");
      li.className = "history-item";
      li.tabIndex = 0;
      li.setAttribute("role", "button");

      const claimEl = document.createElement("span");
      claimEl.className = "history-claim";
      claimEl.textContent = row.claim_text;
      claimEl.title = row.claim_text;

      const statusEl = document.createElement("span");
      statusEl.className = `history-status ${historyStatusClass(row)}`;
      statusEl.textContent = historyStatusText(row);

      const timeEl = document.createElement("span");
      timeEl.className = "history-time";
      timeEl.textContent = formatRelativeTime(row.logged_at);

      li.appendChild(claimEl);
      li.appendChild(statusEl);
      li.appendChild(timeEl);
      li.addEventListener("click", () => showHistoryItem(row));
      li.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          showHistoryItem(row);
        }
      });
      historyList.appendChild(li);
    }
  } catch (e) {
    historyList.innerHTML = "";
    const li = document.createElement("li");
    li.className = "history-empty";
    li.textContent = "Couldn't load past investigations.";
    historyList.appendChild(li);
  }
}

function fillList(el, items, emptyText) {
  el.innerHTML = "";
  if (!items || items.length === 0) {
    const li = document.createElement("li");
    li.textContent = emptyText;
    li.className = "empty-note";
    el.appendChild(li);
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    const color = sourceColorFor(item);
    if (color) {
      const tag = document.createElement("span");
      tag.className = "source-tag";
      tag.style.background = color;
      li.appendChild(tag);
    }
    const textEl = document.createElement("span");
    textEl.textContent = item;
    li.appendChild(textEl);
    el.appendChild(li);
  }
}

// Kept as the trace list's last child while an investigation is
// streaming, so the "more is coming" spinner always sits directly beneath
// whichever item was most recently added, not at a fixed position.
let traceLoadingEl = null;

function showTraceLoading() {
  hideTraceLoading();
  traceLoadingEl = document.createElement("li");
  traceLoadingEl.className = "trace-loading";
  const spinner = document.createElement("span");
  spinner.className = "trace-spinner";
  const label = document.createElement("span");
  label.className = "trace-loading-label";
  label.textContent = "Investigating…";
  traceLoadingEl.appendChild(spinner);
  traceLoadingEl.appendChild(label);
  traceList.appendChild(traceLoadingEl);
}

function hideTraceLoading() {
  if (traceLoadingEl && traceLoadingEl.parentNode) {
    traceLoadingEl.remove();
  }
  traceLoadingEl = null;
}

function addTraceItem(agent, summary) {
  const li = document.createElement("li");
  li.className = "trace-item";

  const agentEl = document.createElement("span");
  agentEl.className = "trace-agent";
  agentEl.textContent = agent;

  const summaryEl = document.createElement("span");
  summaryEl.className = "trace-summary";
  summaryEl.textContent = summary;

  li.appendChild(agentEl);
  li.appendChild(summaryEl);
  if (traceLoadingEl && traceLoadingEl.parentNode === traceList) {
    traceList.insertBefore(li, traceLoadingEl);
  } else {
    traceList.appendChild(li);
  }
}

function renderVerdict(verdict) {
  verdictSection.hidden = false;

  if (!verdict.resolved) {
    unresolvedBox.hidden = false;
    resolvedBox.hidden = true;
    unresolvedReason.textContent = verdict.reason || "Could not produce a verdict.";
    lastVerdict = null;
    exportBtn.disabled = true;
    return;
  }

  unresolvedBox.hidden = true;
  resolvedBox.hidden = false;
  lastVerdict = verdict;
  exportBtn.disabled = false;

  const stamp = verdictStampInfo(verdict);
  verdictStamp.textContent = stamp.text;
  verdictStamp.className = `verdict-stamp ${stamp.className}`;
  verdictCaseId.textContent = verdict.investigation_id
    ? `Case ${verdict.investigation_id.slice(0, 8)}`
    : "";

  verdictSummary.textContent = verdict.summary;

  const direction = verdict.confidence?.direction_score ?? 0.5;
  const coverage = verdict.confidence?.evidence_coverage ?? 0;

  // A marker on a fixed three-zone track — direction 0 sits at the left
  // edge (contradicts), 1 at the right edge (supports), 0.5 centered
  // (mixed). Plain positional CSS, not a rotation transform, so there's no
  // pivot/origin math for a browser to get wrong.
  directionMarker.style.left = `${Math.max(0, Math.min(1, direction)) * 100}%`;
  meterCoverage.style.width = `${Math.round(coverage * 100)}%`;
  directionValue.textContent = direction.toFixed(2);
  coverageValue.textContent = `${Math.round(coverage * 100)}%`;
  const explanationPrefix = verdict.confidence?.explanation
    ? `${verdict.confidence.explanation} `
    : "";
  confidenceExplanation.textContent = `${explanationPrefix}(${directionLabel(direction)})`;

  // Not present on reopened Saved Reports — claims_log only persists
  // direction_score/evidence_coverage as flat columns, not the raw
  // finding counts behind them, so the tally can only show for a live
  // (just-completed) investigation.
  const sc = verdict.confidence?.supports_count;
  const cc = verdict.confidence?.contradicts_count;
  const xc = verdict.confidence?.context_count;
  if (typeof sc === "number" && typeof cc === "number" && typeof xc === "number" && sc + cc + xc > 0) {
    findingTallyRow.hidden = false;
    tallyContradicts.style.flexGrow = cc;
    tallyContext.style.flexGrow = xc;
    tallySupports.style.flexGrow = sc;
    findingTallyLabel.textContent = `${cc} contradicts · ${xc} context · ${sc} supports`;
  } else {
    findingTallyRow.hidden = true;
  }

  fillList(contradictingList, verdict.contradicting_evidence, "None found.");
  fillList(supportingList, verdict.supporting_evidence, "None found.");

  if (verdict.gaps && verdict.gaps.length > 0) {
    gapsSection.hidden = false;
    fillList(gapsList, verdict.gaps, "");
  } else {
    gapsSection.hidden = true;
  }

  if (verdict.sub_claims && verdict.sub_claims.length > 0) {
    subClaimsSection.hidden = false;
    subClaimsList.innerHTML = "";
    for (const sc of verdict.sub_claims) {
      const li = document.createElement("li");
      li.className = "sub-claim-item";

      const header = document.createElement("div");
      header.className = "sub-claim-header";

      const textEl = document.createElement("span");
      textEl.className = "sub-claim-text";
      textEl.textContent = sc.claim;

      const badge = document.createElement("span");
      const cls = directionStatusClass(sc.confidence?.direction_score);
      badge.className = `history-status ${cls}`;
      badge.textContent = cls;

      header.appendChild(textEl);
      header.appendChild(badge);

      const summaryEl = document.createElement("p");
      summaryEl.className = "sub-claim-summary";
      summaryEl.textContent = sc.summary;

      li.appendChild(header);
      li.appendChild(summaryEl);
      subClaimsList.appendChild(li);
    }
  } else {
    subClaimsSection.hidden = true;
  }

  sources.textContent = verdict.sources && verdict.sources.length
    ? `Sources: ${verdict.sources.join(" · ")}`
    : "";
}

for (const chip of exampleChips) {
  chip.addEventListener("click", () => {
    input.value = chip.dataset.claim;
    autoGrowInput();
    form.requestSubmit();
  });
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  // Guards against a stray double-submit (e.g. Enter key plus a click
  // landing in the same tick) starting a second EventSource while the
  // first is still streaming — two concurrent streams would interleave
  // updates to the same DOM elements.
  if (submitBtn.disabled) return;
  const claim = input.value.trim();
  if (!claim) return;

  submitBtn.disabled = true;
  submitBtn.textContent = "Investigating…";

  traceSection.hidden = false;
  traceList.innerHTML = "";
  showTraceLoading();
  verdictSection.hidden = true;
  lastVerdict = null;
  exportBtn.disabled = true;
  resetMap();
  completedAgents = 0;
  traceProgress.textContent = `0 / ${TOTAL_AGENTS}`;

  claimResultHeader.hidden = false;
  claimResultTitle.textContent = claim;
  metaLocation.textContent = "";
  metaPlace.textContent = "";
  metaDatetime.textContent = new Date().toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });

  evidenceOverviewSection.hidden = false;
  resetEvidenceCards();

  timelineSection.hidden = false;
  buildTimeline();

  const url = `/api/investigate?claim=${encodeURIComponent(claim)}`;
  const source = new EventSource(url);

  source.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "progress") {
      addTraceItem(payload.agent, payload.summary);
      if (payload.agent !== "Pipeline") {
        completedAgents += 1;
        traceProgress.textContent = `${completedAgents} / ${TOTAL_AGENTS}`;
        markTimelineStepDone(payload.agent);
      }
      if (typeof payload.lat === "number" && typeof payload.lon === "number") {
        showSite(payload.lat, payload.lon);
        metaLocation.textContent = `${payload.lat.toFixed(4)}, ${payload.lon.toFixed(4)}`;
        metaPlace.textContent = payload.display_name || "";
      }
      if (typeof payload.radius_km === "number") {
        addSearchRadius(payload.agent, payload.radius_km);
      }
      if (payload.land_stats) updateLandCard(payload.land_stats, payload.radius_km);
      if (payload.vegetation_stats) updateVegetationCard(payload.vegetation_stats);
      if (payload.water_stats) updateWaterCard(payload.water_stats);
      if (payload.carbon_stats) updateCarbonCard(payload.carbon_stats, payload.radius_km);
      if (payload.ecology_stats) updateEcologyCard(payload.ecology_stats, payload.radius_km);
    } else if (payload.type === "verdict") {
      hideTraceLoading();
      renderVerdict(payload.data);
      source.close();
      submitBtn.disabled = false;
      submitBtn.textContent = "Investigate";
      loadHistory();
    }
  };

  source.onerror = () => {
    hideTraceLoading();
    source.close();
    submitBtn.disabled = false;
    submitBtn.textContent = "Investigate";
    if (verdictSection.hidden) {
      addTraceItem("Error", "Connection to server lost.");
    }
  };
});

// Optional: ?demo_claim=<text> pre-fills and auto-submits — useful for
// bookmarking a specific claim ahead of a live demo instead of typing it.
const presetClaim = new URLSearchParams(window.location.search).get("demo_claim");
if (presetClaim) {
  showView("investigations");
  input.value = presetClaim;
  autoGrowInput();
  form.requestSubmit();
}

loadHistory();
