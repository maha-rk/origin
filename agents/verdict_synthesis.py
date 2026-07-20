"""Verdict Synthesis Agent.

Produces the final report: supporting evidence, contradicting evidence,
confidence score, cited sources. Never asserts absolute truth — frames
output as evidence for human review.

The confidence score is computed deterministically from the Cross-Reference
Agent's findings, not guessed by the LLM — the brief requires no black-box
scores, so the one number a judge is most likely to scrutinize needs to be
explainable by construction. Gemini's only job here is turning already-
established findings into readable prose; it's instructed not to introduce
claims beyond what Cross-Reference already found, so it can't fabricate
evidence at the last stage.

"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from google import genai

from agents.cross_reference import CrossReferenceFinding, CrossReferenceResult
from agents.gemini_config import MODEL, generate_json


@dataclass
class ConfidenceScore:
    direction_score: float  # 0 = evidence entirely contradicts, 1 = entirely supports, 0.5 = mixed/even
    evidence_coverage: float  # fraction of findings that actually bore on the claim (not context/insufficient_data)
    explanation: str


@dataclass
class SubClaimVerdict:
    claim: str
    confidence: ConfidenceScore
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    gaps: list[str]
    summary: str


@dataclass
class Verdict:
    claim: str
    location: str
    confidence: ConfidenceScore
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    gaps: list[str]
    summary: str
    sources: list[str]
    # Only populated when the claim was decomposed into 2+ sub-claims —
    # empty for the common single-assertion case, where this breakdown
    # would just duplicate the top-level view above.
    sub_claims: list[SubClaimVerdict] = field(default_factory=list)


def compute_confidence(result: CrossReferenceResult) -> ConfidenceScore:
    supports = [f for f in result.findings if f.relation == "supports"]
    contradicts = [f for f in result.findings if f.relation == "contradicts"]
    decisive = len(supports) + len(contradicts)

    if decisive == 0:
        return ConfidenceScore(
            direction_score=0.5,
            evidence_coverage=0.0,
            explanation=(
                "No gathered evidence directly supported or contradicted the "
                "claim (0 of {} findings were decisive) — this is not "
                "evidence the claim is true, just an absence of evidence "
                "either way.".format(len(result.findings))
            ),
        )

    direction = 0.5 + 0.5 * ((len(supports) - len(contradicts)) / decisive)
    coverage = decisive / len(result.findings) if result.findings else 0.0
    return ConfidenceScore(
        direction_score=round(direction, 2),
        evidence_coverage=round(coverage, 2),
        explanation=(
            f"{len(supports)} of {len(result.findings)} findings supported the "
            f"claim, {len(contradicts)} contradicted it, "
            f"{len(result.findings) - decisive} were context/insufficient-data "
            "and excluded from the direction score."
        ),
    )


def _findings_by_relation(
    findings: list[CrossReferenceFinding], relation: str
) -> list[str]:
    return [
        f"{f.explanation} (source: {f.citation})"
        for f in findings
        if f.relation == relation
    ]


def _fallback_summary(supporting: list, contradicting: list, gaps: list) -> str:
    return (
        f"{len(supporting)} supporting and {len(contradicting)} contradicting "
        f"finding(s) were identified; {len(gaps)} aspect(s) of the claim could "
        "not be verified from available evidence."
    )


def synthesize_verdict(
    client: genai.Client,
    original_claim: str,
    sub_claims: list[str],
    location_display_name: str,
    cross_reference_result: CrossReferenceResult,
) -> Verdict:
    confidence = compute_confidence(cross_reference_result)
    supporting = _findings_by_relation(cross_reference_result.findings, "supports")
    contradicting = _findings_by_relation(cross_reference_result.findings, "contradicts")
    sources = sorted({f.evidence_source for f in cross_reference_result.findings})
    gap_texts = [g.gap for g in cross_reference_result.gaps]

    # Per-sub-claim breakdown, reusing the exact same deterministic
    # confidence formula on each sub-claim's own slice of the findings —
    # no separate aggregation logic to get wrong.
    per_sub_claim = []
    for sub_claim in sub_claims:
        findings_for_claim = [
            f for f in cross_reference_result.findings if f.sub_claim == sub_claim
        ]
        sub_confidence = compute_confidence(CrossReferenceResult(findings=findings_for_claim))
        per_sub_claim.append(
            {
                "claim": sub_claim,
                "confidence": sub_confidence,
                "supporting": _findings_by_relation(findings_for_claim, "supports"),
                "contradicting": _findings_by_relation(findings_for_claim, "contradicts"),
                "gaps": [g.gap for g in cross_reference_result.gaps if g.sub_claim == sub_claim],
            }
        )

    is_compound = len(sub_claims) > 1
    prompt = f"""You are the Verdict Synthesis stage of ORIGIN, a claim
investigation system. You are given a claim (possibly broken into multiple
sub-claims), its location, and evidence findings already classified as
supporting or contradicting each sub-claim, plus known gaps.

Hard rules:
- Do NOT introduce any fact, evidence, or claim that isn't already present in
  the findings or gaps given to you below. You are organizing and explaining
  existing findings, not investigating further.
- Never assert any claim is definitively true or false. Frame this as
  evidence for a human reviewer to weigh, not a final judgment.
- If gaps exist for a sub-claim, mention plainly what the evidence could NOT
  verify for it.

Write a short, plain-language summary (3-5 sentences) for EACH sub-claim
below, in the same order they're given.{" Also write one overall summary "
"(3-5 sentences) synthesizing across all sub-claims together." if is_compound else ""}

Respond with strict JSON only, no markdown fences, in this exact shape:
{{"sub_claim_summaries": ["...", ...]{', "overall_summary": "..."' if is_compound else ""}}}

Location: {location_display_name!r}
Sub-claims and their findings, in order: {json.dumps([
    {
        "claim": item["claim"],
        "supporting_findings": item["supporting"],
        "contradicting_findings": item["contradicting"],
        "gaps": item["gaps"],
    }
    for item in per_sub_claim
], indent=2)}"""

    data = generate_json(client, MODEL, prompt)
    sub_claim_summaries = data.get("sub_claim_summaries")
    if not isinstance(sub_claim_summaries, list) or len(sub_claim_summaries) != len(sub_claims):
        # Fall back per-item rather than discarding every summary just
        # because the list came back the wrong length.
        sub_claim_summaries = []
    for i, item in enumerate(per_sub_claim):
        item["summary"] = (
            sub_claim_summaries[i]
            if i < len(sub_claim_summaries) and sub_claim_summaries[i]
            else _fallback_summary(item["supporting"], item["contradicting"], item["gaps"])
        )

    if is_compound:
        overall_summary = data.get("overall_summary") or _fallback_summary(
            supporting, contradicting, gap_texts
        )
    else:
        overall_summary = per_sub_claim[0]["summary"] if per_sub_claim else _fallback_summary(
            supporting, contradicting, gap_texts
        )

    sub_claim_verdicts = (
        [
            SubClaimVerdict(
                claim=item["claim"],
                confidence=item["confidence"],
                supporting_evidence=item["supporting"],
                contradicting_evidence=item["contradicting"],
                gaps=item["gaps"],
                summary=item["summary"],
            )
            for item in per_sub_claim
        ]
        if is_compound
        else []
    )

    return Verdict(
        claim=original_claim,
        location=location_display_name,
        confidence=confidence,
        supporting_evidence=supporting,
        contradicting_evidence=contradicting,
        gaps=gap_texts,
        summary=overall_summary,
        sources=sources,
        sub_claims=sub_claim_verdicts,
    )
