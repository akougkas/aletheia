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


@pytest.mark.asyncio
async def test_editor_marks_not_comparable_major_break_as_misleading():
    editor = EditorAgent()
    breaks = [
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
    analysis = {"data_retrieved": True, "structural_break_detected": {"detected": True}}

    verdict = await editor.synthesize(_claim(), breaks, analysis, evidence_docs=[])
    assert verdict.status == VerdictStatus.MISLEADING
    assert verdict.comparability == ComparabilityLevel.NOT_COMPARABLE
    assert verdict.severity == SeverityLevel.MAJOR


@pytest.mark.asyncio
async def test_editor_uses_false_positive_guard_for_routine_revision():
    editor = EditorAgent()
    breaks = [
        MethodologyChange(
            id=2,
            benchmark_case_id="MB-008",
            dataset_id=1,
            change_type=ChangeType.OTHER,
            effective_date=date(2021, 1, 1),
            description="Routine revision from late registration backlog",
            impact_estimate="small revisions around 0.1",
            severity=SeverityLevel.MODERATE,
            comparability=ComparabilityLevel.UNCERTAIN,
        )
    ]
    analysis = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": False},
        "methodology_vs_real": {"methodology_share_estimate": 0.1},
    }

    verdict = await editor.synthesize(_claim(), breaks, analysis, evidence_docs=[])
    assert verdict.status == VerdictStatus.PARTIALLY_SUPPORTED
    assert verdict.severity == SeverityLevel.MINOR
    assert verdict.comparability == ComparabilityLevel.COMPARABLE_WITH_ADJUSTMENTS


@pytest.mark.asyncio
async def test_editor_boosts_confidence_when_chow_corroborates_kb_breaks():
    """Strong Chow test + KB breaks → confidence boosted beyond base."""
    editor = EditorAgent()
    breaks = [
        MethodologyChange(
            id=3,
            benchmark_case_id="MB-100",
            dataset_id=1,
            change_type=ChangeType.DEFINITION_CHANGE,
            effective_date=date(2021, 1, 1),
            description="Major methodology change",
            severity=SeverityLevel.MAJOR,
            comparability=ComparabilityLevel.NOT_COMPARABLE,
        )
    ]
    analysis_with_math = {
        "data_retrieved": True,
        "structural_break_detected": {
            "detected": True,
            "confidence": 0.95,
            "p_value": 0.001,
            "test_type": "chow_test_linear_trend",
            "split_date": "2021-01",
        },
    }
    analysis_without_math = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": False},
    }

    verdict_with = await editor.synthesize(_claim(), breaks, analysis_with_math, evidence_docs=[])
    verdict_without = await editor.synthesize(_claim(), breaks, analysis_without_math, evidence_docs=[])
    # Math corroboration should boost confidence.
    assert verdict_with.confidence > verdict_without.confidence


@pytest.mark.asyncio
async def test_editor_flags_undocumented_break_from_chow_signal():
    """Strong Chow signal with no KB breaks → PARTIALLY_SUPPORTED, not SUPPORTED."""
    editor = EditorAgent()
    analysis = {
        "data_retrieved": True,
        "structural_break_detected": {
            "detected": True,
            "confidence": 0.95,
            "p_value": 0.002,
            "test_type": "chow_test_linear_trend",
            "split_date": "2021-03",
        },
    }
    verdict = await editor.synthesize(_claim(), [], analysis, evidence_docs=[])
    assert verdict.status == VerdictStatus.PARTIALLY_SUPPORTED
    assert verdict.comparability == ComparabilityLevel.UNCERTAIN


@pytest.mark.asyncio
async def test_editor_penalizes_conflicting_math_and_kb():
    """KB says major break but Chow found nothing → lower confidence."""
    editor = EditorAgent()
    breaks = [
        MethodologyChange(
            id=4,
            benchmark_case_id="MB-200",
            dataset_id=1,
            change_type=ChangeType.DEFINITION_CHANGE,
            effective_date=date(2021, 1, 1),
            description="Major change per KB",
            severity=SeverityLevel.MAJOR,
            comparability=ComparabilityLevel.COMPARABLE_WITH_ADJUSTMENTS,
        )
    ]
    analysis_no_break = {
        "data_retrieved": True,
        "structural_break_detected": {"detected": False},
    }
    analysis_with_break = {
        "data_retrieved": True,
        "structural_break_detected": {
            "detected": True,
            "confidence": 0.95,
            "p_value": 0.001,
        },
    }
    verdict_conflict = await editor.synthesize(_claim(), breaks, analysis_no_break, evidence_docs=[])
    verdict_aligned = await editor.synthesize(_claim(), breaks, analysis_with_break, evidence_docs=[])
    # Conflicting evidence should yield lower confidence than aligned evidence.
    assert verdict_conflict.confidence < verdict_aligned.confidence


@pytest.mark.asyncio
async def test_editor_supported_when_no_breaks_and_weak_chow():
    """Weak Chow signal (low confidence) with no breaks → still SUPPORTED."""
    editor = EditorAgent()
    analysis = {
        "data_retrieved": True,
        "structural_break_detected": {
            "detected": True,
            "confidence": 0.5,
            "p_value": 0.08,
        },
    }
    verdict = await editor.synthesize(_claim(), [], analysis, evidence_docs=[])
    assert verdict.status == VerdictStatus.SUPPORTED
