#!/usr/bin/env python
"""ALETHEIA Phase 2 demo integration harness."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
import re
import sys
from typing import Any, Callable, Iterable

from aletheia.agents.orchestrator import OrchestratorAgent
from aletheia.runtime_profiles import PROFILE_CHOICES, apply_runtime_profile
from aletheia.schema import (
    ComparabilityLevel,
    PolicyClaim,
    SeverityLevel,
    Verdict,
    VerdictStatus,
)
from aletheia.tui import TerminalUI

_BASE_SOURCE_BUDGET = (
    "methodology_kb:1,data_api:1,document_index:1,web_fallback:1,paper_scholar:1"
)


@dataclass(frozen=True)
class DemoCase:
    """Single demo case definition."""

    case_id: str
    title: str
    claim: str
    expected_path: str
    env_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class CaseResult:
    """Result bundle for one demo claim."""

    case: DemoCase
    verdict: Verdict
    run: dict[str, Any]
    error: str | None = None


DEMO_CASES = [
    DemoCase(
        case_id="methodology-path",
        title="Methodology-aware path",
        claim=(
            "E-cigarette use among US adults increased from 3.2% to 4.4% in 2019 "
            "according to NHIS data."
        ),
        expected_path="methodology_aware routing with methodology_kb + data_api + document_index",
        env_overrides={
            "ALETHEIA_ENABLE_DEEP_RESEARCH": "0",
            "ALETHEIA_SOURCE_BUDGET_PER_RUN": _BASE_SOURCE_BUDGET,
        },
    ),
    DemoCase(
        case_id="data-api-path",
        title="Data/API-heavy path",
        claim=(
            "According to BLS data, the unemployment rate peaked at 14.7% in April 2020."
        ),
        expected_path="statistical_fact routing with data_api prioritized",
        env_overrides={
            "ALETHEIA_ENABLE_DEEP_RESEARCH": "0",
            "ALETHEIA_SOURCE_BUDGET_PER_RUN": _BASE_SOURCE_BUDGET,
        },
    ),
    DemoCase(
        case_id="fallback-path",
        title="Fallback path",
        claim=(
            "A regional consumer sentiment index doubled in one month, proving "
            "the economy is fully recovered."
        ),
        expected_path="fallback retrieval forced by source budget skips on primary sources",
        env_overrides={
            "ALETHEIA_ENABLE_DEEP_RESEARCH": "0",
            "ALETHEIA_SOURCE_BUDGET_PER_RUN": (
                "methodology_kb:0,data_api:0,document_index:0,web_fallback:1,paper_scholar:1"
            ),
        },
    ),
    DemoCase(
        case_id="deep-research-path",
        title="Deep-research path (when enabled)",
        claim=(
            "Did EU unemployment in 2021 primarily reflect real labor recovery or "
            "methodology effects in EU-LFS measurement?"
        ),
        expected_path=(
            "deep research enabled; paper_scholar executes when evidence is ambiguous"
        ),
        env_overrides={
            "ALETHEIA_ENABLE_DEEP_RESEARCH": "1",
            "ALETHEIA_DEEP_RESEARCH_CONF_THRESHOLD": "0.99",
            "ALETHEIA_SOURCE_BUDGET_PER_RUN": _BASE_SOURCE_BUDGET,
        },
    ),
]


@contextmanager
def _temporary_env(overrides: dict[str, str]):
    previous: dict[str, str | None] = {}
    for key, value in overrides.items():
        previous[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _normalize_text(value: str, max_len: int = 140) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return f"{cleaned[: max_len - 3]}..."


def _to_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _analysis_signal(run: dict[str, Any], key: str, default: Any = None) -> Any:
    analysis = run.get("analysis")
    if isinstance(analysis, dict) and key in analysis:
        return analysis[key]
    return run.get(key, default)


def _status_icon(ok: bool) -> str:
    return "OK" if ok else "MISSING"


def _print_header(ui: TerminalUI, *, quick: bool, assert_phase2: bool) -> None:
    runtime_profile = os.environ.get("ALETHEIA_RUNTIME_PROFILE", "zbook-single")
    ui.banner(
        "ALETHEIA Phase 2 Demo Integration Harness",
        (
            f"Mode: {'quick' if quick else 'interactive'} | "
            f"assert_phase2={'on' if assert_phase2 else 'off'} | "
            f"profile={runtime_profile}\n"
            "Flow: parser -> router -> evidence sources -> aggregator -> editor -> verdict"
        ),
    )


def _runtime_override_args(args: argparse.Namespace) -> dict[str, str | None]:
    return {
        "ALETHEIA_LLM_BASE_URL": getattr(args, "llm_base_url", None),
        "ALETHEIA_LLM_MODEL": getattr(args, "llm_model", None),
        "ALETHEIA_EMBED_BASE_URL": getattr(args, "embed_base_url", None),
        "ALETHEIA_EMBED_MODEL": getattr(args, "embed_model", None),
        "ALETHEIA_DB_URL": getattr(args, "db_url", None),
    }


def _print_case_report(
    result: CaseResult,
    index: int,
    total: int,
    ui: TerminalUI | None = None,
) -> None:
    ui = ui or TerminalUI(plain=True)
    run = result.run
    routing = run.get("routing_plan") if isinstance(run.get("routing_plan"), dict) else {}
    source_outputs = run.get("source_outputs") if isinstance(run.get("source_outputs"), list) else []
    evidence_docs = run.get("evidence_docs") if isinstance(run.get("evidence_docs"), list) else []

    aggregate_signal = _analysis_signal(
        run,
        "evidence_aggregate_confidence",
        run.get("aggregate_confidence"),
    )
    aggregate_conf = _to_float(
        aggregate_signal,
        0.0,
    )
    fallback_used = _to_bool(_analysis_signal(run, "fallback_used", False))
    deep_research_used = _to_bool(_analysis_signal(run, "deep_research_used", False))
    budget_skips = int(_analysis_signal(run, "provider_budget_skips", 0) or 0)

    ui.kv_table(
        f"Case {index}/{total}: {result.case.title}",
        [
            ("id", result.case.case_id),
            ("claim", result.case.claim),
            ("expected_path", result.case.expected_path),
            ("runtime_error", result.error or "none"),
        ],
    )

    if result.error:
        ui.error(f"CASE FAILED: {result.error}")

    ui.table(
        "E2E Stage Signals",
        ["Stage", "Status", "Details"],
        [
            ["parser", _status_icon(isinstance(run.get("parsed_claim"), dict)), ""],
            ["router", _status_icon(bool(routing)), ""],
            ["evidence sources", _status_icon(bool(source_outputs)), ""],
            [
                "aggregator",
                _status_icon(aggregate_signal is not None),
                f"aggregate_confidence={aggregate_conf:.3f}",
            ],
            ["editor+verdict", _status_icon(bool(run.get("verdict"))), ""],
        ],
    )

    ui.kv_table(
        "Routing Plan",
        [
            ("claim_type", routing.get("claim_type", "unknown")),
            ("source_ids", routing.get("source_ids", [])),
            ("fallback_source_id", routing.get("fallback_source_id")),
            ("deep_research_source_ids", routing.get("deep_research_source_ids", [])),
        ],
    )

    source_rows: list[list[Any]] = []
    if not source_outputs:
        source_rows.append(["(none)", 0, 0, 0, ""])
    for row in source_outputs:
        if not isinstance(row, dict):
            continue
        errors = row.get("errors") if isinstance(row.get("errors"), list) else []
        row_analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
        mode_notes = []
        if row_analysis.get("break_search_mode"):
            mode_notes.append(f"break={row_analysis.get('break_search_mode')}")
        if row_analysis.get("doc_search_mode"):
            mode_notes.append(f"docs={row_analysis.get('doc_search_mode')}")
        source_rows.append(
            [
                row.get("source_id", "unknown"),
                row.get("doc_count", 0),
                row.get("break_count", 0),
                row.get("error_count", 0),
                " | ".join(
                    part for part in [", ".join(str(e) for e in errors[:2]), ", ".join(mode_notes)] if part
                ),
            ]
        )
    ui.table(
        "Source Execution",
        ["Source", "Docs", "Breaks", "Errors", "Notes"],
        source_rows,
    )

    signal_rows: list[tuple[str, Any]] = [
        ("fallback_used", fallback_used),
        ("deep_research_used", deep_research_used),
        ("aggregate_evidence_confidence", f"{aggregate_conf:.3f}"),
        ("provider_budget_skips", budget_skips),
    ]
    claim_value_check = _analysis_signal(run, "claim_value_check")
    if isinstance(claim_value_check, dict):
        signal_rows.append(("claim_value_within_tolerance", claim_value_check.get("within_tolerance")))
        signal_rows.append(("claim_value_delta", claim_value_check.get("delta")))
    summary = _analysis_signal(run, "provider_budget_summary", {})
    if isinstance(summary, dict) and summary:
        source_summary = summary.get("sources", {})
        provider_summary = summary.get("providers", {})
        signal_rows.append(("source_budget_summary", source_summary))
        signal_rows.append(("provider_budget_summary", provider_summary))
    ui.kv_table("Runtime Signals", signal_rows)

    decomposition = _analysis_signal(run, "methodology_vs_real")
    if isinstance(decomposition, dict):
        ui.kv_table(
            "Methodology-vs-Real Decomposition",
            [
                ("observed_change", decomposition.get("observed_change")),
                (
                    "methodology_component",
                    decomposition.get("methodology_component_estimate"),
                ),
                ("real_component", decomposition.get("real_component_estimate")),
                ("methodology_share", decomposition.get("methodology_share_estimate")),
            ],
        )

    evidence_rows: list[list[Any]] = []
    if not evidence_docs:
        evidence_rows.append(["(none)", "", "", "", ""])
    for idx, doc in enumerate(evidence_docs[:3], start=1):
        if not isinstance(doc, dict):
            continue
        title = _normalize_text(str(doc.get("title") or "Untitled evidence"), max_len=72)
        snippet = _normalize_text(str(doc.get("content") or ""), max_len=120)
        evidence_rows.append(
            [
                idx,
                doc.get("source_id", "unknown"),
                f"{_to_float(doc.get('relevance_score')):.3f}",
                f"{_to_float(doc.get('confidence_score')):.3f}",
                f"{title} | {snippet}",
            ]
        )
    ui.table(
        "Top Evidence Snippets (with relevance/confidence)",
        ["#", "Source", "Relevance", "Confidence", "Snippet"],
        evidence_rows,
    )

    verdict = result.verdict
    ui.kv_table(
        "Verdict",
        [
            ("status", verdict.status.value),
            ("severity", verdict.severity.value),
            ("comparability", verdict.comparability.value),
            ("confidence", f"{verdict.confidence:.0%}"),
            ("summary", _normalize_text(verdict.summary, max_len=220)),
        ],
    )


def _validate_case_phase2_markers(result: CaseResult) -> list[str]:
    errors: list[str] = []
    case_id = result.case.case_id
    run = result.run
    if result.error:
        errors.append(f"[{case_id}] runtime_error: {result.error}")
        return errors

    parsed_claim = run.get("parsed_claim")
    if not isinstance(parsed_claim, dict):
        errors.append(f"[{case_id}] missing parsed_claim")

    routing = run.get("routing_plan")
    if not isinstance(routing, dict):
        errors.append(f"[{case_id}] missing routing_plan")
    else:
        if "claim_type" not in routing:
            errors.append(f"[{case_id}] routing_plan.claim_type missing")
        if not isinstance(routing.get("source_ids"), list):
            errors.append(f"[{case_id}] routing_plan.source_ids missing/list expected")
        if "fallback_source_id" not in routing:
            errors.append(f"[{case_id}] routing_plan.fallback_source_id missing")
        if not isinstance(routing.get("deep_research_source_ids"), list):
            errors.append(
                f"[{case_id}] routing_plan.deep_research_source_ids missing/list expected"
            )

    source_outputs = run.get("source_outputs")
    if not isinstance(source_outputs, list) or not source_outputs:
        errors.append(f"[{case_id}] source_outputs missing/empty")
    else:
        for idx, row in enumerate(source_outputs):
            if not isinstance(row, dict):
                errors.append(f"[{case_id}] source_outputs[{idx}] is not a dict")
                continue
            for key in ("source_id", "doc_count", "break_count", "error_count"):
                if key not in row:
                    errors.append(f"[{case_id}] source_outputs[{idx}].{key} missing")

    fallback_used = _analysis_signal(run, "fallback_used")
    if not isinstance(fallback_used, bool):
        errors.append(f"[{case_id}] fallback_used missing/bool expected")

    deep_research_used = _analysis_signal(run, "deep_research_used")
    if not isinstance(deep_research_used, bool):
        errors.append(f"[{case_id}] deep_research_used missing/bool expected")

    aggregate_conf = _analysis_signal(run, "evidence_aggregate_confidence", run.get("aggregate_confidence"))
    if not isinstance(aggregate_conf, (int, float)):
        errors.append(f"[{case_id}] aggregate evidence confidence missing/numeric expected")

    budget_skips = _analysis_signal(run, "provider_budget_skips")
    if not isinstance(budget_skips, int):
        errors.append(f"[{case_id}] provider_budget_skips missing/int expected")

    evidence_docs = run.get("evidence_docs")
    if not isinstance(evidence_docs, list):
        errors.append(f"[{case_id}] evidence_docs missing/list expected")
    elif evidence_docs:
        first = evidence_docs[0]
        if not isinstance(first, dict):
            errors.append(f"[{case_id}] evidence_docs[0] is not a dict")
        else:
            if not isinstance(first.get("relevance_score"), (int, float)):
                errors.append(
                    f"[{case_id}] evidence_docs[0].relevance_score missing/numeric expected"
                )
            if not isinstance(first.get("confidence_score"), (int, float)):
                errors.append(
                    f"[{case_id}] evidence_docs[0].confidence_score missing/numeric expected"
                )

    verdict = result.verdict
    if not verdict.status.value:
        errors.append(f"[{case_id}] verdict status missing")
    if not verdict.severity.value:
        errors.append(f"[{case_id}] verdict severity missing")
    if not verdict.comparability.value:
        errors.append(f"[{case_id}] verdict comparability missing")
    if not isinstance(verdict.confidence, (int, float)):
        errors.append(f"[{case_id}] verdict confidence missing/numeric expected")

    return errors


def _validate_suite_coverage(results: list[CaseResult]) -> list[str]:
    if not results:
        return ["No demo results were produced."]

    claim_types: set[str] = set()
    fallback_count = 0
    deep_count = 0

    for result in results:
        routing = result.run.get("routing_plan")
        if isinstance(routing, dict) and isinstance(routing.get("claim_type"), str):
            claim_types.add(routing["claim_type"])
        if _analysis_signal(result.run, "fallback_used", False) is True:
            fallback_count += 1
        if _analysis_signal(result.run, "deep_research_used", False) is True:
            deep_count += 1

    errors: list[str] = []
    if "methodology_aware" not in claim_types:
        errors.append("No methodology_aware routed claim observed.")
    if "statistical_fact" not in claim_types:
        errors.append("No statistical_fact routed claim observed.")
    if fallback_count == 0:
        errors.append("No fallback_used=True run observed.")
    if deep_count == 0:
        errors.append("No deep_research_used=True run observed.")
    return errors


def _phase2_checklist(results: list[CaseResult]) -> list[tuple[str, bool, str]]:
    def _any(predicate: Callable[[CaseResult], bool]) -> bool:
        return any(predicate(result) for result in results)

    def _cases(predicate: Callable[[CaseResult], bool]) -> str:
        ids = [result.case.case_id for result in results if predicate(result)]
        return ", ".join(ids) if ids else "none"

    return [
        (
            "parser -> router -> evidence -> aggregator -> editor -> verdict",
            _any(
                lambda result: isinstance(result.run.get("parsed_claim"), dict)
                and isinstance(result.run.get("routing_plan"), dict)
                and isinstance(result.run.get("source_outputs"), list)
                and isinstance(
                    _analysis_signal(
                        result.run,
                        "evidence_aggregate_confidence",
                        result.run.get("aggregate_confidence"),
                    ),
                    (int, float),
                )
                and bool(result.run.get("verdict"))
            ),
            _cases(lambda result: bool(result.run.get("verdict"))),
        ),
        (
            "routing metadata (claim_type, source_ids, fallback, deep_research_sources)",
            _any(
                lambda result: isinstance(result.run.get("routing_plan"), dict)
                and "claim_type" in result.run["routing_plan"]
                and isinstance(result.run["routing_plan"].get("source_ids"), list)
                and "fallback_source_id" in result.run["routing_plan"]
                and isinstance(
                    result.run["routing_plan"].get("deep_research_source_ids"),
                    list,
                )
            ),
            _cases(lambda result: isinstance(result.run.get("routing_plan"), dict)),
        ),
        (
            "source execution counts + errors",
            _any(lambda result: isinstance(result.run.get("source_outputs"), list) and bool(result.run.get("source_outputs"))),
            _cases(lambda result: bool(result.run.get("source_outputs"))),
        ),
        (
            "fallback_used",
            _any(lambda result: _analysis_signal(result.run, "fallback_used", False) is True),
            _cases(lambda result: _analysis_signal(result.run, "fallback_used", False) is True),
        ),
        (
            "deep_research_used",
            _any(lambda result: _analysis_signal(result.run, "deep_research_used", False) is True),
            _cases(lambda result: _analysis_signal(result.run, "deep_research_used", False) is True),
        ),
        (
            "aggregate evidence confidence",
            _any(
                lambda result: isinstance(
                    _analysis_signal(
                        result.run,
                        "evidence_aggregate_confidence",
                        result.run.get("aggregate_confidence"),
                    ),
                    (int, float),
                )
            ),
            _cases(
                lambda result: isinstance(
                    _analysis_signal(
                        result.run,
                        "evidence_aggregate_confidence",
                        result.run.get("aggregate_confidence"),
                    ),
                    (int, float),
                )
            ),
        ),
        (
            "provider/source budget skip metrics",
            _any(lambda result: isinstance(_analysis_signal(result.run, "provider_budget_skips"), int)),
            _cases(lambda result: isinstance(_analysis_signal(result.run, "provider_budget_skips"), int)),
        ),
        (
            "methodology-vs-real decomposition",
            _any(lambda result: isinstance(_analysis_signal(result.run, "methodology_vs_real"), dict)),
            _cases(lambda result: isinstance(_analysis_signal(result.run, "methodology_vs_real"), dict)),
        ),
        (
            "top evidence snippets with relevance/confidence",
            _any(
                lambda result: isinstance(result.run.get("evidence_docs"), list)
                and bool(result.run.get("evidence_docs"))
                and isinstance(result.run["evidence_docs"][0], dict)
                and isinstance(result.run["evidence_docs"][0].get("relevance_score"), (int, float))
                and isinstance(result.run["evidence_docs"][0].get("confidence_score"), (int, float))
            ),
            _cases(
                lambda result: isinstance(result.run.get("evidence_docs"), list)
                and bool(result.run.get("evidence_docs"))
            ),
        ),
        (
            "verdict + severity + comparability + confidence",
            _any(lambda result: bool(result.run.get("verdict"))),
            _cases(lambda result: bool(result.run.get("verdict"))),
        ),
    ]


async def _run_case(
    case: DemoCase,
    orchestrator_factory: Callable[[], OrchestratorAgent],
) -> CaseResult:
    orchestrator: OrchestratorAgent | None = None
    with _temporary_env(case.env_overrides):
        try:
            orchestrator = orchestrator_factory()
            verdict = await orchestrator.process_claim(case.claim)
            run = orchestrator.get_last_run_details()
            if not isinstance(run, dict):
                run = {}
            return CaseResult(case=case, verdict=verdict, run=run)
        except Exception as exc:  # noqa: BLE001
            fallback_claim = PolicyClaim(
                original_text=case.claim,
                indicator="unknown",
                confidence=0.0,
            )
            fallback_verdict = Verdict(
                claim=fallback_claim,
                status=VerdictStatus.INSUFFICIENT_DATA,
                confidence=0.0,
                severity=SeverityLevel.UNKNOWN,
                comparability=ComparabilityLevel.UNCERTAIN,
                summary=f"Case execution failed: {type(exc).__name__}",
                caveats=[str(exc)],
            )
            return CaseResult(
                case=case,
                verdict=fallback_verdict,
                run={"runtime_error": f"{type(exc).__name__}: {exc}"},
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if orchestrator is not None:
                try:
                    await orchestrator.close()
                except Exception:  # noqa: BLE001
                    pass


def _selected_cases(case_ids: Iterable[str] | None) -> list[DemoCase]:
    if not case_ids:
        return list(DEMO_CASES)
    wanted = {case_id.strip() for case_id in case_ids if case_id and case_id.strip()}
    selected = [case for case in DEMO_CASES if case.case_id in wanted]
    if not selected:
        known = ", ".join(case.case_id for case in DEMO_CASES)
        raise ValueError(f"No matching case ids. Known ids: {known}")
    return selected


async def run_demo(
    *,
    quick: bool,
    assert_phase2: bool,
    case_ids: list[str] | None = None,
    orchestrator_factory: Callable[[], OrchestratorAgent] = OrchestratorAgent,
    ui: TerminalUI | None = None,
) -> int:
    ui = ui or TerminalUI()
    cases = _selected_cases(case_ids)
    _print_header(ui, quick=quick, assert_phase2=assert_phase2)

    if not quick:
        input("\nPress Enter to start Phase 2 demo...")

    results: list[CaseResult] = []
    case_failures: list[str] = []
    for idx, case in enumerate(cases, start=1):
        result = await _run_case(case, orchestrator_factory)
        results.append(result)
        _print_case_report(result, idx, len(cases), ui=ui)
        if result.error:
            case_failures.append(f"{case.case_id}: {result.error}")

        if assert_phase2:
            case_errors = _validate_case_phase2_markers(result)
            if case_errors:
                ui.error("ASSERT-PHASE2 FAILED")
                for err in case_errors:
                    print(f"- {err}")
                return 2

        if not quick and idx < len(cases):
            input("\nPress Enter for next case...")

    if assert_phase2:
        suite_errors = _validate_suite_coverage(results)
        if suite_errors:
            ui.error("ASSERT-PHASE2 FAILED")
            for err in suite_errors:
                print(f"- {err}")
            return 2
        ui.success("ASSERT-PHASE2 PASSED")

    checklist_rows = []
    for capability, ok, where in _phase2_checklist(results):
        checklist_rows.append([capability, "PASS" if ok else "FAIL", where])
    ui.table("Phase 2 Capability Checklist", ["Capability", "Status", "Cases"], checklist_rows)
    if case_failures:
        ui.error("Demo completed with runtime failures.")
        for item in case_failures:
            print(f"- {item}")
        return 1
    ui.success("Demo Complete.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ALETHEIA Phase 2 demo harness.")
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default=None,
        help="Runtime profile to apply before executing the demo.",
    )
    parser.add_argument(
        "--profile-file",
        default=None,
        help="Optional .env-style profile file layered over built-in profile defaults.",
    )
    parser.add_argument("--llm-base-url", default=None, help="Override ALETHEIA_LLM_BASE_URL.")
    parser.add_argument("--llm-model", default=None, help="Override ALETHEIA_LLM_MODEL.")
    parser.add_argument("--embed-base-url", default=None, help="Override ALETHEIA_EMBED_BASE_URL.")
    parser.add_argument("--embed-model", default=None, help="Override ALETHEIA_EMBED_MODEL.")
    parser.add_argument("--db-url", default=None, help="Override ALETHEIA_DB_URL.")
    parser.add_argument(
        "--quick",
        "-q",
        action="store_true",
        help="Run non-interactive mode.",
    )
    parser.add_argument(
        "--assert-phase2",
        action="store_true",
        help="Exit non-zero if required Phase 2 markers are missing.",
    )
    parser.add_argument(
        "--case",
        action="append",
        help="Run only specific case id(s). Repeat for multiple.",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Disable rich formatting and use plain text output.",
    )
    args = parser.parse_args()
    try:
        apply_runtime_profile(
            profile=args.profile,
            profile_file=args.profile_file,
            cli_overrides=_runtime_override_args(args),
        )
    except ValueError as exc:
        print(f"profile error: {exc}")
        return 2
    ui = TerminalUI(plain=args.plain)

    try:
        return asyncio.run(
            run_demo(
                quick=args.quick,
                assert_phase2=args.assert_phase2,
                case_ids=args.case,
                ui=ui,
            )
        )
    except ValueError as exc:
        ui.error(str(exc))
        return 2
    except Exception as exc:  # noqa: BLE001
        ui.error(f"Demo failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
