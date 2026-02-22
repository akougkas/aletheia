# Base Agent Definitions (AI Context)

**Target Audience**: AI coding assistants creating new agent roles or modifying the core agent lifecycle.

## File Location
`aletheia/agents/base.py`

## Class: `Agent`
The base class for all logical actors (`Auditor`, `Archivist`, `Analyst`, `Editor`, `OrchestratorAgent`).

**Core Attributes**:
- `name: str`: Identifier used in logs and `AgentMessage.sender` (e.g., `"ChiefAnalyst"`).
- `role: str`: Human-readable description (e.g., `"Data Retrieval & Analysis"`).
- `system_prompt: str`: Used *only* for legacy baseline LLM calls. (Note: LLM specifics are abstracted away from this documentation block, but the attribute exists).
- `logger`: Automatically instantiated standard `logging.Logger` scoped to `aletheia.{self.name}`.

**Core Methods**:
- `__init__(self, llm_client: Optional[LLMClient] = None)`: Accepts an injected LLM client; falls back to the global default.
- `async process(self, message: AgentMessage) -> AgentMessage`: Abstract method. Subclasses MUST implement this if they intend to operate in a pure message-passing architecture.
- `log(self, msg: str, level: int = logging.INFO)`: Helper method for standardized scoped logging.

**Lifecycle Note**: 
Agents are generally stateless across distinct user requests, with the exception of the `OrchestratorAgent` which maintains a `self.trace` of `AgentMessage` objects for the duration of a single `process_claim` execution.