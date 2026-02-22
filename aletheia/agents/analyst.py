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
            "EU-LFS": "EU-LFS",
            "ESA 2010": "ESA2010",
            "EURO AREA": "ECB",
            "EUROZONE": "ECB",
            "EA": "ECB",
        }
        return alias_map.get(value, value)

    def _indicator_hint(self, claim: PolicyClaim) -> str:
        text = f"{claim.indicator} {claim.original_text}".lower()
        if "unemployment" in text or "employment" in text:
            return "unemployment"
        if "inflation" in text or "cpi" in text or "hicp" in text:
            return "inflation"
        if "gdp" in text:
            return "gdp"
        if "poverty" in text or "at risk of poverty" in text:
            return "poverty"
        if "income" in text or "median income" in text:
            return "income"
        if "mortality" in text or "death" in text or "life expectancy" in text:
            return "mortality"
        if "health" in text or "nhis" in text or "insurance" in text:
            return "health"
        return "generic"

    def _is_eu_context(self, claim: PolicyClaim) -> bool:
        """Detect if the claim is about EU/Euro area data."""
        text = f"{claim.geography or ''} {claim.original_text}".lower()
        eu_markers = {"euro area", "eurozone", "eu ", "eu-", "european union", "eurostat"}
        return any(m in text for m in eu_markers)

    def _is_us_context(self, claim: PolicyClaim) -> bool:
        """Detect if the claim is about US data."""
        geo = (claim.geography or "").lower()
        if geo in {"usa", "us", "united states"}:
            return True
        text = f"{claim.geography or ''} {claim.original_text}".lower()
        us_markers = {"usa", "united states", "u.s.", "american"}
        return any(m in text for m in us_markers)

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

        # Infer EU dataset from geography when parser leaves dataset empty.
        if not dataset and self._is_eu_context(claim):
            if hint == "unemployment":
                dataset = "EU-LFS"
            elif hint == "inflation":
                dataset = "HICP"
            elif hint == "gdp":
                dataset = "ECB"
            elif hint == "poverty":
                dataset = "EU-SILC"

        try:
            if dataset in {"CPS", "CPI", "BLS"} or (not dataset and hint in {"unemployment", "inflation"} and self._is_us_context(claim)):
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

            if not dataset and hint in {"poverty", "income"} and self._is_us_context(claim):
                points = await self._fetch_acs_median_income(start_year, end_year)
                return {
                    "source": "CENSUS",
                    "series_id": "ACS1_B19013_001E_US",
                    "dataset": "ACS",
                    "indicator": claim.indicator,
                    "points": points,
                    "data_available": len(points) > 0,
                    "note": "Census ACS API (inferred from indicator)",
                }

            if not dataset and hint in {"mortality", "health"}:
                return {
                    "source": "unknown",
                    "indicator": claim.indicator,
                    "points": [],
                    "data_available": False,
                    "note": f"No connector for {hint} data yet",
                }

            # Route generic "EU" dataset based on indicator hint.
            if dataset == "EU":
                if hint == "unemployment":
                    dataset = "EU-LFS"
                elif hint == "inflation":
                    dataset = "HICP"
                elif hint == "gdp":
                    dataset = "ECB"
                elif hint == "poverty":
                    dataset = "EU-SILC"

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
                return {
                    "source": "ECB",
                    "series_id": series_path,
                    "dataset": dataset,
                    "indicator": claim.indicator,
                    "points": points,
                    "data_available": len(points) > 0,
                    "note": "ECB SDMX API",
                }

            if dataset == "FRED" or (hint == "gdp" and self._is_us_context(claim)):
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
        """Run rigorous econometric break detection (Chow test on linear trend)."""
        try:
            import numpy as np
            from scipy import stats
        except ImportError:
            self.log("Break detection requires math dependencies. Run: uv sync --extra math", level=30)
            return None

        split_idx = self._choose_break_index(data, dates, hint_year=hint_year)
        if split_idx is None:
            return None

        y = np.array(data)
        x = np.arange(len(y))

        pre_y = y[:split_idx]
        pre_x = x[:split_idx]
        post_y = y[split_idx:]
        post_x = x[split_idx:]

        if len(pre_y) < 3 or len(post_y) < 3:
            return None

        def _rss(x_vals, y_vals):
            if len(x_vals) <= 2:
                return 0.0
            A = np.vstack([x_vals, np.ones(len(x_vals))]).T
            coeffs, residuals, _, _ = np.linalg.lstsq(A, y_vals, rcond=None)
            if residuals.size > 0:
                return float(residuals[0])
            preds = A.dot(coeffs)
            return float(np.sum((y_vals - preds) ** 2))

        rss_c = _rss(x, y)
        rss_1 = _rss(pre_x, pre_y)
        rss_2 = _rss(post_x, post_y)

        # Chow test for linear trend (k=2: slope + intercept)
        k = 2
        N = len(y)
        df1 = k
        df2 = N - 2 * k

        if df2 <= 0:
            return None

        rss_sum = rss_1 + rss_2
        if rss_sum <= 1e-12:
            if rss_c > 1e-12:
                # Perfect break (no variance within segments but variance across)
                chow_f = 9999.0
                p_value = 0.0
            else:
                return None
        else:
            chow_f = ((rss_c - rss_sum) / df1) / (rss_sum / df2)
            p_value = 1.0 - stats.f.cdf(chow_f, df1, df2)

        mean_pre = float(np.mean(pre_y))
        mean_post = float(np.mean(post_y))
        mean_shift = mean_post - mean_pre

        pooled_std = float(np.std(y))
        effect_size = mean_shift / pooled_std if pooled_std > 0 else 0.0

        confidence = 0.95 if p_value < 0.01 else (0.8 if p_value < 0.05 else (0.5 if p_value < 0.1 else 0.3))
        detected = bool(p_value < 0.05)

        return {
            "detected": detected,
            "split_index": split_idx,
            "split_date": dates[split_idx],
            "test_type": "chow_test_linear_trend",
            "f_statistic": float(round(chow_f, 4)),
            "p_value": float(round(p_value, 4)),
            "mean_pre": round(mean_pre, 4),
            "mean_post": round(mean_post, 4),
            "mean_shift": round(mean_shift, 4),
            "effect_size": round(effect_size, 4),
            "confidence": confidence,
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

    def _extract_claimed_value(self, claim: PolicyClaim) -> float | None:
        """Extract a scalar claimed value from magnitude/text when available."""
        if isinstance(claim.magnitude, (int, float)):
            return float(claim.magnitude)
        if isinstance(claim.magnitude, str):
            match = re.search(r"-?\d+(?:\.\d+)?", claim.magnitude)
            if match:
                return float(match.group(0))

        text = claim.original_text
        percent_match = re.search(r"(-?\d+(?:\.\d+)?)\s*%", text)
        if percent_match:
            return float(percent_match.group(1))

        number_match = re.search(r"\b(-?\d+(?:\.\d+)?)\b", text)
        if number_match:
            return float(number_match.group(1))
        return None

    def _target_value_from_points(
        self,
        claim: PolicyClaim,
        points: list[dict[str, Any]],
    ) -> tuple[float, str] | None:
        if not points:
            return None

        target_year = extract_year(claim.period_end) or extract_year(claim.period_start)
        if target_year is None:
            last = points[-1]
            return float(last["value"]), str(last["date"])

        in_year = [p for p in points if extract_year(p.get("date")) == target_year]
        if in_year:
            avg_value = float(statistics.mean(float(p["value"]) for p in in_year))
            return avg_value, str(in_year[-1]["date"])

        nearest = min(
            points,
            key=lambda p: abs((extract_year(p.get("date")) or target_year) - target_year),
        )
        return float(nearest["value"]), str(nearest["date"])

    def _check_claim_value(
        self,
        claim: PolicyClaim,
        points: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Compare claimed scalar value vs retrieved series value near claim period."""
        claimed = self._extract_claimed_value(claim)
        if claimed is None or not points:
            return None

        observed = self._target_value_from_points(claim, points)
        if observed is None:
            return None

        observed_value, observed_date = observed
        tolerance = float(os.environ.get("ALETHEIA_CLAIM_VALUE_TOLERANCE", "0.5"))
        delta = claimed - observed_value
        return {
            "claimed_value": round(claimed, 4),
            "observed_value": round(observed_value, 4),
            "observed_date": observed_date,
            "delta": round(delta, 4),
            "absolute_delta": round(abs(delta), 4),
            "tolerance": tolerance,
            "within_tolerance": abs(delta) <= tolerance,
        }

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
        claim_value_check = None
        if points:
            break_result = await self.detect_structural_break(
                values,
                dates,
                hint_year=extract_year(claim.period_end) or extract_year(claim.period_start),
            )
            observed_change = self._observed_change(claim, points)
            claim_value_check = self._check_claim_value(claim, points)

        return {
            "data_retrieved": bool(data.get("data_available")),
            "structural_break_detected": break_result,
            "observed_change": observed_change,
            "claim_value_check": claim_value_check,
            "raw_data": data,
            "analysis_note": "Data retrieved from live APIs where connectors are available.",
        }
