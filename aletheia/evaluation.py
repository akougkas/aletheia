"""MethodBench-style evaluation helpers for ALETHEIA."""

from __future__ import annotations

from dataclasses import dataclass

from aletheia.schema import Verdict, VerdictStatus


@dataclass
class CaseResult:
    """One evaluated benchmark case."""

    case_id: str
    expected_status: VerdictStatus
    verdict: Verdict
    expect_break: bool = True


def compute_metrics(results: list[CaseResult]) -> dict[str, float]:
    """Compute basic benchmark metrics from evaluated cases."""
    if not results:
        return {
            "total_cases": 0.0,
            "verdict_accuracy": 0.0,
            "detection_recall": 0.0,
            "false_positive_rate": 0.0,
            "caveat_coverage": 0.0,
        }

    total = len(results)
    expected_break_cases = [result for result in results if result.expect_break]
    expected_no_break_cases = [result for result in results if not result.expect_break]

    verdict_matches = sum(
        1 for result in results if result.verdict.status == result.expected_status
    )
    break_detected_matches = sum(
        1 for result in expected_break_cases if len(result.verdict.breaks_found) > 0
    )
    false_positives = sum(
        1 for result in expected_no_break_cases if len(result.verdict.breaks_found) > 0
    )
    cases_with_caveats = sum(
        1 for result in expected_break_cases if len(result.verdict.caveats) > 0
    )

    detection_recall = (
        break_detected_matches / len(expected_break_cases)
        if expected_break_cases
        else 0.0
    )
    false_positive_rate = (
        false_positives / len(expected_no_break_cases)
        if expected_no_break_cases
        else 0.0
    )
    caveat_coverage = (
        cases_with_caveats / len(expected_break_cases)
        if expected_break_cases
        else 0.0
    )

    return {
        "total_cases": float(total),
        "verdict_accuracy": verdict_matches / total,
        "detection_recall": detection_recall,
        "false_positive_rate": false_positive_rate,
        "caveat_coverage": caveat_coverage,
    }
