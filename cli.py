#!/usr/bin/env python
"""ALETHEIA CLI - Methodology-Aware Policy Intelligence."""

import asyncio
import sys
import json

from aletheia.agents.orchestrator import OrchestratorAgent


BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_verdict(verdict):
    """Pretty-print a verdict."""
    status_colors = {
        "supported": GREEN,
        "partially_supported": YELLOW,
        "misleading": RED,
        "insufficient_data": GRAY,
    }
    color = status_colors.get(verdict.status.value, RESET)

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}VERDICT: {color}{verdict.status.value.upper()}{RESET}")
    print(f"{'='*60}")

    print(f"\n{BOLD}Claim:{RESET}")
    print(f"  {verdict.claim.original_text}")

    print(f"\n{BOLD}Summary:{RESET}")
    print(f"  {verdict.summary}")

    if verdict.breaks_found:
        print(f"\n{BOLD}Methodology Breaks Found ({len(verdict.breaks_found)}):{RESET}")
        for b in verdict.breaks_found[:5]:
            date_str = b.effective_date.isoformat() if b.effective_date else "unknown date"
            print(f"  {YELLOW}•{RESET} [{date_str}] {b.change_type.value}")
            print(f"    {b.description[:100]}...")
            if b.impact_estimate:
                print(f"    {GRAY}Impact: {b.impact_estimate}{RESET}")

    if verdict.caveats:
        print(f"\n{BOLD}Caveats:{RESET}")
        for c in verdict.caveats:
            print(f"  {GRAY}• {c}{RESET}")

    if verdict.sources:
        print(f"\n{BOLD}Sources:{RESET}")
        for s in verdict.sources[:3]:
            print(f"  {BLUE}{s}{RESET}")

    print(f"\n{GRAY}Confidence: {verdict.confidence:.0%}{RESET}")
    print()


async def interactive_mode():
    """Run interactive CLI."""
    print(f"{BOLD}ALETHEIA{RESET} - Methodology-Aware Policy Intelligence")
    print(f"{GRAY}Type a policy claim to analyze, or 'quit' to exit.{RESET}\n")

    orchestrator = OrchestratorAgent()

    try:
        while True:
            try:
                claim = input(f"{BLUE}claim>{RESET} ").strip()
            except EOFError:
                break

            if not claim:
                continue
            if claim.lower() in ("quit", "exit", "q"):
                break

            if claim.lower() == "trace":
                # Show last trace
                print(json.dumps(orchestrator.get_trace(), indent=2, default=str))
                continue

            print(f"\n{GRAY}Analyzing...{RESET}")
            verdict = await orchestrator.process_claim(claim)
            print_verdict(verdict)

    finally:
        await orchestrator.close()
        print("Goodbye.")


async def single_claim(claim: str):
    """Process a single claim and exit."""
    orchestrator = OrchestratorAgent()
    try:
        verdict = await orchestrator.process_claim(claim)
        print_verdict(verdict)
        # Also output JSON for programmatic use
        print(f"\n{GRAY}JSON output:{RESET}")
        print(verdict.model_dump_json(indent=2))
    finally:
        await orchestrator.close()


def main():
    if len(sys.argv) > 1:
        # Process claim from command line
        claim = " ".join(sys.argv[1:])
        asyncio.run(single_claim(claim))
    else:
        # Interactive mode
        asyncio.run(interactive_mode())


if __name__ == "__main__":
    main()
