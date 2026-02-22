import pytest

from aletheia.agents.analyst import AnalystAgent
from aletheia.schema import Direction, PolicyClaim


def _claim(
    dataset: str,
    indicator: str = "test indicator",
    geography: str = "USA",
    original_text: str | None = None,
) -> PolicyClaim:
    return PolicyClaim(
        original_text=original_text or f"{dataset} claim",
        indicator=indicator,
        dataset=dataset,
        geography=geography,
        period_start=2020,
        period_end=2023,
        direction=Direction.UNKNOWN,
    )


@pytest.mark.asyncio
async def test_analyst_routes_to_acs_connector(monkeypatch):
    analyst = AnalystAgent()

    async def _fake_acs(start_year, end_year):
        return [{"date": "2022", "value": 70000.0}]

    monkeypatch.setattr(analyst, "_fetch_acs_median_income", _fake_acs)
    result = await analyst.fetch_data(_claim("ACS"))
    assert result["source"] == "CENSUS"
    assert result["data_available"] is True

    await analyst.close()


@pytest.mark.asyncio
async def test_analyst_routes_to_eu_silc_connector(monkeypatch):
    analyst = AnalystAgent()

    async def _fake_eurostat(dataset_code, params):
        assert dataset_code == "ilc_li02"
        return [{"date": "2022", "value": 21.0}]

    monkeypatch.setattr(analyst, "_fetch_eurostat_series", _fake_eurostat)
    result = await analyst.fetch_data(_claim("EU-SILC", "at risk of poverty"))
    assert result["source"] == "EUROSTAT"
    assert result["data_available"] is True

    await analyst.close()


@pytest.mark.asyncio
async def test_analyst_routes_to_ecb_connector(monkeypatch):
    analyst = AnalystAgent()

    async def _fake_ecb(series_path, start_period=None):
        return [{"date": "2023-Q1", "value": 0.5}]

    monkeypatch.setattr(analyst, "_fetch_ecb_series", _fake_ecb)
    result = await analyst.fetch_data(_claim("ECB", "gdp growth"))
    assert result["source"] == "ECB"
    assert result["data_available"] is True

    await analyst.close()


@pytest.mark.asyncio
async def test_us_poverty_routes_to_acs(monkeypatch):
    """Bug #1: US poverty claim with no dataset must route to ACS."""
    analyst = AnalystAgent()

    async def _fake_acs(start_year, end_year):
        return [{"date": "2022", "value": 12.4}]

    monkeypatch.setattr(analyst, "_fetch_acs_median_income", _fake_acs)
    claim = _claim("", "poverty rate", geography="USA",
                    original_text="The US poverty rate increased by 3% in 2020")
    result = await analyst.fetch_data(claim)
    assert result["source"] == "CENSUS"
    assert result["data_available"] is True

    await analyst.close()


@pytest.mark.asyncio
async def test_eu_poverty_routes_to_eu_silc(monkeypatch):
    """Bug #2: EU poverty claim with no dataset must infer EU-SILC."""
    analyst = AnalystAgent()

    async def _fake_eurostat(dataset_code, params):
        assert dataset_code == "ilc_li02"
        return [{"date": "2022", "value": 21.0}]

    monkeypatch.setattr(analyst, "_fetch_eurostat_series", _fake_eurostat)
    claim = _claim("", "at risk of poverty", geography="Euro Area",
                    original_text="EU poverty rose in 2022")
    result = await analyst.fetch_data(claim)
    assert result["source"] == "EUROSTAT"
    assert result["dataset"] == "EU-SILC"

    await analyst.close()


@pytest.mark.asyncio
async def test_mortality_returns_no_connector():
    """Bug #3: Mortality claim must get explicit no-connector, not fall through."""
    analyst = AnalystAgent()
    claim = _claim("", "mortality rate", geography="USA",
                    original_text="US mortality increased in 2020")
    result = await analyst.fetch_data(claim)
    assert result["data_available"] is False
    assert "mortality" in result["note"]

    await analyst.close()


@pytest.mark.asyncio
async def test_health_returns_no_connector():
    """Bug #4: Health/NHIS claim must get explicit no-connector."""
    analyst = AnalystAgent()
    claim = _claim("", "health insurance coverage", geography="USA",
                    original_text="NHIS coverage declined in 2019")
    result = await analyst.fetch_data(claim)
    assert result["data_available"] is False
    assert "health" in result["note"]

    await analyst.close()


@pytest.mark.asyncio
async def test_non_us_unemployment_skips_bls(monkeypatch):
    """Bug #8: Non-US unemployment with no dataset must not hit BLS."""
    analyst = AnalystAgent()
    routed_to: list[str] = []

    async def _fake_bls(series_id, start_year, end_year):
        routed_to.append("BLS")
        return []

    monkeypatch.setattr(analyst, "_fetch_bls_series", _fake_bls)
    claim = _claim("", "unemployment rate", geography="Germany",
                    original_text="German unemployment fell in 2023")
    result = await analyst.fetch_data(claim)
    assert result["source"] != "BLS"
    assert "BLS" not in routed_to

    await analyst.close()


@pytest.mark.asyncio
async def test_eu_gdp_without_dataset_routes_to_ecb(monkeypatch):
    """Bug #7: EU GDP with no dataset must go to ECB, not FRED."""
    analyst = AnalystAgent()

    async def _fake_ecb(series_path, start_period=None):
        return [{"date": "2023-Q1", "value": 1.2}]

    monkeypatch.setattr(analyst, "_fetch_ecb_series", _fake_ecb)
    claim = _claim("", "gdp growth", geography="Euro Area",
                    original_text="EU GDP grew in 2023")
    result = await analyst.fetch_data(claim)
    assert result["source"] == "ECB"
    assert result["data_available"] is True

    await analyst.close()
