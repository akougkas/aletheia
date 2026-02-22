"""Tests for recall-aware verdict synthesis in EditorAgent."""

from datetime import date

import pytest

from aletheia.agents.editor import EditorAgent
from aletheia.schema import (
    ChangeType,
    ComparabilityLevel,
    Direction,
    MethodologyChange,
    PolicyClaim,
    SeverityLevel,
    VerdictStatus,
)


def _claim() -> PolicyClaim:
    return PolicyClaim(
        original_text="EU unemployment fell sharply in 2021.",
        indicator="unemployment rate",
        dataset="EU-LFS",
        geography="EU",
        period_start=2020,
        period_end=2021,
        direction=Direction.DECREASE,
    )


def _breaks() -> list[MethodologyChange]:
    return [
        MethodologyChange(
            id=1,
            benchmark_case_id="MB-999",
            dataset_id=1,
            change_type=ChangeType.DEFINITION_CHANGE,
            effective_date=date(2021, 1, 1),
            description="Major definitional break",
            severity=SeverityLevel.MAJOR,
            comparability=ComparabilityLevel.NOT_COMPARABLE,
        )
    ]


def _moderate_relevant_breaks() -> list[MethodologyChange]:
    """Breaks that produce PARTIALLY_SUPPORTED via the catch-all path."""
    return [
        MethodologyChange(
            id=2,
            benchmark_case_id="MB-050",
            dataset_id=1,
            change_type=ChangeType.WEIGHTING_UPDATE,
            effective_date=date(2021, 3, 1),
            description="Weighting scheme updated",
            severity=SeverityLevel.MODERATE,
            comparability=ComparabilityLevel.COMPARABLE_WITH_ADJUSTMENTS,
        )
    ]


def _historical_breaks() -> list[MethodologyChange]:
    """Breaks outside the claim window → PARTIALLY_SUPPORTED (historical only)."""
    return [
        MethodologyChange(
            id=3,
            benchmark_case_id="MB-010",
            dataset_id=1,
            change_type=ChangeType.CLASSIFICATION_CHANGE,
            effective_date=date(2015, 1, 1),
            description="Old classification update",
            severity=SeverityLevel.MINOR,
            comparability=ComparabilityLevel.COMPARABLE_WITH_ADJUSTMENTS,
        )
    ]


def _recall_matches(
    status: str,
    confidence: float,
    count: int = 3,
    *,
    benchmark_case_id: str | None = None,
) -> dict:
    """Build a prior_verification_recall dict with ``count`` matching sessions."""
    matches = []
    for i in range(count):
        matches.append(
            {
                "session": {
                    "id": f"session:{i + 100}",
                    "case_id": f"case:{i + 100}",
                    "claim_text": "EU unemployment decreased",
                    "claim_dataset": "EU-LFS",
                    "claim_indicator": "unemployment rate",
                    "status": "completed",
                },
                "verdict": {"status": status, "confidence": confidence},
                "aggregate_confidence": confidence,
                "methodology_changes": [
                    {
                        "id": f"methodology_change:{i + 200}",
                        "benchmark_case_id": benchmark_case_id,
                        "change_type": "definition_change",
                        "effective_date": "2021-01-01",
                        "description": "Major definitional break",
                        "impact_estimate": None,
                    }
                ],
            }
        )
    return {
        "query": {"dataset": "EU-LFS", "indicator": "unemployment rate"},
        "matches": matches,
    }


def _mixed_recall(statuses: list[tuple[str, float]]) -> dict:
    """Build recall with mixed verdicts for consensus testing."""
    matches = []
    for i, (status, conf) in enumerate(statuses):
        matches.append(
            {
                "session": {
                    "id": f"session:{i + 300}",
                    "case_id": f"case:{i + 300}",
                    "claim_text": "EU unemployment decreased",
                    "claim_dataset": "EU-LFS",
                    "claim_indicator": "unemployment rate",
                    "status": "completed",
                },
                "verdict": {"status": status, "confidence": conf},
                "aggregate_confidence": conf,
                "methodology_changes": [],
            }
        )
    return {
        "query": {"dataset": "EU-LFS", "indicator": "unemployment rate"},
        "matches": matches,
    }


@pytest.mark.asyncio
async def test_aligned_recall_boosts_confidence():
    """Strong aligned recall should increase confidence within cap."""
    editor = EditorAgent()
    breaks = _breaks()

    # Without recall
    analysis_base = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": True, "confidence": 0.9},
    }
    verdict_no = await editor.synthesize(
        _claim(), breaks, dict(analysis_base), evidence_docs=[]
    )

    # With aligned recall (same status as evidence-derived verdict)
    analysis_recall = dict(analysis_base)
    analysis_recall["prior_verification_recall"] = _recall_matches(
        status="misleading", confidence=0.85, count=4,
    )
    verdict_yes = await editor.synthesize(
        _claim(), breaks, analysis_recall, evidence_docs=[]
    )

    assert verdict_yes.confidence > verdict_no.confidence
    assert verdict_yes.recall_adjustment is not None
    assert verdict_yes.recall_adjustment["recall_delta"] > 0
    assert any("prior similar verification" in c for c in verdict_yes.caveats)


@pytest.mark.asyncio
async def test_conflicting_recall_reduces_confidence():
    """Conflicting recall should decrease confidence."""
    editor = EditorAgent()
    breaks = _breaks()

    analysis_base = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": True, "confidence": 0.9},
    }
    verdict_no = await editor.synthesize(
        _claim(), breaks, dict(analysis_base), evidence_docs=[]
    )

    # Recall says "supported" but current evidence → misleading
    analysis_conflict = dict(analysis_base)
    analysis_conflict["prior_verification_recall"] = _recall_matches(
        status="supported", confidence=0.8, count=3,
    )
    verdict_conflict = await editor.synthesize(
        _claim(), breaks, analysis_conflict, evidence_docs=[]
    )

    assert verdict_conflict.confidence < verdict_no.confidence
    assert verdict_conflict.recall_adjustment["recall_delta"] < 0
    assert any("Conflicts" in c for c in verdict_conflict.caveats)


@pytest.mark.asyncio
async def test_weak_recall_has_no_effect():
    """Single match or low consensus should not change confidence."""
    editor = EditorAgent()
    breaks = _breaks()

    analysis_base = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": True, "confidence": 0.9},
    }
    verdict_base = await editor.synthesize(
        _claim(), breaks, dict(analysis_base), evidence_docs=[]
    )

    # Only 1 match → insufficient
    analysis_weak = dict(analysis_base)
    analysis_weak["prior_verification_recall"] = _recall_matches(
        status="misleading", confidence=0.9, count=1,
    )
    verdict_weak = await editor.synthesize(
        _claim(), breaks, analysis_weak, evidence_docs=[]
    )

    assert verdict_weak.confidence == verdict_base.confidence
    assert verdict_weak.recall_adjustment["recall_delta"] == 0.0
    assert verdict_weak.recall_adjustment["recall_reason"] == "insufficient_recall"


@pytest.mark.asyncio
async def test_recall_delta_never_exceeds_cap():
    """Even with many strong matches, abs(delta) stays within 0.08."""
    editor = EditorAgent()

    analysis = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": False},
        "prior_verification_recall": _recall_matches(
            status="supported", confidence=0.99, count=10,
        ),
    }
    verdict = await editor.synthesize(_claim(), [], analysis, evidence_docs=[])

    assert verdict.recall_adjustment is not None
    assert abs(verdict.recall_adjustment["recall_delta"]) <= 0.08


@pytest.mark.asyncio
async def test_recall_does_not_override_status():
    """Recall alone must not flip verdict status."""
    editor = EditorAgent()
    breaks = _breaks()

    # Evidence clearly says MISLEADING (NOT_COMPARABLE + MAJOR)
    analysis = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": True, "confidence": 0.95},
        "prior_verification_recall": _recall_matches(
            status="supported", confidence=0.95, count=5,
        ),
    }
    verdict = await editor.synthesize(_claim(), breaks, analysis, evidence_docs=[])

    # Status must remain MISLEADING despite recall saying "supported"
    assert verdict.status == VerdictStatus.MISLEADING
    # But confidence should be reduced due to conflict
    assert verdict.recall_adjustment["recall_delta"] < 0


# ---- Tie-breaking tests ----


@pytest.mark.asyncio
async def test_tiebreak_to_supported_with_historical_only_breaks():
    """PARTIALLY_SUPPORTED from historical breaks tips to SUPPORTED with strong recall."""
    editor = EditorAgent()
    breaks = _historical_breaks()

    analysis = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": False},
        "prior_verification_recall": _recall_matches(
            status="supported", confidence=0.9, count=4,
        ),
    }
    verdict = await editor.synthesize(_claim(), breaks, analysis, evidence_docs=[])

    assert verdict.status == VerdictStatus.SUPPORTED
    assert verdict.recall_adjustment.get("recall_tiebreak") is not None
    assert any("adjusted to supported" in c.lower() for c in verdict.caveats)


@pytest.mark.asyncio
async def test_tiebreak_to_misleading_with_structural_corroboration():
    """PARTIALLY_SUPPORTED tips to MISLEADING when recall + structure both agree."""
    editor = EditorAgent()
    breaks = _moderate_relevant_breaks()

    analysis = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": True, "confidence": 0.85},
        "prior_verification_recall": _recall_matches(
            status="misleading", confidence=0.85, count=4,
        ),
    }
    verdict = await editor.synthesize(_claim(), breaks, analysis, evidence_docs=[])

    assert verdict.status == VerdictStatus.MISLEADING
    assert verdict.recall_adjustment.get("recall_tiebreak") is not None
    assert any("adjusted to misleading" in c.lower() for c in verdict.caveats)


@pytest.mark.asyncio
async def test_tiebreak_blocked_weak_consensus():
    """Tie-break requires ≥80% consensus — mixed recall should not tip status."""
    editor = EditorAgent()
    breaks = _historical_breaks()

    # 2 supported + 2 misleading → 50% consensus, below 80% threshold
    analysis = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": False},
        "prior_verification_recall": _mixed_recall([
            ("supported", 0.8),
            ("supported", 0.8),
            ("misleading", 0.8),
            ("misleading", 0.8),
        ]),
    }
    verdict = await editor.synthesize(_claim(), breaks, analysis, evidence_docs=[])

    assert verdict.status == VerdictStatus.PARTIALLY_SUPPORTED
    assert verdict.recall_adjustment.get("recall_tiebreak") is None


@pytest.mark.asyncio
async def test_tiebreak_to_supported_blocked_by_structural_signal():
    """Recall says 'supported' but structure detected a break → no tie-break."""
    editor = EditorAgent()
    breaks = _historical_breaks()

    analysis = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": True, "confidence": 0.9},
        "prior_verification_recall": _recall_matches(
            status="supported", confidence=0.9, count=5,
        ),
    }
    verdict = await editor.synthesize(_claim(), breaks, analysis, evidence_docs=[])

    # Structure signal blocks the SUPPORTED tie-break.
    assert verdict.status == VerdictStatus.PARTIALLY_SUPPORTED
    assert verdict.recall_adjustment.get("recall_tiebreak") is None


@pytest.mark.asyncio
async def test_tiebreak_to_misleading_blocked_without_corroboration():
    """Recall says 'misleading' but no structural signal and severity < MAJOR → blocked."""
    editor = EditorAgent()
    breaks = _moderate_relevant_breaks()

    analysis = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": False},
        "prior_verification_recall": _recall_matches(
            status="misleading", confidence=0.9, count=4,
        ),
    }
    verdict = await editor.synthesize(_claim(), breaks, analysis, evidence_docs=[])

    # No structure corroboration and severity=MODERATE → blocked.
    assert verdict.status == VerdictStatus.PARTIALLY_SUPPORTED
    assert verdict.recall_adjustment.get("recall_tiebreak") is None


@pytest.mark.asyncio
async def test_overlap_uses_benchmark_case_id_when_available():
    """Overlap ratio should be higher when benchmark_case_ids match."""
    editor = EditorAgent()
    breaks = _breaks()  # has benchmark_case_id="MB-999"

    # Recall with matching benchmark_case_id
    recall_matching = _recall_matches(
        status="misleading", confidence=0.8, count=3,
        benchmark_case_id="MB-999",
    )
    adj_match = editor._compute_recall_adjustment(
        recall_matching, VerdictStatus.MISLEADING, breaks,
    )

    # Recall with non-matching benchmark_case_id
    recall_diff = _recall_matches(
        status="misleading", confidence=0.8, count=3,
        benchmark_case_id="MB-001",
    )
    adj_diff = editor._compute_recall_adjustment(
        recall_diff, VerdictStatus.MISLEADING, breaks,
    )

    match_overlap = adj_match["recall_metrics"]["recall_change_overlap_ratio"]
    diff_overlap = adj_diff["recall_metrics"]["recall_change_overlap_ratio"]

    assert match_overlap == 1.0  # exact benchmark_case_id match
    assert diff_overlap == 0.0  # no overlap
