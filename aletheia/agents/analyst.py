"""Data Analyst Agent - retrieves and analyzes statistical data."""

from __future__ import annotations

import math
import os
import re
import statistics
from datetime import datetime, timezone
from typing import Any

import httpx

from aletheia.agents.base import Agent
from aletheia.schema import MethodologyChange, PolicyClaim
from aletheia.time_utils import extract_year


BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
EUROSTAT_API_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
CENSUS_API_BASE = "https://api.census.gov/data"
ECB_API_BASE = "https://data-api.ecb.europa.eu/service/data"


class AnalystAgent(Agent):
    """Retrieves actual data and performs statistical analysis."""

    name = "Analyst"
    role = "Data Retrieval & Analysis"
    system_prompt = "You retrieve and analyze statistical data to verify claims."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.http = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self.http.aclose()

    def _normalize_dataset(self, dataset: str | None) -> str:
        if not dataset:
            return ""
        value = dataset.strip().upper().replace("_", "-")
        alias_map = {
            "EU SILC": "EU-SILC",
            "EU-LFS ": "EU-LFS",
            "ESA 2010": "ESA2010",
        }
        return alias_map.get(value, value)

    def _indicator_hint(self, claim: PolicyClaim) -> str:
        text = f"{claim.indicator} {claim.original_text}".lower()
        if "unemployment" in text:
            return "unemployment"
        if "inflation" in text or "cpi" in text or "hicp" in text:
            return "inflation"
        if "gdp" in text:
            return "gdp"
        return "generic"

    async def _fetch_bls_series(
        self, series_id: str, start_year: int, end_year: int
    ) -> list[dict[str, Any]]:
        response = await self.http.post(
            BLS_API_URL,
            json={
                "seriesid": [series_id],
                "startyear": str(start_year),
                "endyear": str(end_year),
            },
        )
        response.raise_for_status()
        payload = response.json()
        series = payload.get("Results", {}).get("series", [])
        if not series:
            return []

        points: list[dict[str, Any]] = []
        for item in series[0].get("data", []):
            period = item.get("period", "")
            if not period.startswith("M") or period == "M13":
                continue
            month = period[1:]
            date = f"{item['year']}-{month}"
            try:
                points.append({"date": date, "value": float(item["value"])})
            except (TypeError, ValueError):
                continue
        points.sort(key=lambda p: p["date"])
        return points

    async def _fetch_fred_series(
        self, series_id: str, start_date: str = "2016-01-01"
    ) -> list[dict[str, Any]]:
        api_key = os.environ.get("FRED_API_KEY")
        if not api_key:
            return []
        response = await self.http.get(
            FRED_API_URL,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "observation_start": start_date,
            },
        )
        response.raise_for_status()
        payload = response.json()
        points: list[dict[str, Any]] = []
        for obs in payload.get("observations", []):
            value = obs.get("value")
            if value in (None, ".", ""):
                continue
            try:
                points.append({"date": obs["date"], "value": float(value)})
            except (TypeError, ValueError):
                continue
        return points

    async def _fetch_acs_median_income(
        self, start_year: int, end_year: int
    ) -> list[dict[str, Any]]:
        api_key = os.environ.get("CENSUS_API_KEY")
        points: list[dict[str, Any]] = []
        for year in range(start_year, end_year + 1):
            params = {"get": "NAME,B19013_001E", "for": "us:1"}
            if api_key:
                params["key"] = api_key
            response = await self.http.get(
                f"{CENSUS_API_BASE}/{year}/acs/acs1",
                params=params,
            )
            if response.status_code != 200:
                continue
            payload = response.json()
            if not isinstance(payload, list) or len(payload) < 2:
                continue
            row = payload[1]
            try:
                value = float(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            if value <= 0:
                continue
            points.append({"date": str(year), "value": value})
        points.sort(key=lambda p: p["date"])
        return points

    async def _fetch_eurostat_series(
        self, dataset_code: str, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        response = await self.http.get(
            f"{EUROSTAT_API_BASE}/{dataset_code}",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()

        time_index = (
            payload.get("dimension", {})
            .get("time", {})
            .get("category", {})
            .get("index", {})
        )
        values = payload.get("value", {})
        if not time_index or not values:
            return []

        by_position = {int(pos): label for label, pos in time_index.items()}
        points: list[dict[str, Any]] = []
        for idx, value in values.items():
            try:
                position = int(idx)
                date = by_position.get(position)
                if date is None:
                    continue
                points.append({"date": date, "value": float(value)})
            except (TypeError, ValueError):
                continue
        points.sort(key=lambda p: p["date"])
        return points

    async def _fetch_ecb_series(
        self,
        series_path: str,
        *,
        start_period: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"format": "jsondata"}
        if start_period:
            params["startPeriod"] = start_period

        response = await self.http.get(
            f"{ECB_API_BASE}/{series_path}",
            params=params,
            headers={"Accept": "application/vnd.sdmx.data+json;version=1.0.0-wd"},
        )
        response.raise_for_status()
        payload = response.json()

        obs_dims = (
            payload.get("structure", {})
            .get("dimensions", {})
            .get("observation", [])
        )
        if not obs_dims:
            return []
        time_values = obs_dims[0].get("values", [])
        if not time_values:
            return []

        data_sets = payload.get("dataSets", [])
        if not data_sets:
            return []
        series_map = data_sets[0].get("series", {})
        if not series_map:
            return []

        # For fixed-key series requests there is usually one series.
        first_series = next(iter(series_map.values()))
        observations = first_series.get("observations", {})

        points: list[dict[str, Any]] = []
        for index_key, obs_value in observations.items():
            try:
                obs_idx = int(str(index_key).split(":")[0])
                label = time_values[obs_idx]["id"]
                value = float(obs_value[0])
                points.append({"date": label, "value": value})
            except (TypeError, ValueError, KeyError, IndexError):
                continue

        points.sort(key=lambda p: p["date"])
        return points

    async def fetch_data(self, claim: PolicyClaim) -> dict[str, Any]:
        """Fetch relevant data for a claim from statistical APIs."""
        self.log(f"Fetching data for indicator: {claim.indicator}")
        dataset = self._normalize_dataset(claim.dataset)
        hint = self._indicator_hint(claim)
        start_year = max(1995, (extract_year(claim.period_start) or 2016) - 3)
        current_year = datetime.now(timezone.utc).year
        end_year = min(current_year, (extract_year(claim.period_end) or current_year))

        try:
            if dataset in {"CPS", "CPI", "BLS"} or (not dataset and hint in {"unemployment", "inflation"}):
                series_id = "LNS14000000" if hint == "unemployment" else "CUUR0000SA0"
                points = await self._fetch_bls_series(series_id, start_year, end_year)
                return {
                    "source": "BLS",
                    "series_id": series_id,
                    "dataset": dataset or "BLS",
                    "indicator": claim.indicator,
                    "points": points,
                    "data_available": len(points) > 0,
                    "note": "BLS public API",
                }

            if dataset == "ACS":
                points = await self._fetch_acs_median_income(start_year, end_year)
                return {
                    "source": "CENSUS",
                    "series_id": "ACS1_B19013_001E_US",
                    "dataset": dataset,
                    "indicator": claim.indicator,
                    "points": points,
                    "data_available": len(points) > 0,
                    "note": "Census ACS API",
                }

            if dataset in {"EU-LFS", "HICP"}:
                if dataset == "EU-LFS":
                    points = await self._fetch_eurostat_series(
                        "une_rt_m",
                        {
                            "geo": "EU27_2020",
                            "sex": "T",
                            "age": "Y15-74",
                            "unit": "PC_ACT",
                            "s_adj": "SA",
                        },
                    )
                else:
                    points = await self._fetch_eurostat_series(
                        "prc_hicp_midx",
                        {
                            "geo": "EA20",
                            "coicop": "CP00",
                            "unit": "I15",
                            "freq": "M",
                        },
                    )
                return {
                    "source": "EUROSTAT",
                    "dataset": dataset,
                    "indicator": claim.indicator,
                    "points": points,
                    "data_available": len(points) > 0,
                    "note": "Eurostat dissemination API",
                }

            if dataset == "EU-SILC":
                points = await self._fetch_eurostat_series(
                    "ilc_li02",
                    {
                        "geo": "IE",
                        "unit": "PC",
                        "indic_il": "LI_R_MD60",
                        "sex": "T",
                        "age": "TOTAL",
                        "freq": "A",
                    },
                )
                return {
                    "source": "EUROSTAT",
                    "series_id": "ilc_li02:LI_R_MD60:IE",
                    "dataset": dataset,
                    "indicator": claim.indicator,
                    "points": points,
                    "data_available": len(points) > 0,
                    "note": "Eurostat EU-SILC API",
                }

            if dataset in {"ECB", "ESA2010"}:
                gdp_series = os.environ.get(
                    "ALETHEIA_ECB_GDP_SERIES",
                    "MNA/Q.Y.I9.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY",
                )
                inflation_series = os.environ.get(
                    "ALETHEIA_ECB_INFLATION_SERIES",
                    "ICP/M.U2.N.000000.4.ANR",
                )
                fallback_series = os.environ.get(
                    "ALETHEIA_ECB_DEFAULT_SERIES",
                    "EXR/D.USD.EUR.SP00.A",
                )
                series_path = (
                    gdp_series
                    if hint == "gdp"
                    else inflation_series if hint == "inflation" else fallback_series
                )
                points = await self._fetch_ecb_series(
                    series_path,
                    start_period=f"{start_year}-01-01",
                )
                if points:
                    return {
                        "source": "ECB",
                        "series_id": series_path,
                        "dataset": dataset,
                        "indicator": claim.indicator,
                        "points": points,
                        "data_available": True,
                        "note": "ECB SDMX API",
                    }

            if dataset in {"FRED", "ESA2010"} or hint == "gdp":
                fred_series = "GDP" if hint == "gdp" else "UNRATE"
                points = await self._fetch_fred_series(fred_series)
                return {
                    "source": "FRED",
                    "series_id": fred_series,
                    "dataset": dataset or "FRED",
                    "indicator": claim.indicator,
                    "points": points,
                    "data_available": len(points) > 0,
                    "note": "FRED API (requires FRED_API_KEY)",
                }

            return {
                "source": dataset or "unknown",
                "indicator": claim.indicator,
                "points": [],
                "data_available": False,
                "note": "No configured connector for this dataset yet",
            }
        except Exception as exc:  # noqa: BLE001
            self.log(f"Data retrieval failed: {exc}")
            return {
                "source": dataset or "unknown",
                "indicator": claim.indicator,
                "points": [],
                "data_available": False,
                "note": f"Data retrieval error: {exc}",
            }

    def _choose_break_index(
        self,
        values: list[float],
        dates: list[str],
        hint_year: int | None = None,
    ) -> int | None:
        if len(values) < 8:
            return None

        if hint_year is not None:
            for idx, label in enumerate(dates):
                year = extract_year(label)
                if year is not None and year >= hint_year and 3 <= idx <= len(values) - 4:
                    return idx

        best_idx = None
        best_gap = -1.0
        window = max(3, min(12, len(values) // 4))
        for idx in range(window, len(values) - window):
            left = values[idx - window:idx]
            right = values[idx:idx + window]
            gap = abs(statistics.mean(right) - statistics.mean(left))
            if gap > best_gap:
                best_gap = gap
                best_idx = idx
        return best_idx

    async def detect_structural_break(
        self,
        data: list[float],
        dates: list[str],
        *,
        hint_year: int | None = None,
    ) -> dict[str, Any] | None:
        """Run lightweight break diagnostics (mean-shift + CUSUM-style score)."""
        split_idx = self._choose_break_index(data, dates, hint_year=hint_year)
        if split_idx is None:
            return None

        pre = data[:split_idx]
        post = data[split_idx:]
        if len(pre) < 3 or len(post) < 3:
            return None

        mean_pre = statistics.mean(pre)
        mean_post = statistics.mean(post)
        mean_shift = mean_post - mean_pre

        var_pre = statistics.variance(pre) if len(pre) > 1 else 0.0
        var_post = statistics.variance(post) if len(post) > 1 else 0.0
        dof = max(1, (len(pre) - 1) + (len(post) - 1))
        pooled_var = (((len(pre) - 1) * var_pre) + ((len(post) - 1) * var_post)) / dof
        pooled_std = math.sqrt(max(pooled_var, 1e-9))
        effect_size = mean_shift / pooled_std if pooled_std > 0 else 0.0

        # CUSUM-style score around the split.
        baseline = statistics.mean(data)
        residuals = [value - baseline for value in data]
        cumulative = []
        running = 0.0
        for residual in residuals:
            running += residual
            cumulative.append(running)
        cusum_range = max(cumulative) - min(cumulative)
        cusum_score = cusum_range / (pooled_std * math.sqrt(len(data)))

        detected = abs(effect_size) >= 0.8 or cusum_score >= 1.2
        confidence = min(0.95, 0.35 + (min(abs(effect_size), 2.5) / 5.0) + min(cusum_score, 2.0) / 5.0)

        return {
            "detected": detected,
            "split_index": split_idx,
            "split_date": dates[split_idx],
            "mean_pre": round(mean_pre, 4),
            "mean_post": round(mean_post, 4),
            "mean_shift": round(mean_shift, 4),
            "effect_size": round(effect_size, 4),
            "cusum_score": round(cusum_score, 4),
            "confidence": round(confidence, 4),
        }

    def _value_for_year(self, points: list[dict[str, Any]], year: int) -> float | None:
        year_values = [p["value"] for p in points if extract_year(p["date"]) == year]
        if year_values:
            return float(statistics.mean(year_values))
        return None

    def _observed_change(self, claim: PolicyClaim, points: list[dict[str, Any]]) -> float | None:
        if len(points) < 2:
            return None
        start_year = extract_year(claim.period_start)
        end_year = extract_year(claim.period_end) or start_year

        if start_year is not None and end_year is not None:
            start_value = self._value_for_year(points, start_year)
            end_value = self._value_for_year(points, end_year)
            if start_value is not None and end_value is not None:
                return end_value - start_value

        return points[-1]["value"] - points[0]["value"]

    def _estimate_numeric_impact(self, impact_estimate: str | None) -> float | None:
        if not impact_estimate:
            return None
        range_match = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)", impact_estimate
        )
        if range_match:
            low = float(range_match.group(1))
            high = float(range_match.group(2))
            return (low + high) / 2.0

        numbers = re.findall(r"(\d+(?:\.\d+)?)", impact_estimate)
        if not numbers:
            return None
        return float(numbers[0])

    def quantify_methodology_vs_reality(
        self,
        claim: PolicyClaim,
        breaks: list[MethodologyChange],
        analysis: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Estimate how much of observed change may be methodological."""
        observed_change = analysis.get("observed_change")
        if observed_change is None:
            return None

        period_year = extract_year(claim.period_end) or extract_year(claim.period_start)
        impact_values: list[float] = []
        overlapping_breaks = 0
        for change in breaks:
            change_year = extract_year(change.effective_date)
            if period_year is not None and change_year is not None and abs(change_year - period_year) <= 1:
                overlapping_breaks += 1
            impact_value = self._estimate_numeric_impact(change.impact_estimate)
            if impact_value is not None:
                impact_values.append(impact_value)

        if not impact_values:
            return None

        # Sum nearby effects to reflect compounding when breaks overlap.
        methodology_component = sum(impact_values[:2]) if overlapping_breaks > 1 else impact_values[0]
        observed_abs = abs(observed_change)
        if observed_abs <= 1e-9:
            share = 0.0
            real_component = 0.0
        else:
            share = min(1.0, methodology_component / observed_abs)
            sign = 1.0 if observed_change >= 0 else -1.0
            real_component = observed_change - (methodology_component * sign)

        return {
            "observed_change": round(observed_change, 4),
            "methodology_component_estimate": round(methodology_component, 4),
            "real_component_estimate": round(real_component, 4),
            "methodology_share_estimate": round(share, 4),
            "overlapping_breaks": overlapping_breaks,
        }

    async def analyze(self, claim: PolicyClaim) -> dict[str, Any]:
        """Full analysis pipeline for a claim."""
        data = await self.fetch_data(claim)
        points = data.get("points", []) or []
        values = [point["value"] for point in points]
        dates = [point["date"] for point in points]

        break_result = None
        observed_change = None
        if points:
            break_result = await self.detect_structural_break(
                values,
                dates,
                hint_year=extract_year(claim.period_end) or extract_year(claim.period_start),
            )
            observed_change = self._observed_change(claim, points)

        return {
            "data_retrieved": bool(data.get("data_available")),
            "structural_break_detected": break_result,
            "observed_change": observed_change,
            "raw_data": data,
            "analysis_note": "Data retrieved from live APIs where connectors are available.",
        }
