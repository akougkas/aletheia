"""Verdict & Synthesis Agent (The Editor) - produces final verdicts."""

from aletheia.agents.base import Agent
from aletheia.schema import (
    PolicyClaim,
    MethodologyChange,
    Verdict,
    VerdictStatus,
)


EDITOR_SYSTEM_PROMPT = """You are The Editor, synthesizing findings into policy verdicts.

Given:
1. A policy claim
2. Methodology breaks found in the knowledge base
3. Data analysis results (if available)

Produce a clear, evidence-based verdict on whether the claim is:
- SUPPORTED: The claim accurately reflects the data with no significant methodology concerns
- PARTIALLY_SUPPORTED: The claim has merit but methodology changes affect interpretation
- MISLEADING: The claim ignores or misrepresents methodology changes that significantly impact the data
- INSUFFICIENT_DATA: Cannot determine due to missing information

Always cite specific methodology changes and their documented impacts.
Be precise about caveats and alternative interpretations."""


class EditorAgent(Agent):
    """Synthesizes findings into verdicts with full provenance."""

    name = "Editor"
    role = "Verdict Synthesis"
    system_prompt = EDITOR_SYSTEM_PROMPT

    async def synthesize(
        self,
        claim: PolicyClaim,
        breaks: list[MethodologyChange],
        analysis: dict,
    ) -> Verdict:
        """Synthesize all findings into a final verdict."""

        # Determine verdict status based on findings
        if not breaks:
            # No methodology breaks found
            if analysis.get("data_retrieved"):
                status = VerdictStatus.SUPPORTED
                summary = f"No methodology breaks found affecting {claim.indicator}. Claim appears consistent with available data."
            else:
                status = VerdictStatus.INSUFFICIENT_DATA
                summary = f"No methodology breaks found, but data retrieval was not available to verify the claim."
            caveats = []
        else:
            # Methodology breaks found - assess severity
            recent_breaks = [
                b for b in breaks
                if b.effective_date and claim.period_start
                and (isinstance(claim.period_start, int) and b.effective_date.year >= claim.period_start - 1)
            ]

            if recent_breaks:
                status = VerdictStatus.PARTIALLY_SUPPORTED if len(recent_breaks) == 1 else VerdictStatus.MISLEADING
                break_descriptions = [f"- {b.change_type.value}: {b.description}" for b in recent_breaks[:3]]
                summary = f"Found {len(recent_breaks)} methodology change(s) affecting {claim.indicator} during the claimed period:\n" + "\n".join(break_descriptions)
                caveats = [b.impact_estimate for b in recent_breaks if b.impact_estimate]
            else:
                status = VerdictStatus.PARTIALLY_SUPPORTED
                summary = f"Found {len(breaks)} historical methodology change(s) for {claim.indicator}, but none directly overlap with the claimed period."
                caveats = ["Earlier methodology changes may still affect trend interpretation"]

        # Use LLM to generate a more detailed summary if we have breaks
        if breaks:
            prompt = f"""Given this policy claim and methodology findings, write a 2-3 sentence assessment.

Claim: "{claim.original_text}"

Methodology breaks found:
{chr(10).join(f'- {b.change_type.value} ({b.effective_date}): {b.description}' for b in breaks[:5])}

Assessment:"""

            llm_summary = await self.think(prompt, temperature=0.3, max_tokens=512)
            if llm_summary.strip():
                summary = llm_summary.strip()

        # Collect sources
        sources = [b.source_url for b in breaks if b.source_url]

        return Verdict(
            claim=claim,
            status=status,
            confidence=0.7 if breaks else 0.5,
            breaks_found=breaks,
            summary=summary,
            caveats=caveats,
            sources=sources,
        )
