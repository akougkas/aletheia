from datetime import date

from aletheia.evaluation import CaseResult, compute_metrics
from aletheia.schema import (
    ChangeType,
    Direction,
    MethodologyChange,
    PolicyClaim,
    Verdict,
    VerdictStatus,
)


def _claim() -> PolicyClaim:
    return PolicyClaim(
        original_text="Test claim",
        indicator="unemployment rate",
        dataset="CPS",
        geography="USA",
        direction=Direction.UNKNOWN,
    )


def _break() -> MethodologyChange:
    return MethodologyChange(
        id=1,
        benchmark_case_id="MB-003",
        dataset_id=1,
        change_type=ChangeType.CLASSIFICATION_CHANGE,
        effective_date=date(2020, 3, 1),
        description="COVID misclassification",
    )


def _verdict(
    status: VerdictStatus,
    *,
    with_break: bool,
    with_caveat: bool,
) -> Verdict:
    return Verdict(
        claim=_claim(),
        status=status,
        confidence=0.8,
        breaks_found=[_break()] if with_break else [],
        summary="summary",
        caveats=["caveat"] if with_caveat else [],
    )


def test_compute_metrics_tracks_detection_and_false_positives():
    results = [
        CaseResult(
            case_id="MB-001",
            expected_status=VerdictStatus.MISLEADING,
            verdict=_verdict(
                VerdictStatus.MISLEADING, with_break=True, with_caveat=True
            ),
            expect_break=True,
        ),
        CaseResult(
            case_id="MB-002",
            expected_status=VerdictStatus.PARTIALLY_SUPPORTED,
            verdict=_verdict(
                VerdictStatus.PARTIALLY_SUPPORTED, with_break=True, with_caveat=True
            ),
            expect_break=True,
        ),
        CaseResult(
            case_id="NEG-001",
            expected_status=VerdictStatus.SUPPORTED,
            verdict=_verdict(
                VerdictStatus.SUPPORTED, with_break=False, with_caveat=False
            ),
            expect_break=False,
        ),
        CaseResult(
            case_id="NEG-002",
            expected_status=VerdictStatus.SUPPORTED,
            verdict=_verdict(
                VerdictStatus.SUPPORTED, with_break=True, with_caveat=False
            ),
            expect_break=False,
        ),
    ]

    metrics = compute_metrics(results)
    assert metrics["total_cases"] == 4.0
    assert metrics["verdict_accuracy"] == 1.0
    assert metrics["detection_recall"] == 1.0
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["caveat_coverage"] == 1.0
