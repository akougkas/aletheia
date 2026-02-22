"""Verdict & Synthesis Agent (The Editor) - produces final verdicts."""

from __future__ import annotations

import os
from typing import Any

from aletheia.agents.base import Agent
from aletheia.schema import (
    ComparabilityLevel,
    PolicyClaim,
    MethodologyChange,
    SeverityLevel,
    Verdict,
    VerdictStatus,
)
from aletheia.time_utils import extract_year


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

    _severity_rank = {
        SeverityLevel.UNKNOWN: 0,
        SeverityLevel.MINOR: 1,
        SeverityLevel.MODERATE: 2,
        SeverityLevel.MAJOR: 3,
    }

    _comparability_rank = {
        ComparabilityLevel.COMPARABLE: 0,
        ComparabilityLevel.COMPARABLE_WITH_ADJUSTMENTS: 1,
        ComparabilityLevel.UNCERTAIN: 2,
        ComparabilityLevel.NOT_COMPARABLE: 3,
    }

    def _is_relevant_break(
        self,
        change: MethodologyChange,
        start_year: int | None,
        end_year: int | None,
    ) -> bool:
        if change.effective_date is None:
            return True
        change_year = change.effective_date.year
        effective_start = start_year if start_year is not None else end_year
        effective_end = end_year if end_year is not None else start_year
        if effective_start is None and effective_end is None:
            return True
        effective_start = effective_start if effective_start is not None else effective_end
        effective_end = effective_end if effective_end is not None else effective_start
        return (effective_start - 1) <= change_year <= (effective_end + 1)

    def _max_severity(self, breaks: list[MethodologyChange]) -> SeverityLevel:
        best = SeverityLevel.UNKNOWN
        for change in breaks:
            severity = change.severity or SeverityLevel.UNKNOWN
            if self._severity_rank[severity] > self._severity_rank[best]:
                best = severity
        return best

    def _max_comparability(self, breaks: list[MethodologyChange]) -> ComparabilityLevel:
        # Higher rank means less comparable.
        worst = ComparabilityLevel.COMPARABLE
        for change in breaks:
            comparability = change.comparability or ComparabilityLevel.UNCERTAIN
            if self._comparability_rank[comparability] > self._comparability_rank[worst]:
                worst = comparability
        return worst

    def _is_normal_revision(self, change: MethodologyChange) -> bool:
        text = f"{change.description} {change.impact_estimate or ''}".lower()
        revision_terms = ("revision", "late registration", "backlog", "preliminary")
        return change.change_type.value == "other" and any(term in text for term in revision_terms)

    def _has_overlapping_breaks(self, breaks: list[MethodologyChange]) -> bool:
        years = [extract_year(change.effective_date) for change in breaks if change.effective_date]
        if len(years) < 2:
            return False
        return (max(years) - min(years)) <= 1

    def _build_summary(
        self,
        claim: PolicyClaim,
        status: VerdictStatus,
        comparability: ComparabilityLevel,
        relevant_breaks: list[MethodologyChange],
        decomposition: dict[str, Any] | None,
    ) -> str:
        if status == VerdictStatus.SUPPORTED:
            return (
                f"No material methodology breaks were found for {claim.indicator}; "
                "the claim is consistent with currently retrieved evidence."
            )

        if status == VerdictStatus.INSUFFICIENT_DATA:
            return (
                "Methodology notes were searched, but available data connectors did not return "
                "enough evidence to verify the claim end-to-end."
            )

        break_count = len(relevant_breaks)
        summary = (
            f"Detected {break_count} methodology break(s) relevant to {claim.indicator}; "
            f"comparability is assessed as {comparability.value}."
        )
        if decomposition:
            share = decomposition.get("methodology_share_estimate")
            share_value = float(share) if isinstance(share, (int, float)) else 0.0
            summary += (
                f" Estimated methodology share of observed change: "
                f"{share_value:.0%}."
            )
        return summary

    async def synthesize(
        self,
        claim: PolicyClaim,
        breaks: list[MethodologyChange],
        analysis: dict,
        evidence_docs: list[dict] | None = None,
    ) -> Verdict:
        """Synthesize all findings into a final verdict."""
        evidence_docs = evidence_docs or []
        evidence_docs = sorted(
            evidence_docs,
            key=lambda row: (
                float(row.get("confidence_score", 0.0)),
                float(row.get("relevance_score", 0.0)),
            ),
            reverse=True,
        )
        period_start_year = extract_year(claim.period_start)
        period_end_year = extract_year(claim.period_end)
        relevant_breaks = [
            change
            for change in breaks
            if self._is_relevant_break(change, period_start_year, period_end_year)
        ]
        historical_breaks = [change for change in breaks if change not in relevant_breaks]

        comparability = (
            self._max_comparability(relevant_breaks)
            if relevant_breaks
            else (self._max_comparability(breaks) if breaks else ComparabilityLevel.COMPARABLE)
        )
        severity = (
            self._max_severity(relevant_breaks)
            if relevant_breaks
            else (self._max_severity(breaks) if breaks else SeverityLevel.UNKNOWN)
        )

        overlapping_breaks = self._has_overlapping_breaks(relevant_breaks)
        if overlapping_breaks and severity in {SeverityLevel.MINOR, SeverityLevel.MODERATE}:
            severity = SeverityLevel.MAJOR if severity == SeverityLevel.MODERATE else SeverityLevel.MODERATE

        normal_revision_only = bool(relevant_breaks) and all(
            self._is_normal_revision(change) for change in relevant_breaks
        )
        structure_signal = bool(
            analysis.get("structural_break_detected", {}).get("detected")
            if analysis.get("structural_break_detected")
            else False
        )

        decomposition = analysis.get("methodology_vs_real")
        methodology_share = (
            decomposition.get("methodology_share_estimate")
            if isinstance(decomposition, dict)
            else None
        )
        claim_value_check = (
            analysis.get("claim_value_check")
            if isinstance(analysis.get("claim_value_check"), dict)
            else None
        )
        low_methodology_share = (
            isinstance(methodology_share, (int, float)) and methodology_share < 0.15
        )

        if not breaks:
            if analysis.get("data_retrieved"):
                status = VerdictStatus.SUPPORTED
                comparability = ComparabilityLevel.COMPARABLE
            else:
                status = VerdictStatus.INSUFFICIENT_DATA
                comparability = ComparabilityLevel.UNCERTAIN
            severity = SeverityLevel.UNKNOWN
        else:
            if not relevant_breaks:
                status = VerdictStatus.PARTIALLY_SUPPORTED
            elif normal_revision_only and (low_methodology_share or not structure_signal):
                # False-positive guard: routine revisions without strong break signal.
                status = VerdictStatus.PARTIALLY_SUPPORTED
                severity = SeverityLevel.MINOR
                comparability = ComparabilityLevel.COMPARABLE_WITH_ADJUSTMENTS
            elif comparability == ComparabilityLevel.NOT_COMPARABLE:
                status = VerdictStatus.MISLEADING
            elif severity == SeverityLevel.MAJOR and (overlapping_breaks or structure_signal):
                status = VerdictStatus.MISLEADING
            else:
                status = VerdictStatus.PARTIALLY_SUPPORTED

        if claim_value_check and claim_value_check.get("within_tolerance") is False:
            if status == VerdictStatus.SUPPORTED:
                status = VerdictStatus.PARTIALLY_SUPPORTED
            caveat = (
                f"Claimed value deviates from retrieved series by {claim_value_check.get('absolute_delta')} "
                f"(tolerance {claim_value_check.get('tolerance')})."
            )
            # Keep this caveat high in the list.
            caveats = [caveat]
        else:
            caveats = []

        if historical_breaks:
            caveats.append(
                "Historical methodology changes exist outside the claim window and may still influence long-run trends."
            )
        if overlapping_breaks:
            caveats.append(
                "Multiple overlapping methodology breaks are present; individual effects may be difficult to separate."
            )
        if any(change.effective_date is None for change in breaks):
            caveats.append(
                "At least one break has an uncertain effective date; timeline alignment is approximate."
            )
        if analysis.get("fallback_used"):
            caveats.append(
                "Primary strategy returned sparse evidence; fallback retrieval was used."
            )
        for change in relevant_breaks[:5]:
            if change.impact_estimate:
                caveats.append(change.impact_estimate)

        summary = self._build_summary(
            claim=claim,
            status=status,
            comparability=comparability,
            relevant_breaks=relevant_breaks,
            decomposition=decomposition if isinstance(decomposition, dict) else None,
        )

        # Keep deterministic summary by default; allow LLM refinement opportunistically.
        if breaks and os.environ.get("ALETHEIA_LLM_SUMMARY", "0") == "1":
            try:
                prompt = f"""Write a concise 2-sentence policy assessment.

Claim: "{claim.original_text}"
Status: {status.value}
Comparability: {comparability.value}
Severity: {severity.value}
Methodology changes:
{chr(10).join(f"- {change.change_type.value} ({change.effective_date.isoformat() if change.effective_date else 'undated'}): {change.description}" for change in relevant_breaks[:4])}
"""
                llm_summary = await self.think(prompt, temperature=0.2, max_tokens=220)
                if llm_summary.strip():
                    summary = llm_summary.strip()
            except Exception as exc:
                self.log(f"LLM summary refinement failed: {exc}", level=30)

        # Collect and de-duplicate sources/snippets from breaks + semantic evidence.
        sources = [change.source_url for change in breaks if change.source_url]
        sources.extend(row.get("url") for row in evidence_docs if row.get("url"))
        deduped_sources = []
        seen = set()
        for source in sources:
            if source and source not in seen:
                seen.add(source)
                deduped_sources.append(source)

        evidence_snippets: list[str] = []
        for row in evidence_docs[:3]:
            title = row.get("title") or "Untitled source"
            content = (row.get("content") or "").strip()
            snippet = content[:180] + ("..." if len(content) > 180 else "")
            if snippet:
                relevance = row.get("relevance_score")
                confidence_score = row.get("confidence_score")
                if isinstance(relevance, (int, float)) and isinstance(
                    confidence_score, (int, float)
                ):
                    evidence_snippets.append(
                        (
                            f"[rel={float(relevance):.2f}, conf={float(confidence_score):.2f}] "
                            f"{title}: {snippet}"
                        )
                    )
                else:
                    evidence_snippets.append(f"{title}: {snippet}")

        confidence = 0.45
        if analysis.get("data_retrieved"):
            confidence += 0.15
        if relevant_breaks:
            confidence += 0.15
        if evidence_docs:
            confidence += 0.05
            top_doc_conf = evidence_docs[0].get("confidence_score")
            if isinstance(top_doc_conf, (int, float)):
                confidence += max(0.0, min(0.15, (float(top_doc_conf) - 0.5) * 0.3))
        if comparability == ComparabilityLevel.UNCERTAIN:
            confidence -= 0.1
        if analysis.get("fallback_used"):
            confidence -= 0.08
        aggregate_confidence = analysis.get("evidence_aggregate_confidence")
        if isinstance(aggregate_confidence, (int, float)) and aggregate_confidence > 0:
            confidence += max(
                0.0,
                min(0.08, (float(aggregate_confidence) - 0.5) * 0.2),
            )
        confidence = max(0.2, min(confidence, 0.95))

        scenarios = None
        if isinstance(decomposition, dict):
            share = decomposition.get("methodology_share_estimate")
            share_value = float(share) if isinstance(share, (int, float)) else 0.0
            scenarios = {
                "headline_series": (
                    f"Observed change: {decomposition.get('observed_change')} "
                    f"(methodology share est.: {share_value:.0%})"
                ),
                "methodology_adjusted": (
                    f"Estimated real component: {decomposition.get('real_component_estimate')}"
                ),
            }

        return Verdict(
            claim=claim,
            status=status,
            confidence=round(confidence, 3),
            severity=severity,
            comparability=comparability,
            breaks_found=breaks,
            summary=summary,
            caveats=caveats,
            sources=deduped_sources,
            evidence_snippets=evidence_snippets,
            scenarios=scenarios,
            methodology_vs_real=decomposition if isinstance(decomposition, dict) else None,
        )
