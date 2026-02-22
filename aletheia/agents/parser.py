"""Claim Parser Agent - extracts structured claims from natural language."""

import json
from typing import Optional
from aletheia.agents.base import Agent
from aletheia.schema import PolicyClaim, Direction

PARSER_SYSTEM_PROMPT = "You extract structured data from policy claims. Output only valid JSON, no explanation."


class ClaimParserAgent(Agent):
    """Extracts structured policy claims from natural language."""

    name = "Auditor"
    role = "Claim Parser"
    system_prompt = PARSER_SYSTEM_PROMPT

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_reasoning = ""

    async def parse(self, text: str) -> Optional[PolicyClaim]:
        claim, _ = await self.parse_with_reasoning(text)
        return claim

    async def parse_with_reasoning(self, text: str) -> tuple[Optional[PolicyClaim], str]:
        """Parse a natural language claim into a structured PolicyClaim."""
        prompt = f'''Extract structured data from this policy claim. Return only JSON.

Claim: "{text}"

Return JSON with these fields:
- indicator: the statistical measure (e.g., "unemployment rate", "e-cigarette use")
- dataset: source dataset code if mentioned (e.g., "CPS", "NHIS") or null
- geography: geographic scope (default "USA")
- period_start: start year/date or null
- period_end: end year/date or null
- direction: "increase", "decrease", "stable", or "unknown"
- magnitude: stated change amount or null
- confidence: your confidence 0.0-1.0

JSON:'''

        result = await self.think_with_reasoning(prompt, temperature=0.0, max_tokens=4096)
        response = result.content
        self.last_reasoning = result.reasoning

        # Extract JSON from response (handle markdown code blocks)
        json_str = self._extract_json(response)
        if not json_str:
            self.log(f"Failed to extract JSON from: {response[:100]}")
            return None, result.reasoning

        try:
            data = json.loads(json_str)
            # Map direction string to enum
            if "direction" in data and isinstance(data["direction"], str):
                data["direction"] = Direction(data["direction"])
            return PolicyClaim(original_text=text, **data), result.reasoning
        except (json.JSONDecodeError, ValueError) as e:
            self.log(f"Parse error: {e}")
            return None, result.reasoning

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON object from text, handling code blocks."""
        text = text.strip()

        # Handle markdown code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                return text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                return text[start:end].strip()

        # Find raw JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return text[start:end]

        return None
