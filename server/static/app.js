const form = document.getElementById("claim-form");
const input = document.getElementById("claim-input");
const submitBtn = document.getElementById("submit-btn");
const exampleChips = document.querySelectorAll(".example-chip");

const traceSection = document.getElementById("trace");
const traceList = document.getElementById("trace-list");

const verdictSection = document.getElementById("verdict");
const unresolvedBox = document.getElementById("verdict-unresolved");
const unresolvedReason = document.getElementById("verdict-unresolved-reason");
const resolvedBox = document.getElementById("verdict-resolved");

const verdictStamp = document.getElementById("verdict-stamp");
const verdictCaseId = document.getElementById("verdict-case-id");
const verdictSummary = document.getElementById("verdict-summary");
const gaugeNeedle = document.getElementById("gauge-needle");
const meterCoverage = document.getElementById("meter-coverage");
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

const historySection = document.getElementById("history");
const historyList = document.getElementById("history-list");
const traceProgress = document.getElementById("trace-progress");

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

function resetMap() {
  if (map) {
    map.remove();
    map = null;
  }
  siteMarker = null;
  radiusCircles = [];
  locationPanel.hidden = true;
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

  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Esri World Imagery", maxZoom: 18 }
  ).addTo(map);

  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Esri", maxZoom: 18 }
  ).addTo(map);

  // GFW's own tree-cover-loss tiles (UMD/Hansen dataset), the same layer
  // used on globalforestwatch.org — public, no API key. 512px tiles, so
  // Leaflet needs tileSize/zoomOffset set or every tile renders at 2x scale
  // and misaligns with the 256px basemap grid.
  L.tileLayer(
    "https://tiles.globalforestwatch.org/umd_tree_cover_loss/latest/tcd_30/{z}/{x}/{y}.png",
    { attribution: "Hansen/UMD/GFW", maxZoom: 18, tileSize: 512, zoomOffset: -1, opacity: 0.75 }
  ).addTo(map);

  timelapseLink.href = `https://earthengine.google.com/timelapse#v=${lat},${lon},9,latLng`;

  siteMarker = L.circleMarker([lat, lon], {
    radius: 6,
    color: "#faf8f4",
    weight: 2,
    fillColor: "#1c1b19",
    fillOpacity: 1,
  }).addTo(map);
}

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
  traceSection.hidden = true;
  resetMap();
  if (row.resolved && typeof row.location_lat === "number" && typeof row.location_lon === "number") {
    showSite(row.location_lat, row.location_lon);
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
      historySection.hidden = true;
      return;
    }
    historySection.hidden = false;

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
    historySection.hidden = true;
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
  traceList.appendChild(li);
}

function renderVerdict(verdict) {
  verdictSection.hidden = false;

  if (!verdict.resolved) {
    unresolvedBox.hidden = false;
    resolvedBox.hidden = true;
    unresolvedReason.textContent = verdict.reason || "Could not produce a verdict.";
    return;
  }

  unresolvedBox.hidden = true;
  resolvedBox.hidden = false;

  const stamp = verdictStampInfo(verdict);
  verdictStamp.textContent = stamp.text;
  verdictStamp.className = `verdict-stamp ${stamp.className}`;
  verdictCaseId.textContent = verdict.investigation_id
    ? `Case ${verdict.investigation_id.slice(0, 8)}`
    : "";

  verdictSummary.textContent = verdict.summary;

  const direction = verdict.confidence?.direction_score ?? 0.5;
  const coverage = verdict.confidence?.evidence_coverage ?? 0;

  // Needle rests pointing straight up at direction=0.5 (neutral); sweeps
  // to fully left (-90deg) at 0 (contradicts) and fully right (+90deg) at
  // 1 (supports) — a full 180deg sweep matching the gauge's semicircle.
  gaugeNeedle.style.transform = `rotate(${180 * direction - 90}deg)`;
  meterCoverage.style.width = `${Math.round(coverage * 100)}%`;
  directionValue.textContent = direction.toFixed(2);
  coverageValue.textContent = `${Math.round(coverage * 100)}%`;
  const explanationPrefix = verdict.confidence?.explanation
    ? `${verdict.confidence.explanation} `
    : "";
  confidenceExplanation.textContent = `${explanationPrefix}(${directionLabel(direction)})`;

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
  verdictSection.hidden = true;
  resetMap();
  completedAgents = 0;
  traceProgress.textContent = `0 / ${TOTAL_AGENTS}`;

  const url = `/api/investigate?claim=${encodeURIComponent(claim)}`;
  const source = new EventSource(url);

  source.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "progress") {
      addTraceItem(payload.agent, payload.summary);
      if (payload.agent !== "Pipeline") {
        completedAgents += 1;
        traceProgress.textContent = `${completedAgents} / ${TOTAL_AGENTS}`;
      }
      if (typeof payload.lat === "number" && typeof payload.lon === "number") {
        showSite(payload.lat, payload.lon);
      }
      if (typeof payload.radius_km === "number") {
        addSearchRadius(payload.agent, payload.radius_km);
      }
    } else if (payload.type === "verdict") {
      renderVerdict(payload.data);
      source.close();
      submitBtn.disabled = false;
      submitBtn.textContent = "Investigate";
      loadHistory();
    }
  };

  source.onerror = () => {
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
  input.value = presetClaim;
  form.requestSubmit();
}

loadHistory();
