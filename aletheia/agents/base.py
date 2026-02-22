"""Base agent class for ALETHEIA."""

import logging
from typing import Optional
from aletheia.llm import CompletionResult, LLMClient, llm
from aletheia.schema import AgentMessage


class Agent:
    """Base class for all ALETHEIA agents."""

    name: str = "Agent"
    role: str = "Generic Agent"
    system_prompt: str = "You are a helpful assistant."

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or llm
        self.logger = logging.getLogger(f"aletheia.{self.name}")

    async def think(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        ) -> str:
        """Generate a response using the LLM."""
        return await self.llm.complete(
            prompt,
            system=self.system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def think_with_reasoning(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> CompletionResult:
        """Generate response with provider reasoning/thinking when available."""
        return await self.llm.complete_with_reasoning(
            prompt,
            system=self.system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def process(self, message: AgentMessage) -> AgentMessage:
        """Process an incoming message and return a response.

        Override in subclasses for specific agent behavior.
        """
        raise NotImplementedError(f"{self.name} must implement process()")

    def log(self, msg: str, level: int = logging.INFO):
        """Log a message with agent context."""
        self.logger.log(level, f"[{self.name}] {msg}")
