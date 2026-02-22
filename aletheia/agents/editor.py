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

    # --- Recall policy constants ---
    RECALL_MIN_MATCHES = 2
    RECALL_MIN_CONSENSUS = 0.5
    RECALL_MAX_DELTA = 0.08
    RECALL_TIEBREAK_MIN_MATCHES = 3
    RECALL_TIEBREAK_MIN_CONSENSUS = 0.8

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

    def _compute_recall_adjustment(
        self,
        recall: dict | None,
        current_status: VerdictStatus,
        current_breaks: list[MethodologyChange],
    ) -> dict[str, Any]:
        """Compute deterministic recall-based confidence adjustment.

        Returns dict with recall_delta, recall_reason, recall_metrics.
        Hard cap: abs(delta) <= 0.08.
        """
        NO_EFFECT: dict[str, Any] = {
            "recall_delta": 0.0,
            "recall_reason": "no_recall_data",
            "recall_metrics": {},
        }

        if not recall or not isinstance(recall, dict):
            return NO_EFFECT

        matches = recall.get("matches")
        if not matches or not isinstance(matches, list):
            return NO_EFFECT

        recall_match_count = len(matches)

        # Status distribution across prior verdicts.
        status_counts: dict[str, int] = {}
        for m in matches:
            verdict = m.get("verdict") or {}
            v_status = verdict.get("status")
            if v_status and isinstance(v_status, str):
                status_counts[v_status] = status_counts.get(v_status, 0) + 1

        # Consensus strength: majority fraction.
        total_with_status = sum(status_counts.values())
        if total_with_status > 0:
            majority_count = max(status_counts.values())
            recall_consensus_strength = majority_count / total_with_status
            majority_status = max(status_counts, key=lambda k: status_counts[k])
        else:
            recall_consensus_strength = 0.0
            majority_status = None

        # Change overlap ratio — prefer benchmark_case_id, fall back to (change_type, year).
        current_case_ids: set[str] = set()
        current_keys: set[tuple[str, int | None]] = set()
        for b in current_breaks:
            if b.benchmark_case_id:
                current_case_ids.add(b.benchmark_case_id)
            year = b.effective_date.year if b.effective_date else None
            current_keys.add((b.change_type.value, year))

        recall_case_ids: set[str] = set()
        recall_keys: set[tuple[str, int | None]] = set()
        for m in matches:
            for mc in m.get("methodology_changes") or []:
                bcid = mc.get("benchmark_case_id")
                if bcid and isinstance(bcid, str):
                    recall_case_ids.add(bcid)
                ct = mc.get("change_type")
                ed = mc.get("effective_date")
                year = None
                if isinstance(ed, str) and len(ed) >= 4:
                    try:
                        year = int(ed[:4])
                    except (ValueError, TypeError):
                        pass
                if ct:
                    recall_keys.add((str(ct), year))

        # Use benchmark_case_id Jaccard when both sides have IDs.
        if current_case_ids and recall_case_ids:
            union = len(current_case_ids | recall_case_ids)
            recall_change_overlap_ratio = (
                len(current_case_ids & recall_case_ids) / union if union > 0 else 0.0
            )
        elif current_keys and recall_keys:
            union = len(current_keys | recall_keys)
            recall_change_overlap_ratio = (
                len(current_keys & recall_keys) / union if union > 0 else 0.0
            )
        else:
            recall_change_overlap_ratio = 0.0

        # Weighted confidence mean from prior verdicts.
        conf_values: list[float] = []
        for m in matches:
            v = m.get("verdict") or {}
            conf = v.get("confidence")
            agg = m.get("aggregate_confidence")
            c = (
                conf
                if isinstance(conf, (int, float))
                else (agg if isinstance(agg, (int, float)) else None)
            )
            if c is not None:
                conf_values.append(float(c))

        recall_weighted_confidence_mean = (
            sum(conf_values) / len(conf_values) if conf_values else 0.0
        )

        metrics = {
            "recall_match_count": recall_match_count,
            "recall_status_distribution": dict(status_counts),
            "recall_consensus_strength": round(recall_consensus_strength, 3),
            "recall_change_overlap_ratio": round(recall_change_overlap_ratio, 3),
            "recall_weighted_confidence_mean": round(recall_weighted_confidence_mean, 3),
            "recall_majority_status": majority_status,
        }

        # Gate: need minimum matches with minimum consensus.
        if (
            recall_match_count < self.RECALL_MIN_MATCHES
            or recall_consensus_strength < self.RECALL_MIN_CONSENSUS
        ):
            return {
                "recall_delta": 0.0,
                "recall_reason": "insufficient_recall",
                "recall_metrics": metrics,
            }

        # Alignment check.
        aligned = majority_status == current_status.value

        # Bounded delta: scale by match density, consensus, prior confidence.
        count_factor = min(recall_match_count, 5) / 5
        raw_magnitude = (
            count_factor
            * recall_consensus_strength
            * max(recall_weighted_confidence_mean, 0.3)
            * self.RECALL_MAX_DELTA
        )

        CAP = self.RECALL_MAX_DELTA
        if aligned:
            delta = min(raw_magnitude, CAP)
            reason = "aligned_recall"
        else:
            delta = -min(raw_magnitude, CAP)
            reason = "conflicting_recall"

        return {
            "recall_delta": round(delta, 4),
            "recall_reason": reason,
            "recall_metrics": metrics,
        }

    def _apply_recall_tiebreak(
        self,
        status: VerdictStatus,
        recall_adj: dict[str, Any],
        structure_signal: bool,
        relevant_breaks: list[MethodologyChange],
        severity: SeverityLevel,
    ) -> tuple[VerdictStatus, str | None]:
        """Attempt recall-based status tie-break for PARTIALLY_SUPPORTED verdicts.

        Strict gates:
        - Only PARTIALLY_SUPPORTED status is eligible.
        - Requires RECALL_TIEBREAK_MIN_MATCHES and RECALL_TIEBREAK_MIN_CONSENSUS.
        - Must not conflict with structural signal.

        Returns (new_status, caveat_text) or (status, None) if no tie-break.
        """
        if status != VerdictStatus.PARTIALLY_SUPPORTED:
            return status, None

        metrics = recall_adj.get("recall_metrics") or {}
        match_count = metrics.get("recall_match_count", 0)
        consensus = metrics.get("recall_consensus_strength", 0.0)
        majority = metrics.get("recall_majority_status")

        if match_count < self.RECALL_TIEBREAK_MIN_MATCHES:
            return status, None
        if consensus < self.RECALL_TIEBREAK_MIN_CONSENSUS:
            return status, None
        if majority is None or majority == VerdictStatus.PARTIALLY_SUPPORTED.value:
            return status, None

        if majority == VerdictStatus.SUPPORTED.value:
            # Block if structural signal detected a break.
            if structure_signal:
                return status, None
            # Block if relevant breaks with MODERATE+ severity exist.
            if relevant_breaks and self._severity_rank.get(severity, 0) >= 2:
                return status, None
            return VerdictStatus.SUPPORTED, (
                f"Status adjusted to supported based on {match_count} prior verification(s) "
                f"with {consensus:.0%} consensus; no conflicting structural signal."
            )

        if majority == VerdictStatus.MISLEADING.value:
            # Require corroboration: structure_signal OR severity >= MAJOR.
            if not structure_signal and self._severity_rank.get(severity, 0) < 3:
                return status, None
            return VerdictStatus.MISLEADING, (
                f"Status adjusted to misleading based on {match_count} prior verification(s) "
                f"with {consensus:.0%} consensus; structural signal does not contradict."
            )

        return status, None

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
        break_detection = analysis.get("structural_break_detected")
        structure_signal = bool(
            break_detection.get("detected") if isinstance(break_detection, dict) else False
        )
        # Extract Chow test strength for verdict weighting.
        math_confidence = 0.0
        if isinstance(break_detection, dict) and break_detection.get("detected"):
            math_confidence = float(break_detection.get("confidence", 0.0))

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
                # Math-aware: strong Chow signal with no KB breaks → possible undocumented break.
                if structure_signal and math_confidence >= 0.8:
                    status = VerdictStatus.PARTIALLY_SUPPORTED
                    comparability = ComparabilityLevel.UNCERTAIN
                else:
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
            
        if isinstance(break_detection, dict) and break_detection.get("detected"):
            test_type = break_detection.get("test_type", "Chow test").replace("_", " ")
            p_val = break_detection.get("p_value", "N/A")
            split_date = break_detection.get("split_date", "unknown date")
            if relevant_breaks:
                caveats.append(
                    f"A {test_type} confirmed a significant structural break near {split_date} "
                    f"(p={p_val}), supporting the documented methodology changes."
                )
            else:
                caveats.append(
                    f"A {test_type} detected a significant structural break near {split_date} "
                    f"(p={p_val}), indicating a possible undocumented methodology change."
                )

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
        seen_titles: set[str] = set()
        for row in evidence_docs[:6]:
            title = row.get("title") or "Untitled source"
            # Deduplicate by title — same-source evidence appears once.
            title_key = title.lower().strip()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            content = (row.get("content") or "").strip()
            # Strip repeated title prefix that leaks from stored evidence.
            title_prefix = title.strip()
            while content.startswith(title_prefix):
                content = content[len(title_prefix):].lstrip(": ")
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
            if len(evidence_snippets) >= 3:
                break

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
        # Chow test confidence contribution: strong math signal boosts verdict confidence,
        # conflicting signals (math break + no KB breaks, or no math break + KB major) penalize.
        if structure_signal and math_confidence > 0:
            if relevant_breaks:
                # Math corroborates KB breaks — boost proportional to test strength.
                confidence += min(0.12, math_confidence * 0.15)
            else:
                # Math detected break but no KB documentation — uncertain but informative.
                confidence += min(0.05, math_confidence * 0.06)
        elif not structure_signal and relevant_breaks and severity == SeverityLevel.MAJOR:
            # KB says major break but math found nothing — conflicting, lower confidence.
            confidence -= 0.06
        confidence = max(0.2, min(confidence, 0.95))

        # --- Recall-aware confidence adjustment ---
        recall_adj = self._compute_recall_adjustment(
            analysis.get("prior_verification_recall"), status, relevant_breaks,
        )
        recall_delta = recall_adj["recall_delta"]
        if recall_delta != 0.0:
            confidence += recall_delta
            confidence = max(0.2, min(confidence, 0.95))

        if recall_adj["recall_reason"] == "aligned_recall":
            rm = recall_adj["recall_metrics"]
            caveats.append(
                f"Consistent with {rm['recall_match_count']} prior similar verification(s) "
                f"(majority verdict: {rm['recall_majority_status']})."
            )
        elif recall_adj["recall_reason"] == "conflicting_recall":
            rm = recall_adj["recall_metrics"]
            caveats.append(
                f"Conflicts with {rm['recall_match_count']} prior similar verification(s) "
                f"(majority verdict: {rm['recall_majority_status']}); confidence reduced."
            )

        # --- Recall-based borderline tie-break ---
        tiebreak_status, tiebreak_caveat = self._apply_recall_tiebreak(
            status, recall_adj, structure_signal, relevant_breaks, severity,
        )
        if tiebreak_status != status:
            status = tiebreak_status
            recall_adj["recall_tiebreak"] = tiebreak_caveat
            caveats.append(tiebreak_caveat)
            # Rebuild summary for new status.
            summary = self._build_summary(
                claim=claim,
                status=status,
                comparability=comparability,
                relevant_breaks=relevant_breaks,
                decomposition=decomposition if isinstance(decomposition, dict) else None,
            )

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
            recall_adjustment=recall_adj,
        )
