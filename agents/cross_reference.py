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

from agents.gemini_config import MODEL, generate_with_retry
from data_clients.gdacs_client import WaterRiskQuery
from data_clients.gfw_client import ProtectedArea, TreeCoverLossYear

RELATIONS = {"supports", "contradicts", "context", "insufficient_data"}


@dataclass
class CrossReferenceFinding:
    evidence_source: str
    relation: str
    explanation: str
    citation: str


@dataclass
class CrossReferenceResult:
    findings: list[CrossReferenceFinding]
    gaps: list[str] = field(default_factory=list)


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
                "note": f"within {radius_km}km of claim location (exact distance not computed)",
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


def build_evidence_bundle(
    claim_text: str,
    location_display_name: str,
    land_loss_by_year: list[TreeCoverLossYear],
    ecology_areas: list[ProtectedArea],
    ecology_radius_km: float,
    water_query: WaterRiskQuery,
    water_radius_km: float,
    water_lookback_days: int,
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

    return {
        "claim": claim_text,
        "location": location_display_name,
        "evidence": evidence,
    }


def cross_reference_claim(client: genai.Client, evidence_bundle: dict) -> CrossReferenceResult:
    prompt = f"""You are the Evidence Cross-Reference stage of ORIGIN, a claim
investigation system. You are given a claim and evidence gathered by upstream
agents about the claim's location. Your job is ONLY to identify the
relationship between the claim and each piece of evidence — you never decide
whether the claim is true or false overall (that's a downstream step).

For each piece of evidence, judge its relation to the specific wording of the
claim:
- "supports": the evidence is consistent with what the claim asserts
- "contradicts": the evidence conflicts with what the claim asserts
- "context": relevant background, but doesn't directly confirm or deny the claim
- "insufficient_data": the claim asserts something this evidence category
  cannot actually measure (e.g. the claim is about emissions reductions, but
  land-use data can only speak to tree cover, not emissions directly)

Watch for negated claims ("no protected areas nearby", "no environmental
risk", "minimal impact"). The relation must reflect whether the evidence
confirms or refutes the CLAIM AS STATED, not just whether the evidence
category itself sounds negative or positive. For example: if the claim says
"no environmental risk nearby" and the evidence is a flood event found near
the location, that evidence CONTRADICTS the claim — finding a risk when the
claim asserts none is a contradiction, not support. Before assigning
"supports", double check: does this evidence actually make the claim's exact
wording more likely to be true, after accounting for any negation in it?

Also list "gaps": specific things the claim asserts that NONE of the gathered
evidence can verify or refute.

If the evidence dict is empty, return no findings and a gap noting that no
evidence was available for this claim/location.

Respond with strict JSON only, no markdown fences, in this exact shape:
{{
  "findings": [
    {{"evidence_source": "...", "relation": "supports|contradicts|context|insufficient_data", "explanation": "...", "citation": "..."}}
  ],
  "gaps": ["..."]
}}

For "evidence_source", always use the exact string in that evidence
category's "source" field below (e.g. "WDPA — World Database on Protected
Areas") — never the JSON key it's nested under (e.g. "ecology"). This keeps
citations consistent and human-readable regardless of which internal key the
pipeline used to organize the evidence.

Claim and evidence:
{json.dumps(evidence_bundle, indent=2)}"""

    response = generate_with_retry(client, MODEL, prompt)
    text = response.text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    data = json.loads(text)
    findings = [
        CrossReferenceFinding(
            evidence_source=f["evidence_source"],
            relation=f["relation"] if f["relation"] in RELATIONS else "context",
            explanation=f["explanation"],
            citation=f["citation"],
        )
        for f in data.get("findings", [])
    ]
    return CrossReferenceResult(findings=findings, gaps=data.get("gaps", []))
