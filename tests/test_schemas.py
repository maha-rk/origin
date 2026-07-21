"""Every Gemini call in this project uses response_schema instead of
prompt-and-hope JSON — these tests pin down that the schemas actually
enforce what the surrounding code assumes they enforce (in particular,
that an invalid "relation" value gets rejected by the API contract itself,
not just by a defensive check after the fact)."""

import pytest
from pydantic import ValidationError

from agents.claim_decomposition import _DecompositionSchema
from agents.cross_reference import _CrossReferenceSchema, _FindingSchema
from agents.location_grounding import _LocationSignalSchema
from agents.verdict_synthesis import _VerdictSummarySchema


def test_decomposition_schema_accepts_valid_data():
    parsed = _DecompositionSchema(sub_claims=["claim one", "claim two"])
    assert parsed.sub_claims == ["claim one", "claim two"]


def test_location_signal_schema_allows_null_location_text():
    parsed = _LocationSignalSchema(has_location=False, location_text=None)
    assert parsed.location_text is None


def test_location_signal_schema_requires_has_location():
    with pytest.raises(ValidationError):
        _LocationSignalSchema(location_text="Mandya")


def test_finding_schema_accepts_valid_relation():
    finding = _FindingSchema(
        sub_claim="x",
        evidence_source="Global Forest Watch",
        relation="contradicts",
        explanation="...",
        citation="...",
    )
    assert finding.relation == "contradicts"


def test_finding_schema_rejects_invalid_relation():
    # This is the actual point of switching to structured output: an
    # out-of-vocabulary relation should be impossible by construction, not
    # just something a downstream .get()-with-fallback happens to catch.
    with pytest.raises(ValidationError):
        _FindingSchema(
            sub_claim="x",
            evidence_source="Global Forest Watch",
            relation="probably_true",
            explanation="...",
            citation="...",
        )


def test_cross_reference_schema_accepts_empty_findings_and_gaps():
    parsed = _CrossReferenceSchema(findings=[], gaps=[])
    assert parsed.findings == []
    assert parsed.gaps == []


def test_verdict_summary_schema_allows_null_overall_summary():
    # Non-compound claims never get an overall_summary from the prompt —
    # null here must be valid, not a validation failure.
    parsed = _VerdictSummarySchema(sub_claim_summaries=["a summary"])
    assert parsed.overall_summary is None


def test_verdict_summary_schema_accepts_overall_summary_when_present():
    parsed = _VerdictSummarySchema(
        sub_claim_summaries=["a", "b"], overall_summary="combined summary"
    )
    assert parsed.overall_summary == "combined summary"
