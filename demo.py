#!/usr/bin/env python
"""
ALETHEIA Demo - Methodology-Aware Policy Intelligence
======================================================

This demo showcases ALETHEIA's ability to detect methodology breaks
that could make policy claims misleading.

Run: uv run python demo.py
"""

import asyncio
from aletheia.agents.orchestrator import OrchestratorAgent

# ANSI colors
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"

DEMO_CLAIMS = [
    {
        "title": "Case 1: NHIS E-Cigarette Use (2019 Questionnaire Redesign)",
        "claim": "E-cigarette use among US adults increased from 3.2% to 4.4% in 2019 according to NHIS data.",
        "expected": "MISLEADING - the 2019 questionnaire redesign accounts for ~0.5-1.0 pp of the change",
    },
    {
        "title": "Case 2: COVID Unemployment Misclassification",
        "claim": "The unemployment rate peaked at 14.7% in April 2020 according to BLS data.",
        "expected": "PARTIALLY_SUPPORTED - misclassification understated true unemployment by ~1pp",
    },
    {
        "title": "Case 3: EU Unemployment Definition Change",
        "claim": "EU unemployment fell sharply in 2021, showing strong labor market recovery.",
        "expected": "PARTIALLY_SUPPORTED - 2021 definition change reduced rate by ~0.3-0.4pp",
    },
]


def print_header():
    print(f"\n{BOLD}{'=' * 70}{RESET}")
    print(f"{BOLD}  ALETHEIA - Methodology-Aware Policy Intelligence Demo{RESET}")
    print(f"{BOLD}{'=' * 70}{RESET}")
    print(f"""
{GRAY}ALETHEIA bridges two disconnected worlds:{RESET}
  1. Statistical anomaly detection (finds unusual patterns)
  2. Policy/compliance AI (reasons about documentation)

{GRAY}We read methodology documentation AND analyze data simultaneously,
reasoning about whether claims are trustworthy given what the
documentation says about measurement changes.{RESET}
""")


def print_verdict(verdict, expected: str):
    status_colors = {
        "supported": GREEN,
        "partially_supported": YELLOW,
        "misleading": RED,
        "insufficient_data": GRAY,
    }
    color = status_colors.get(verdict.status.value, RESET)

    print(f"\n{BOLD}VERDICT: {color}{verdict.status.value.upper()}{RESET}")
    print(
        f"{GRAY}Severity: {verdict.severity.value} | "
        f"Comparability: {verdict.comparability.value}{RESET}"
    )
    print(f"{GRAY}Expected: {expected}{RESET}")

    print(f"\n{BOLD}Summary:{RESET}")
    print(f"  {verdict.summary[:300]}...")

    if verdict.breaks_found:
        print(f"\n{BOLD}Methodology Breaks Detected:{RESET}")
        for b in verdict.breaks_found[:2]:
            date_str = b.effective_date.isoformat() if b.effective_date else "?"
            print(f"  {YELLOW}[{date_str}]{RESET} {b.change_type.value}")
            if b.impact_estimate:
                print(f"  {GRAY}Impact: {b.impact_estimate[:100]}...{RESET}")

    if verdict.methodology_vs_real:
        mvr = verdict.methodology_vs_real
        print(
            f"{GRAY}Methodology share estimate: "
            f"{mvr.get('methodology_share_estimate', 0.0):.0%}{RESET}"
        )

    print(f"\n{GRAY}Confidence: {verdict.confidence:.0%}{RESET}")


async def run_demo():
    print_header()
    input(f"\n{BLUE}Press Enter to start the demo...{RESET}")

    orchestrator = OrchestratorAgent()

    try:
        for i, case in enumerate(DEMO_CLAIMS, 1):
            print(f"\n{BOLD}{'=' * 70}{RESET}")
            print(f"{BOLD}{case['title']}{RESET}")
            print(f"{'=' * 70}")
            print(f'\n{BLUE}Claim:{RESET} "{case["claim"]}"')
            print(f"\n{GRAY}Analyzing...{RESET}")

            verdict = await orchestrator.process_claim(case["claim"])
            print_verdict(verdict, case["expected"])

            if i < len(DEMO_CLAIMS):
                input(f"\n{BLUE}Press Enter for next case...{RESET}")

    finally:
        await orchestrator.close()

    print(f"\n{BOLD}{'=' * 70}{RESET}")
    print(f"{BOLD}  Demo Complete{RESET}")
    print(f"{'=' * 70}")
    print(f"""
{GRAY}Key Takeaways:{RESET}
  1. ALETHEIA parses natural language claims into structured queries
  2. Searches a knowledge graph of methodology changes
  3. Connects methodology documentation to specific time periods
  4. Produces verdicts with full provenance and source citations

{GRAY}Next Steps:{RESET}
  - Add real-time data retrieval from BLS, Census, FRED APIs
  - Implement statistical break detection (Chow test, CUSUM)
  - Ingest methodology documents (pgai vectorizer auto-generates embeddings)
  - Build the Watchdog agent for continuous monitoring
""")


async def run_quick_demo():
    """Non-interactive demo for quick presentations."""
    print_header()

    orchestrator = OrchestratorAgent()

    try:
        for i, case in enumerate(DEMO_CLAIMS, 1):
            print(f"\n{BOLD}{'=' * 70}{RESET}")
            print(f"{BOLD}{case['title']}{RESET}")
            print(f"{'=' * 70}")
            print(f'\n{BLUE}Claim:{RESET} "{case["claim"]}"')
            print(f"\n{GRAY}Analyzing...{RESET}")

            verdict = await orchestrator.process_claim(case["claim"])
            print_verdict(verdict, case["expected"])
            print()

    finally:
        await orchestrator.close()

    print(f"\n{BOLD}Demo Complete.{RESET}\n")


if __name__ == "__main__":
    import sys

    if "--quick" in sys.argv or "-q" in sys.argv:
        asyncio.run(run_quick_demo())
    else:
        asyncio.run(run_demo())
