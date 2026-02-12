"""Chief Analyst (Orchestrator) - coordinates the multi-agent pipeline."""

import asyncio
from typing import Optional
from datetime import datetime

from aletheia.agents.base import Agent
from aletheia.agents.parser import ClaimParserAgent
from aletheia.agents.archivist import ArchivistAgent
from aletheia.agents.analyst import AnalystAgent
from aletheia.agents.editor import EditorAgent
from aletheia.schema import PolicyClaim, Verdict, AgentMessage


class OrchestratorAgent(Agent):
    """Coordinates the ALETHEIA pipeline: parse → search → analyze → synthesize."""

    name = "ChiefAnalyst"
    role = "Orchestrator"
    system_prompt = "You coordinate the analysis of policy claims for methodology awareness."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.parser = ClaimParserAgent()
        self.archivist = ArchivistAgent()
        self.analyst = AnalystAgent()
        self.editor = EditorAgent()
        self.trace: list[AgentMessage] = []

    def _log_message(self, sender: str, receiver: str, msg_type: str, payload: str):
        """Log inter-agent communication for audit trail."""
        self.trace.append(
            AgentMessage(
                sender=sender,
                receiver=receiver,
                msg_type=msg_type,
                payload=payload,
                timestamp=datetime.utcnow(),
            )
        )

    async def process_claim(self, text: str) -> Verdict:
        """Process a natural language claim through the full pipeline."""
        self.trace = []  # Reset trace for new claim
        self.log(f"Processing claim: {text[:100]}...")

        # Step 1: Parse the claim
        self._log_message("User", "Auditor", "request", text)
        claim = await self.parser.parse(text)

        if not claim:
            self.log("Failed to parse claim, creating minimal claim object")
            claim = PolicyClaim(
                original_text=text,
                indicator="unknown",
                confidence=0.0,
            )

        self._log_message("Auditor", "ChiefAnalyst", "response", claim.model_dump_json())
        self.log(f"Parsed claim: indicator={claim.indicator}, dataset={claim.dataset}")

        # Step 2: Query knowledge base for methodology breaks (parallel with data fetch)
        self._log_message("ChiefAnalyst", "Archivist", "request", f"Find breaks for {claim.dataset}")
        self._log_message("ChiefAnalyst", "Analyst", "request", f"Fetch data for {claim.indicator}")

        # Run archivist and analyst in parallel
        breaks_task = self.archivist.find_breaks(claim)
        analysis_task = self.analyst.analyze(claim)

        breaks, analysis = await asyncio.gather(breaks_task, analysis_task)

        self._log_message("Archivist", "ChiefAnalyst", "response", f"Found {len(breaks)} breaks")
        self._log_message("Analyst", "ChiefAnalyst", "response", str(analysis))
        self.log(f"Found {len(breaks)} methodology breaks")

        # Step 3: Synthesize verdict
        self._log_message("ChiefAnalyst", "Editor", "request", "Synthesize verdict")
        verdict = await self.editor.synthesize(claim, breaks, analysis)
        self._log_message("Editor", "ChiefAnalyst", "response", verdict.status.value)

        self.log(f"Verdict: {verdict.status.value}")
        return verdict

    async def close(self):
        """Clean up resources."""
        await self.llm.close()
        # All agents share the same default llm client, so closing once is enough

    def get_trace(self) -> list[dict]:
        """Get the audit trail of agent communications."""
        return [msg.model_dump() for msg in self.trace]
