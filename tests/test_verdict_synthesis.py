"""compute_confidence() is the one number in the whole pipeline most likely
to get scrutinized — it's the actual verdict score, not a black box, so its
arithmetic needs to be pinned down exactly, not just "seems right"."""

from agents.cross_reference import CrossReferenceFinding, CrossReferenceResult
from agents.verdict_synthesis import compute_confidence


def _findings(n_supports: int, n_contradicts: int, n_context: int = 0):
    return CrossReferenceResult(
        findings=(
            [
                CrossReferenceFinding("src", "supports", "", "", "claim")
                for _ in range(n_supports)
            ]
            + [
                CrossReferenceFinding("src", "contradicts", "", "", "claim")
                for _ in range(n_contradicts)
            ]
            + [
                CrossReferenceFinding("src", "context", "", "", "claim")
                for _ in range(n_context)
            ]
        )
    )


def test_all_contradict_gives_zero():
    score = compute_confidence(_findings(0, 3))
    assert score.direction_score == 0.0
    assert score.evidence_coverage == 1.0
    assert score.contradicts_count == 3
    assert score.supports_count == 0


def test_all_support_gives_one():
    score = compute_confidence(_findings(3, 0))
    assert score.direction_score == 1.0
    assert score.evidence_coverage == 1.0
    assert score.supports_count == 3


def test_even_split_gives_midpoint():
    score = compute_confidence(_findings(1, 1))
    assert score.direction_score == 0.5
    assert score.evidence_coverage == 1.0


def test_partial_support_is_proportional():
    # 2 supports, 1 contradicts -> 0.5 + 0.5*((2-1)/3) = 0.6666...
    score = compute_confidence(_findings(2, 1))
    assert score.direction_score == 0.67


def test_context_findings_reduce_coverage_not_direction():
    # Direction only looks at the 3 decisive findings; coverage reflects
    # that 1 of the 4 total findings was excluded as context.
    score = compute_confidence(_findings(1, 2, n_context=1))
    assert score.direction_score == 0.33
    assert score.evidence_coverage == 0.75
    assert score.context_count == 1


def test_no_decisive_findings_is_neutral_not_zero_coverage_confused_with_contradiction():
    # Zero decisive findings must land at the neutral midpoint (0.5), not 0
    # — landing at 0 would misread "no evidence either way" as "evidence
    # against the claim," which is a meaningfully different, wrong signal.
    score = compute_confidence(_findings(0, 0, n_context=3))
    assert score.direction_score == 0.5
    assert score.evidence_coverage == 0.0
    assert score.context_count == 3


def test_empty_findings_do_not_crash():
    score = compute_confidence(CrossReferenceResult(findings=[]))
    assert score.direction_score == 0.5
    assert score.evidence_coverage == 0.0
