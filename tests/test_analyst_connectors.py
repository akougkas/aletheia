import pytest

from aletheia.agents.analyst import AnalystAgent
from aletheia.schema import Direction, PolicyClaim


def _claim(dataset: str, indicator: str = "test indicator") -> PolicyClaim:
    return PolicyClaim(
        original_text=f"{dataset} claim",
        indicator=indicator,
        dataset=dataset,
        geography="USA",
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
