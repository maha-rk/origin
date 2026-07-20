"""Evidence Cross-Reference Agent.

Takes the claim plus whatever the Land Analysis, Ecology, and Water Risk
agents found, and identifies where the evidence supports, contradicts, or
simply can't speak to what the claim asserts. This is where most of the
system's actual reasoning depth lives — the upstream agents just fetch data;
this agent has to judge its relationship to the specific wording of the
claim, which arithmetic can't do.

"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from google import genai

from agents.gemini_config import MODEL, generate_json
from agents.visual_inspection import VisualInspectionResult
from data_clients.gdacs_client import WaterRiskQuery
from data_clients.gfw_client import ProtectedArea, TreeCoverLossYear

RELATIONS = {"supports", "contradicts", "context", "insufficient_data"}


@dataclass
class CrossReferenceFinding:
    evidence_source: str
    relation: str
    explanation: str
    citation: str
    sub_claim: str


@dataclass
class Gap:
    sub_claim: str
    gap: str


@dataclass
class CrossReferenceResult:
    findings: list[CrossReferenceFinding]
    gaps: list[Gap] = field(default_factory=list)


def _summarize_land_evidence(loss_by_year: list[TreeCoverLossYear]) -> dict | None:
    if not loss_by_year:
        return None
    years_sorted = sorted(loss_by_year, key=lambda y: y.year)
    recent = [y for y in years_sorted if y.year >= years_sorted[-1].year - 4]
    return {
        "source": "Global Forest Watch — tree cover loss (30% canopy density threshold)",
        "years_with_data": [y.year for y in years_sorted],
        "total_loss_ha_all_years": round(sum(y.loss_area_ha for y in years_sorted), 2),
        "total_loss_ha_last_5_years": round(sum(y.loss_area_ha for y in recent), 2),
        "most_recent_year": years_sorted[-1].year,
        "most_recent_year_loss_ha": round(years_sorted[-1].loss_area_ha, 2),
    }


def _summarize_ecology_evidence(
    areas: list[ProtectedArea], radius_km: float
) -> dict | None:
    if not areas:
        return None
    return {
        "source": "WDPA — World Database on Protected Areas",
        "search_radius_km": radius_km,
        "protected_areas_found": [
            {
                "name": a.name,
                "designation": a.designation,
                "iucn_category": a.iucn_category,
                "status": a.status,
                "area_ha": round(a.area_ha, 2),
                "note": (
                    f"approximately {a.distance_km}km from claim location "
                    "(distance to the protected area's bounding-box center, "
                    "not its nearest edge)"
                    if a.distance_km is not None
                    else f"within {radius_km}km of claim location (exact distance not computed)"
                ),
            }
            for a in areas
        ],
    }


def _summarize_water_evidence(
    query: WaterRiskQuery, radius_km: float, days: int
) -> dict | None:
    # Opportunistic by design: only contributes evidence when GDACS both has
    # coverage here AND found an actual event. No-coverage and no-events are
    # both silently omitted, not surfaced as a placeholder — see
    # data_clients/gdacs_client.py's WaterRiskQuery docstring for why those
    # two cases are tracked separately even though they're both silent here.
    if not query.has_coverage or not query.events:
        return None
    return {
        "source": "GDACS — disaster alerts",
        "search_radius_km": radius_km,
        "lookback_days": days,
        "events": [
            {
                "type": e.event_type,
                "name": e.name,
                "alert_level": e.alert_level,
                "from_date": e.from_date,
                "to_date": e.to_date,
            }
            for e in query.events
        ],
    }


def _summarize_visual_evidence(visual: VisualInspectionResult) -> dict | None:
    # No radius number included here on purpose — a distinct evidence
    # category restating a search-radius figure is exactly the pattern that
    # caused Gemini to misattribute one category's radius to another's
    # explanation text in earlier testing (see the "do NOT state a
    # search_radius_km number" instruction below); the observation content
    # itself doesn't need it to be useful.
    if not visual.available or not visual.observations:
        return None
    return {
        "source": "Gemini vision — satellite image analysis (generated independently, without seeing the claim text)",
        "observations": visual.observations,
    }


def _summarize_vegetation_evidence(vegetation: dict | None) -> dict | None:
    if not vegetation or not vegetation.get("available"):
        return None
    return {
        "source": "Google Earth Engine — Sentinel-2 NDVI vegetation index",
        "recent_year": vegetation["recent_year"],
        "baseline_year": vegetation["baseline_year"],
        "recent_ndvi": vegetation["recent_ndvi"],
        "baseline_ndvi": vegetation["baseline_ndvi"],
        "ndvi_change": vegetation["ndvi_change"],
        "note": (
            "NDVI ranges roughly 0 (bare ground/water) to ~0.9 (dense healthy "
            "vegetation); a negative ndvi_change indicates vegetation decline "
            "between baseline_year and recent_year in this area."
        ),
    }


def _summarize_carbon_evidence(
    projects: list[dict], radius_km: float
) -> dict | None:
    if not projects:
        return None
    return {
        "source": "Verra/Gold Standard/Puro carbon registries (via Carbonmark)",
        "nearby_registered_projects": [
            {
                "name": p["name"],
                "registry": p["registry"],
                "methodologies": p["methodologies"],
                "total_credits_retired": p["total_credits_retired"],
                "note": f"approximately {p['distance_km']}km from claim location",
            }
            for p in projects
        ],
        "note": (
            f"Searched a {radius_km}km radius. Absence of a project here means "
            "no registered carbon offset project was found nearby — it does not "
            "confirm or deny any claim about emissions or deforestation on its own."
        ),
    }


def build_evidence_bundle(
    original_claim: str,
    sub_claims: list[str],
    location_display_name: str,
    land_loss_by_year: list[TreeCoverLossYear],
    ecology_areas: list[ProtectedArea],
    ecology_radius_km: float,
    water_query: WaterRiskQuery,
    water_radius_km: float,
    water_lookback_days: int,
    visual: VisualInspectionResult,
    vegetation: dict | None,
    carbon_projects: list[dict],
    carbon_radius_km: float,
) -> dict:
    evidence = {}
    land = _summarize_land_evidence(land_loss_by_year)
    if land:
        evidence["land_analysis"] = land
    ecology = _summarize_ecology_evidence(ecology_areas, ecology_radius_km)
    if ecology:
        evidence["ecology"] = ecology
    water = _summarize_water_evidence(water_query, water_radius_km, water_lookback_days)
    if water:
        evidence["water_risk"] = water
    visual_summary = _summarize_visual_evidence(visual)
    if visual_summary:
        evidence["visual_inspection"] = visual_summary
    vegetation_summary = _summarize_vegetation_evidence(vegetation)
    if vegetation_summary:
        evidence["vegetation_trend"] = vegetation_summary
    carbon_summary = _summarize_carbon_evidence(carbon_projects, carbon_radius_km)
    if carbon_summary:
        evidence["carbon_registry"] = carbon_summary

    return {
        "claim": original_claim,
        "sub_claims": sub_claims,
        "location": location_display_name,
        "evidence": evidence,
    }


def cross_reference_claim(client: genai.Client, evidence_bundle: dict) -> CrossReferenceResult:
    sub_claims = evidence_bundle.get("sub_claims") or [evidence_bundle.get("claim", "")]
    prompt = f"""You are the Evidence Cross-Reference stage of ORIGIN, a claim
investigation system. You are given a claim broken into one or more atomic
sub-claims, plus evidence gathered by upstream agents about the claim's
location. Your job is ONLY to identify the relationship between EACH
sub-claim and each piece of evidence — you never decide whether any claim
is true or false overall (that's a downstream step).

There are {len(sub_claims)} sub-claim(s) to judge evidence against:
{json.dumps(sub_claims, indent=2)}

For each piece of evidence, and for EACH sub-claim it's relevant to, judge
the relation:
- "supports": the evidence is consistent with what that sub-claim asserts
- "contradicts": the evidence conflicts with what that sub-claim asserts
- "context": relevant background, but doesn't directly confirm or deny that sub-claim
- "insufficient_data": that sub-claim asserts something this evidence
  category cannot actually measure (e.g. the sub-claim is about emissions
  reductions, but land-use data can only speak to tree cover, not emissions
  directly)

A single piece of evidence may be relevant to multiple sub-claims (produce
one finding per sub-claim it actually bears on) or to none of them (skip it
entirely rather than forcing an irrelevant finding).

Watch for negated claims ("no protected areas nearby", "no environmental
risk", "minimal impact"). The relation must reflect whether the evidence
confirms or refutes the SUB-CLAIM AS STATED, not just whether the evidence
category itself sounds negative or positive. For example: if a sub-claim
says "no environmental risk nearby" and the evidence is a flood event found
near the location, that evidence CONTRADICTS the sub-claim — finding a risk
when the sub-claim asserts none is a contradiction, not support. Before
assigning "supports", double check: does this evidence actually make that
sub-claim's exact wording more likely to be true, after accounting for any
negation in it?

Also list "gaps": specific things any sub-claim asserts that NONE of the
gathered evidence can verify or refute. Each gap must be tagged with which
sub-claim it belongs to (exactly matching one of the sub-claims above).

Do NOT state a "search_radius_km" number in your explanation text — models
have repeatedly misattributed one evidence category's radius to another
(e.g. describing an ecology finding using land_analysis's radius) even when
told to be careful, so the number is left out of your task entirely. Where
a specific protected area already has a "note" field with its computed
distance (e.g. "approximately 8.17km from claim location"), use THAT
distance instead — it's more precise than a search radius anyway, and it's
already correct in the data you don't need to transcribe it.

If the evidence dict is empty, return no findings and a gap noting that no
evidence was available for this claim/location.

Respond with strict JSON only, no markdown fences, in this exact shape:
{{
  "findings": [
    {{"sub_claim": "<must exactly match one of the sub-claims above>", "evidence_source": "...", "relation": "supports|contradicts|context|insufficient_data", "explanation": "...", "citation": "..."}}
  ],
  "gaps": [
    {{"sub_claim": "<must exactly match one of the sub-claims above>", "gap": "..."}}
  ]
}}

For "evidence_source", always use the exact string in that evidence
category's "source" field below (e.g. "WDPA — World Database on Protected
Areas") — never the JSON key it's nested under (e.g. "ecology"). This keeps
citations consistent and human-readable regardless of which internal key the
pipeline used to organize the evidence.

Claim and evidence:
{json.dumps(evidence_bundle, indent=2)}"""

    data = generate_json(client, MODEL, prompt)
    # Defensive .get() rather than direct indexing: a single malformed
    # finding item (missing a key) shouldn't crash the whole investigation
    # when the other findings are perfectly usable. sub_claim falls back to
    # the first sub-claim rather than an empty string so grouping downstream
    # never silently drops a finding into an unmatched bucket.
    findings = [
        CrossReferenceFinding(
            evidence_source=f.get("evidence_source", "unknown source"),
            relation=f.get("relation") if f.get("relation") in RELATIONS else "context",
            explanation=f.get("explanation", ""),
            citation=f.get("citation", ""),
            sub_claim=f.get("sub_claim") or sub_claims[0],
        )
        for f in data.get("findings", [])
    ]
    gaps = [
        Gap(sub_claim=g.get("sub_claim") or sub_claims[0], gap=g.get("gap", ""))
        for g in data.get("gaps", [])
        if isinstance(g, dict)
    ]
    return CrossReferenceResult(findings=findings, gaps=gaps)
