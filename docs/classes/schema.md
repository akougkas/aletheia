# Core Pydantic Schemas (AI Context)

**Target Audience**: AI coding assistants modifying input/output models or internal agent messaging structures.

## File Location
All core models are defined in `aletheia/schema.py`. Do not duplicate these definitions in other files.

## Enums
- `ChangeType`: Determines the nature of a methodology break (`questionnaire_redesign`, `classification_change`, `definition_change`, `sample_redesign`, etc.).
- `Direction`: Determines the claimed mathematical trend (`increase`, `decrease`, `stable`, `unknown`).
- `VerdictStatus`: The final editor output (`supported`, `partially_supported`, `misleading`, `insufficient_data`).
- `SeverityLevel`: (`minor`, `moderate`, `major`, `unknown`).
- `ComparabilityLevel`: Determines if the time series can be mathematically linked across the break (`comparable`, `comparable_with_adjustments`, `not_comparable`, `uncertain`).

## `PolicyClaim` (Input)
The normalized extraction of the user's natural language prompt.
```python
original_text: str
indicator: str
dataset: Optional[str]
geography: str = "USA"
period_start: Optional[Union[str, int]]
period_end: Optional[Union[str, int]]
direction: Direction = Direction.UNKNOWN
magnitude: Optional[Union[str, float]]
confidence: float = 0.5
```

## `MethodologyChange` (Internal Entity)
The database representation of a statistical break.
```python
id: Optional[int]
benchmark_case_id: Optional[str]
dataset_id: int
change_type: ChangeType
effective_date: Optional[date]
description: str
impact_estimate: Optional[str]
severity: Optional[SeverityLevel]
comparability: Optional[ComparabilityLevel]
is_documented: bool = True
source_url: Optional[str]
```

## `AgentMessage` (Internal Audit)
Used for inter-agent observability and tracing.
```python
sender: str
receiver: str
msg_type: str      # 'request', 'response', 'error'
payload: Any       # Usually JSON strings
timestamp: datetime
trace_id: Optional[str]
```

## `Verdict` (Output)
The final synthesized output presented to the user.
```python
claim: PolicyClaim
status: VerdictStatus
confidence: float
severity: SeverityLevel
comparability: ComparabilityLevel
breaks_found: list[MethodologyChange]
summary: str
caveats: list[str]
sources: list[str]
evidence_snippets: list[str]
scenarios: Optional[dict[str, str]]
methodology_vs_real: Optional[dict[str, Any]]
```