"""Pydantic models for ALETHEIA's core data structures."""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


# === Enums ===

class ChangeType(str, Enum):
    """Types of methodology changes."""
    QUESTIONNAIRE_REDESIGN = "questionnaire_redesign"
    CLASSIFICATION_CHANGE = "classification_change"
    WEIGHTING_UPDATE = "weighting_update"
    COLLECTION_MODE = "collection_mode"
    DEFINITION_CHANGE = "definition_change"
    IMPUTATION_METHOD = "imputation_method"
    SAMPLE_REDESIGN = "sample_redesign"
    OTHER = "other"


class Direction(str, Enum):
    """Direction of change in an indicator."""
    INCREASE = "increase"
    DECREASE = "decrease"
    STABLE = "stable"
    UNKNOWN = "unknown"


class VerdictStatus(str, Enum):
    """Verdict on a policy claim."""
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    MISLEADING = "misleading"
    INSUFFICIENT_DATA = "insufficient_data"


class SeverityLevel(str, Enum):
    """Impact severity of a methodology change."""
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    UNKNOWN = "unknown"


class ComparabilityLevel(str, Enum):
    """How comparable the series remains across a break."""
    COMPARABLE = "comparable"
    COMPARABLE_WITH_ADJUSTMENTS = "comparable_with_adjustments"
    NOT_COMPARABLE = "not_comparable"
    UNCERTAIN = "uncertain"


# === Policy Claim (Input) ===

class PolicyClaim(BaseModel):
    """A policy claim extracted from natural language."""
    original_text: str = Field(..., description="The original claim text")
    indicator: str = Field(..., description="Statistical indicator (e.g., 'unemployment rate')")
    dataset: Optional[str] = Field(None, description="Dataset code (e.g., 'CPS', 'NHIS')")
    geography: str = Field(default="USA", description="Geographic scope")
    period_start: Optional[str | int] = Field(None, description="Start of time period")
    period_end: Optional[str | int] = Field(None, description="End of time period")
    direction: Direction = Field(default=Direction.UNKNOWN)
    magnitude: Optional[str | float] = Field(None, description="Claimed magnitude (e.g., '5%')")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# === Knowledge Graph Entities ===

class Agency(BaseModel):
    """Statistical agency."""
    id: Optional[int] = None
    code: str
    name: str
    country: Optional[str] = None
    url: Optional[str] = None


class Dataset(BaseModel):
    """Statistical dataset."""
    id: Optional[int] = None
    code: str
    name: str
    agency_id: Optional[int] = None
    description: Optional[str] = None
    frequency: Optional[str] = None


class Indicator(BaseModel):
    """Indicator within a dataset."""
    id: Optional[int] = None
    dataset_id: int
    code: str
    name: str
    unit: Optional[str] = None
    description: Optional[str] = None


class MethodologyChange(BaseModel):
    """A documented methodology change."""
    id: Optional[int] = None
    benchmark_case_id: Optional[str] = None
    dataset_id: int
    change_type: ChangeType
    effective_date: Optional[date] = None
    description: str
    impact_estimate: Optional[str] = None
    severity: Optional[SeverityLevel] = None
    comparability: Optional[ComparabilityLevel] = None
    is_documented: bool = True
    source_url: Optional[str] = None


# === Agent Communication ===

class AgentMessage(BaseModel):
    """Message passed between agents."""
    sender: str
    receiver: str
    msg_type: str  # 'request', 'response', 'error'
    payload: Any
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: Optional[str] = None


# === Verdict (Output) ===

class Verdict(BaseModel):
    """Final verdict on a policy claim."""
    claim: PolicyClaim
    status: VerdictStatus
    confidence: float = Field(ge=0.0, le=1.0)
    severity: SeverityLevel = Field(default=SeverityLevel.UNKNOWN)
    comparability: ComparabilityLevel = Field(default=ComparabilityLevel.UNCERTAIN)

    # Methodology breaks found
    breaks_found: list[MethodologyChange] = Field(default_factory=list)

    # Explanation
    summary: str
    caveats: list[str] = Field(default_factory=list)

    # Provenance
    sources: list[str] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)

    # Alternative interpretations
    scenarios: Optional[dict[str, str]] = None  # e.g., {"with_old_method": "...", "with_new_method": "..."}
    methodology_vs_real: Optional[dict[str, Any]] = None
