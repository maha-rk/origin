const form = document.getElementById("claim-form");
const input = document.getElementById("claim-input");
const submitBtn = document.getElementById("submit-btn");

const traceSection = document.getElementById("trace");
const traceList = document.getElementById("trace-list");

const verdictSection = document.getElementById("verdict");
const unresolvedBox = document.getElementById("verdict-unresolved");
const unresolvedReason = document.getElementById("verdict-unresolved-reason");
const resolvedBox = document.getElementById("verdict-resolved");

const verdictSummary = document.getElementById("verdict-summary");
const meterDirection = document.getElementById("meter-direction");
const meterCoverage = document.getElementById("meter-coverage");
const directionValue = document.getElementById("direction-value");
const coverageValue = document.getElementById("coverage-value");
const confidenceExplanation = document.getElementById("confidence-explanation");
const contradictingList = document.getElementById("contradicting-list");
const supportingList = document.getElementById("supporting-list");
const gapsSection = document.getElementById("gaps-section");
const gapsList = document.getElementById("gaps-list");
const sources = document.getElementById("sources");

const locationPanel = document.getElementById("location-panel");
const locationCaption = document.getElementById("location-caption");

const RADIUS_COLORS = {
  "Land Analysis": "#a9762c",
  Ecology: "#2f5d43",
  "Water Risk": "#3a6a8c",
};

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
    li.textContent = item;
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

  verdictSummary.textContent = verdict.summary;

  const direction = verdict.confidence?.direction_score ?? 0.5;
  const coverage = verdict.confidence?.evidence_coverage ?? 0;

  meterDirection.style.width = `${Math.round(direction * 100)}%`;
  meterCoverage.style.width = `${Math.round(coverage * 100)}%`;
  directionValue.textContent = direction.toFixed(2);
  coverageValue.textContent = `${Math.round(coverage * 100)}%`;
  confidenceExplanation.textContent =
    (verdict.confidence?.explanation || "") + ` (${directionLabel(direction)})`;

  fillList(contradictingList, verdict.contradicting_evidence, "None found.");
  fillList(supportingList, verdict.supporting_evidence, "None found.");

  if (verdict.gaps && verdict.gaps.length > 0) {
    gapsSection.hidden = false;
    fillList(gapsList, verdict.gaps, "");
  } else {
    gapsSection.hidden = true;
  }

  sources.textContent = verdict.sources && verdict.sources.length
    ? `Sources: ${verdict.sources.join(" · ")}`
    : "";
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

  const url = `/api/investigate?claim=${encodeURIComponent(claim)}`;
  const source = new EventSource(url);

  source.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "progress") {
      addTraceItem(payload.agent, payload.summary);
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
