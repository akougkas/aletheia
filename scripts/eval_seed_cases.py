#!/usr/bin/env python
"""Evaluation harness for Aletheia methodology-break detection.

Reads Phase 3 benchmark cases from the DB, constructs natural-language claims,
runs each through the full pipeline, and scores whether the correct methodology
break was surfaced.

Usage:
    uv run python scripts/eval_seed_cases.py [--limit N] [--case PH3-001]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

# Ensure project root is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aletheia.agents.orchestrator import OrchestratorAgent
from aletheia.db import get_db_url
from aletheia.runtime_profiles import apply_runtime_profile


# ---------------------------------------------------------------------------
# Claim templates keyed by (dataset_name_fragment, indicator_hint).
# Fallback: generic template at the end.
# ---------------------------------------------------------------------------

_CLAIM_TEMPLATES: list[tuple[set[str], str]] = [
    (
        {"current population survey", "cps"},
        "The US {indicator} changed significantly around {year}",
    ),
    (
        {"american community survey", "acs"},
        "US {indicator} trends shifted around {year} according to ACS data",
    ),
    (
        {"national health interview survey", "nhis"},
        "US {indicator} patterns changed around {year} in NHIS data",
    ),
    (
        {"eu labour force survey", "eu-lfs"},
        "EU unemployment {direction} around {year}",
    ),
    (
        {"consumer price index", "cpi"},
        "US inflation {direction} around {year}",
    ),
    (
        {"harmonised index of consumer prices", "hicp"},
        "Euro area inflation {direction} around {year}",
    ),
    (
        {"eurostat weekly mortality", "mortality"},
        "European excess mortality figures changed around {year}",
    ),
    (
        {"european system of accounts", "esa"},
        "Euro area GDP was revised around {year}",
    ),
    (
        {"eu statistics on income and living conditions", "eu-silc", "silc"},
        "EU poverty rates changed around {year}",
    ),
]

_GENERIC_TEMPLATE = "Statistical {indicator} data changed around {year}"


def _build_claim(case: dict[str, Any]) -> str:
    """Construct a natural-language claim from a benchmark case."""
    ds = (case.get("dataset_name") or "").lower()
    desc = (case.get("description") or "").lower()
    eff: date | None = case.get("effective_date")
    year = eff.year if eff else "2020"

    # Derive a rough indicator from the description.
    indicator = "employment"
    if "poverty" in desc or "income" in desc or "deprivation" in desc:
        indicator = "poverty"
    elif "inflation" in desc or "price" in desc or "cpi" in desc or "hicp" in desc:
        indicator = "inflation"
    elif "unemployment" in desc or "labor" in desc or "labour" in desc:
        indicator = "unemployment"
    elif "mortality" in desc or "death" in desc:
        indicator = "mortality"
    elif "gdp" in desc or "national account" in desc:
        indicator = "GDP"

    direction = "shifted" if case.get("change_type") in {"weighting_update", "sample_redesign"} else "changed"

    for keywords, template in _CLAIM_TEMPLATES:
        if any(k in ds for k in keywords):
            return template.format(indicator=indicator, year=year, direction=direction)

    return _GENERIC_TEMPLATE.format(indicator=indicator, year=year)


def _break_matches(verdict_breaks: list[dict[str, Any]], case: dict[str, Any]) -> bool:
    """Check if any break in the verdict matches the benchmark case."""
    target_type = case.get("change_type", "")
    target_date = case.get("effective_date")
    target_year = target_date.year if target_date else None
    target_desc = (case.get("description") or "").lower()

    for brk in verdict_breaks:
        brk_type = brk.get("change_type", "")
        brk_date = brk.get("effective_date")
        brk_desc = (brk.get("description") or "").lower()

        # Exact type + year match.
        brk_year = None
        if isinstance(brk_date, str) and len(brk_date) >= 4:
            try:
                brk_year = int(brk_date[:4])
            except ValueError:
                pass
        elif isinstance(brk_date, date):
            brk_year = brk_date.year

        if brk_type == target_type and brk_year == target_year:
            return True

        # Fuzzy: same year + significant keyword overlap in description.
        if brk_year == target_year:
            target_words = set(target_desc.split())
            brk_words = set(brk_desc.split())
            overlap = len(target_words & brk_words)
            if overlap >= 4:
                return True

    return False


def _load_cases(limit: int | None, case_id: str | None) -> list[dict[str, Any]]:
    """Load PH3 benchmark cases from the DB."""
    with psycopg.connect(get_db_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            if case_id:
                cur.execute(
                    """
                    SELECT mc.*, d.name AS dataset_name
                    FROM methodology_changes mc
                    LEFT JOIN datasets d ON mc.dataset_id = d.id
                    WHERE mc.benchmark_case_id = %s
                    """,
                    (case_id,),
                )
            else:
                query = """
                    SELECT mc.*, d.name AS dataset_name
                    FROM methodology_changes mc
                    LEFT JOIN datasets d ON mc.dataset_id = d.id
                    WHERE mc.benchmark_case_id LIKE 'PH3-%%'
                    ORDER BY mc.benchmark_case_id
                """
                if limit:
                    query += f" LIMIT {int(limit)}"
                cur.execute(query)
            return cur.fetchall()


async def _run_eval(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run the pipeline for each case and collect results."""
    orchestrator = OrchestratorAgent()
    results: list[dict[str, Any]] = []

    for i, case in enumerate(cases, 1):
        case_id = case["benchmark_case_id"]
        claim_text = _build_claim(case)
        print(f"\n[{i}/{len(cases)}] {case_id}: {claim_text}")
        print(f"  Expected: type={case['change_type']}, date={case['effective_date']}")

        t0 = time.monotonic()
        try:
            verdict = await orchestrator.process_claim(claim_text)
            elapsed = time.monotonic() - t0

            # Extract break dicts from verdict.
            breaks_raw = []
            for b in verdict.breaks_found:
                if hasattr(b, "model_dump"):
                    breaks_raw.append(b.model_dump())
                elif isinstance(b, dict):
                    breaks_raw.append(b)

            found = _break_matches(breaks_raw, case)

            result = {
                "case_id": case_id,
                "claim": claim_text,
                "status": verdict.status.value,
                "confidence": verdict.confidence,
                "breaks_count": len(verdict.breaks_found),
                "break_found": found,
                "elapsed_s": round(elapsed, 1),
                "error": None,
            }
            tag = "PASS" if found else "MISS"
            print(
                f"  {tag} | status={verdict.status.value} conf={verdict.confidence:.0%} "
                f"breaks={len(verdict.breaks_found)} elapsed={elapsed:.1f}s"
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - t0
            result = {
                "case_id": case_id,
                "claim": claim_text,
                "status": "error",
                "confidence": 0.0,
                "breaks_count": 0,
                "break_found": False,
                "elapsed_s": round(elapsed, 1),
                "error": str(exc),
            }
            print(f"  ERROR | {exc} ({elapsed:.1f}s)")

        results.append(result)

    return results


def _print_summary(results: list[dict[str, Any]]) -> None:
    """Print a summary table."""
    total = len(results)
    passed = sum(1 for r in results if r["break_found"])
    errors = sum(1 for r in results if r["error"])
    avg_conf = sum(r["confidence"] for r in results) / total if total else 0
    avg_time = sum(r["elapsed_s"] for r in results) / total if total else 0

    print("\n" + "=" * 78)
    print(f"{'Case':<10} {'Status':<22} {'Conf':>5} {'Breaks':>6} {'Match':>5} {'Time':>6}")
    print("-" * 78)
    for r in results:
        tag = "PASS" if r["break_found"] else ("ERR" if r["error"] else "MISS")
        print(
            f"{r['case_id']:<10} {r['status']:<22} {r['confidence']:>4.0%} "
            f"{r['breaks_count']:>6} {tag:>5} {r['elapsed_s']:>5.1f}s"
        )
    print("-" * 78)
    print(
        f"{'TOTAL':<10} {passed}/{total} passed ({passed/total:.0%})  "
        f"errors={errors}  avg_conf={avg_conf:.0%}  avg_time={avg_time:.1f}s"
    )
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description="Eval harness for Aletheia seed cases")
    parser.add_argument("--limit", type=int, default=10, help="Max cases to evaluate (default 10)")
    parser.add_argument("--case", type=str, default=None, help="Run a single case (e.g. PH3-016)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    apply_runtime_profile()

    cases = _load_cases(args.limit, args.case)
    if not cases:
        print("No benchmark cases found.")
        return 1

    print(f"Evaluating {len(cases)} benchmark case(s)...")
    results = asyncio.run(_run_eval(cases))

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        _print_summary(results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
