import pytest

import demo
from aletheia.schema import (
    ComparabilityLevel,
    Direction,
    PolicyClaim,
    SeverityLevel,
    Verdict,
    VerdictStatus,
)


def _verdict() -> Verdict:
    claim = PolicyClaim(
        original_text="EU unemployment changed in 2021.",
        indicator="unemployment rate",
        dataset="EU-LFS",
        geography="EU",
        direction=Direction.UNKNOWN,
        confidence=0.9,
    )
    return Verdict(
        claim=claim,
        status=VerdictStatus.PARTIALLY_SUPPORTED,
        confidence=0.76,
        severity=SeverityLevel.MODERATE,
        comparability=ComparabilityLevel.COMPARABLE_WITH_ADJUSTMENTS,
        summary="Methodology changes explain part of the observed movement.",
    )


def _run_payload(
    *,
    claim_type: str = "methodology_aware",
    fallback_used: bool = False,
    deep_research_used: bool = False,
    include_decomposition: bool = True,
) -> dict:
    analysis = {
        "fallback_used": fallback_used,
        "deep_research_used": deep_research_used,
        "evidence_aggregate_confidence": 0.733,
        "provider_budget_skips": 1,
        "provider_budget_summary": {
            "sources": {"calls": {"methodology_kb": 1}, "skips": {}, "skip_total": 0},
            "providers": {"web_fallback": {"skip_total": 1}},
        },
    }
    if include_decomposition:
        analysis["methodology_vs_real"] = {
            "observed_change": -1.2,
            "methodology_component_estimate": 0.4,
            "real_component_estimate": -0.8,
            "methodology_share_estimate": 0.333,
        }

    return {
        "parsed_claim": {"indicator": "unemployment rate", "dataset": "EU-LFS"},
        "routing_plan": {
            "claim_type": claim_type,
            "source_ids": ["methodology_kb", "data_api", "document_index"],
            "fallback_source_id": "web_fallback",
            "deep_research_source_ids": ["paper_scholar"],
        },
        "source_outputs": [
            {
                "source_id": "methodology_kb",
                "doc_count": 2,
                "break_count": 1,
                "error_count": 0,
                "errors": [],
            }
        ],
        "analysis": analysis,
        "evidence_docs": [
            {
                "source_id": "methodology_kb",
                "title": "Method note",
                "content": "Definition update changed 2021 series comparability.",
                "relevance_score": 0.92,
                "confidence_score": 0.89,
            }
        ],
        "aggregate_confidence": 0.733,
        "fallback_used": fallback_used,
        "deep_research_used": deep_research_used,
        "verdict": {
            "status": "partially_supported",
            "severity": "moderate",
            "comparability": "comparable_with_adjustments",
            "confidence": 0.76,
        },
    }


def test_case_marker_validation_accepts_complete_payload(capsys):
    case = demo.DemoCase(
        case_id="smoke",
        title="Smoke",
        claim="Claim",
        expected_path="path",
    )
    result = demo.CaseResult(case=case, verdict=_verdict(), run=_run_payload())

    assert demo._validate_case_phase2_markers(result) == []

    demo._print_case_report(result, index=1, total=1)
    rendered = capsys.readouterr().out
    assert "Routing Plan" in rendered
    assert "Source Execution" in rendered
    assert "fallback_used" in rendered
    assert "deep_research_used" in rendered
    assert "aggregate_evidence_confidence" in rendered
    assert "provider_budget_skips" in rendered
    assert "Top Evidence Snippets (with relevance/confidence)" in rendered
    assert "Verdict" in rendered


def test_suite_coverage_requires_distinct_phase2_paths():
    case = demo.DemoCase(
        case_id="only-one",
        title="One",
        claim="Claim",
        expected_path="path",
    )
    result = demo.CaseResult(case=case, verdict=_verdict(), run=_run_payload())
    errors = demo._validate_suite_coverage([result])

    assert "No statistical_fact routed claim observed." in errors
    assert "No fallback_used=True run observed." in errors
    assert "No deep_research_used=True run observed." in errors


class _FakeOrchestrator:
    def __init__(self, payload: dict):
        self.payload = payload

    async def process_claim(self, text: str):  # noqa: ARG002
        return self.payload["verdict_obj"]

    def get_last_run_details(self):
        return self.payload["run"]

    async def close(self):
        return None


class _FailingOrchestrator:
    async def process_claim(self, text: str):  # noqa: ARG002
        raise RuntimeError("chat endpoint unreachable")

    def get_last_run_details(self):
        return {}

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_assert_mode_returns_nonzero_on_missing_markers(capsys):
    payload = {"verdict_obj": _verdict(), "run": {}}

    def factory():
        return _FakeOrchestrator(payload)

    exit_code = await demo.run_demo(
        quick=True,
        assert_phase2=True,
        case_ids=["methodology-path"],
        orchestrator_factory=factory,  # type: ignore[arg-type]
    )
    output = capsys.readouterr().out
    assert exit_code == 2
    assert "ASSERT-PHASE2 FAILED" in output
    assert "missing parsed_claim" in output


@pytest.mark.asyncio
async def test_assert_mode_passes_with_required_markers():
    payloads = [
        {"verdict_obj": _verdict(), "run": _run_payload(claim_type="methodology_aware")},
        {"verdict_obj": _verdict(), "run": _run_payload(claim_type="statistical_fact")},
        {"verdict_obj": _verdict(), "run": _run_payload(fallback_used=True)},
        {"verdict_obj": _verdict(), "run": _run_payload(deep_research_used=True)},
    ]
    index = {"value": 0}

    def factory():
        payload = payloads[index["value"]]
        index["value"] += 1
        return _FakeOrchestrator(payload)

    exit_code = await demo.run_demo(
        quick=True,
        assert_phase2=True,
        case_ids=[
            "methodology-path",
            "data-api-path",
            "fallback-path",
            "deep-research-path",
        ],
        orchestrator_factory=factory,  # type: ignore[arg-type]
    )
    assert exit_code == 0


@pytest.mark.asyncio
async def test_run_demo_returns_one_and_continues_on_case_runtime_failure(capsys):
    payload = {"verdict_obj": _verdict(), "run": _run_payload(claim_type="statistical_fact")}
    index = {"value": 0}

    def factory():
        if index["value"] == 0:
            index["value"] += 1
            return _FailingOrchestrator()
        return _FakeOrchestrator(payload)

    exit_code = await demo.run_demo(
        quick=True,
        assert_phase2=False,
        case_ids=["methodology-path", "data-api-path"],
        orchestrator_factory=factory,  # type: ignore[arg-type]
    )
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "CASE FAILED" in output
    assert "Case 2/2" in output
    assert "Demo completed with runtime failures." in output


@pytest.mark.asyncio
async def test_assert_mode_fails_fast_on_case_runtime_failure(capsys):
    def factory():
        return _FailingOrchestrator()

    exit_code = await demo.run_demo(
        quick=True,
        assert_phase2=True,
        case_ids=["methodology-path"],
        orchestrator_factory=factory,  # type: ignore[arg-type]
    )
    output = capsys.readouterr().out
    assert exit_code == 2
    assert "ASSERT-PHASE2 FAILED" in output
    assert "runtime_error" in output


def test_main_returns_one_on_unexpected_exception(monkeypatch, capsys):
    async def _boom(**kwargs):  # noqa: ARG001
        raise RuntimeError("unexpected")

    monkeypatch.setattr(demo, "run_demo", _boom)
    monkeypatch.setattr(demo.sys, "argv", ["demo.py", "--quick", "--plain"])
    exit_code = demo.main()
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Demo failed: RuntimeError: unexpected" in output
