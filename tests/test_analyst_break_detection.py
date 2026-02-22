import pytest

from aletheia.agents.analyst import AnalystAgent
from aletheia.schema import Direction, PolicyClaim


def _claim(text: str, *, magnitude=None) -> PolicyClaim:
    return PolicyClaim(
        original_text=text,
        indicator="unemployment rate",
        dataset="CPS",
        geography="USA",
        period_start=2020,
        period_end=2020,
        direction=Direction.UNKNOWN,
        magnitude=magnitude,
    )


@pytest.mark.asyncio
async def test_detect_structural_break_detects_step_change():
    analyst = AnalystAgent()
    try:
        data = [5.0] * 12 + [8.0] * 12
        dates = [f"2019-{i:02d}" for i in range(1, 13)] + [f"2020-{i:02d}" for i in range(1, 13)]
        result = await analyst.detect_structural_break(data, dates, hint_year=2020)
        assert isinstance(result, dict)
        assert result["detected"] is True
        assert result["split_date"].startswith("2020-")
    finally:
        await analyst.close()


@pytest.mark.asyncio
async def test_detect_structural_break_ignores_small_noise_series():
    analyst = AnalystAgent()
    try:
        data = [5.0 + (0.02 if i % 2 == 0 else -0.02) for i in range(24)]
        dates = [f"2019-{i:02d}" for i in range(1, 13)] + [f"2020-{i:02d}" for i in range(1, 13)]
        result = await analyst.detect_structural_break(data, dates, hint_year=2020)
        assert isinstance(result, dict)
        assert result["detected"] is False
    finally:
        await analyst.close()


def test_check_claim_value_within_tolerance(monkeypatch):
    monkeypatch.setenv("ALETHEIA_CLAIM_VALUE_TOLERANCE", "0.5")
    analyst = AnalystAgent.__new__(AnalystAgent)
    claim = _claim("US unemployment peaked at 14.7% in April 2020")
    points = [
        {"date": "2020-04", "value": 14.8},
    ]

    result = analyst._check_claim_value(claim, points)
    assert isinstance(result, dict)
    assert result["within_tolerance"] is True


def test_check_claim_value_outside_tolerance(monkeypatch):
    monkeypatch.setenv("ALETHEIA_CLAIM_VALUE_TOLERANCE", "0.25")
    analyst = AnalystAgent.__new__(AnalystAgent)
    claim = _claim("US unemployment was 8.0% in 2020")
    points = [
        {"date": "2020-03", "value": 4.4},
        {"date": "2020-04", "value": 14.7},
        {"date": "2020-05", "value": 13.3},
    ]

    result = analyst._check_claim_value(claim, points)
    assert isinstance(result, dict)
    assert result["within_tolerance"] is False
    assert result["absolute_delta"] > 0.25


def test_extract_claimed_value_prefers_magnitude_field():
    analyst = AnalystAgent.__new__(AnalystAgent)
    claim = _claim("placeholder text", magnitude="12.4%")
    assert analyst._extract_claimed_value(claim) == 12.4


def test_extract_claimed_value_skips_year_as_number():
    """Year-like numbers (2020, 2021) should not be extracted as claimed values."""
    analyst = AnalystAgent.__new__(AnalystAgent)
    claim = _claim("EU unemployment fell sharply in 2021")
    result = analyst._extract_claimed_value(claim)
    assert result is None  # no real numeric value in text


def test_extract_claimed_value_extracts_percent_before_year():
    analyst = AnalystAgent.__new__(AnalystAgent)
    claim = _claim("Poverty increased by 3% in 2020")
    assert analyst._extract_claimed_value(claim) == 3.0


def test_extract_claimed_value_extracts_non_year_number():
    analyst = AnalystAgent.__new__(AnalystAgent)
    claim = _claim("GDP grew by 5.2 percentage points in 2021")
    assert analyst._extract_claimed_value(claim) == 5.2
