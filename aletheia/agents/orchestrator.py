"""Chief Analyst (Orchestrator) - coordinates the multi-agent pipeline."""

from datetime import datetime
from typing import Any

from aletheia.agents.base import Agent
from aletheia.agents.analyst import AnalystAgent
from aletheia.agents.archivist import ArchivistAgent
from aletheia.agents.editor import EditorAgent
from aletheia.agents.parser import ClaimParserAgent
from aletheia.evidence import (
    ClaimRouter,
    DataApiEvidenceSource,
    DocumentIndexEvidenceSource,
    EvidenceAggregator,
    EvidencePipeline,
    MethodologyEvidenceSource,
    ScholarPaperEvidenceSource,
    WebSearchEvidenceSource,
)
from aletheia.retrieval_store import RetrievalStore
from aletheia.schema import AgentMessage, PolicyClaim, Verdict
from aletheia.source_registry import SourceRegistry
from aletheia.web_search import WebSearchClient


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
        self.source_registry = SourceRegistry.default()
        self.retrieval_store = RetrievalStore()
        self.router = ClaimRouter()
        self.web_search_client = WebSearchClient()
        self.evidence_pipeline = EvidencePipeline(
            router=self.router,
            sources={
                "methodology_kb": MethodologyEvidenceSource(self.archivist),
                "document_index": DocumentIndexEvidenceSource(self.archivist),
                "data_api": DataApiEvidenceSource(self.analyst),
                "web_fallback": WebSearchEvidenceSource(
                    search_client=self.web_search_client,
                    retrieval_store=self.retrieval_store,
                ),
                "paper_scholar": ScholarPaperEvidenceSource(
                    search_client=self.web_search_client,
                    retrieval_store=self.retrieval_store,
                ),
            },
            aggregator=EvidenceAggregator(self.source_registry),
            retrieval_store=self.retrieval_store,
        )
        self.trace: list[AgentMessage] = []
        self.last_run_details: dict[str, Any] = {}

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
        self.last_run_details = {}
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

        # Step 2: Route claim to source strategy and aggregate evidence.
        self._log_message("ChiefAnalyst", "Router", "request", "Select evidence strategy")
        aggregated = await self.evidence_pipeline.collect(claim)
        breaks = aggregated.breaks
        analysis = dict(aggregated.analysis)
        evidence_docs = aggregated.evidence_docs

        analysis["routing"] = {
            "claim_type": aggregated.plan.claim_type.value,
            "sources": aggregated.plan.source_ids,
            "fallback_source_id": aggregated.plan.fallback_source_id,
            "deep_research_source_ids": aggregated.plan.deep_research_source_ids,
        }
        analysis["evidence_aggregate_confidence"] = aggregated.aggregate_confidence
        analysis["fallback_used"] = aggregated.fallback_used

        self._log_message(
            "Router",
            "ChiefAnalyst",
            "response",
            (
                f"type={aggregated.plan.claim_type.value} "
                f"sources={aggregated.plan.source_ids} "
                f"fallback={aggregated.plan.fallback_source_id}"
            ),
        )
        for output in aggregated.source_outputs:
            self._log_message(
                output.source_id,
                "ChiefAnalyst",
                "response",
                (
                    f"breaks={len(output.breaks)} docs={len(output.evidence_docs)} "
                    f"errors={len(output.errors)}"
                ),
            )

        decomposition = self.analyst.quantify_methodology_vs_reality(
            claim=claim,
            breaks=breaks,
            analysis=analysis,
        )
        if decomposition:
            analysis["methodology_vs_real"] = decomposition

        source_outputs_summary = [
            {
                "source_id": output.source_id,
                "break_count": len(output.breaks),
                "doc_count": len(output.evidence_docs),
                "error_count": len(output.errors),
                "errors": list(output.errors),
            }
            for output in aggregated.source_outputs
        ]
        self.last_run_details = {
            "claim_text": text,
            "parsed_claim": claim.model_dump(mode="json"),
            "routing_plan": {
                "claim_type": aggregated.plan.claim_type.value,
                "source_ids": list(aggregated.plan.source_ids),
                "fallback_source_id": aggregated.plan.fallback_source_id,
                "deep_research_source_ids": list(aggregated.plan.deep_research_source_ids),
            },
            "source_outputs": source_outputs_summary,
            "break_count": len(breaks),
            "analysis": analysis,
            "evidence_docs": evidence_docs,
            "aggregate_confidence": aggregated.aggregate_confidence,
            "fallback_used": aggregated.fallback_used,
            "deep_research_used": bool(analysis.get("deep_research_used", False)),
        }

        self._log_message("Archivist", "ChiefAnalyst", "response", f"Found {len(breaks)} breaks")
        self._log_message("Analyst", "ChiefAnalyst", "response", str(analysis))
        self._log_message("Aggregator", "ChiefAnalyst", "response", f"Ranked {len(evidence_docs)} evidence snippets")
        self.log(f"Found {len(breaks)} methodology breaks")

        # Step 3: Synthesize verdict
        self._log_message("ChiefAnalyst", "Editor", "request", "Synthesize verdict")
        verdict = await self.editor.synthesize(
            claim,
            breaks,
            analysis,
            evidence_docs=evidence_docs,
        )
        self._log_message("Editor", "ChiefAnalyst", "response", verdict.status.value)
        self.last_run_details["verdict"] = {
            "status": verdict.status.value,
            "severity": verdict.severity.value,
            "comparability": verdict.comparability.value,
            "confidence": verdict.confidence,
        }

        self.log(f"Verdict: {verdict.status.value}")
        return verdict

    async def close(self):
        """Clean up resources."""
        await self.analyst.close()
        await self.evidence_pipeline.close()
        await self.llm.close()
        # All agents share the same default llm client, so closing once is enough

    def get_trace(self) -> list[dict]:
        """Get the audit trail of agent communications."""
        return [msg.model_dump() for msg in self.trace]

    def get_last_run_details(self) -> dict[str, Any]:
        """Get structured details from the most recent process_claim run."""
        return dict(self.last_run_details)
