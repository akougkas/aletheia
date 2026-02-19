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
