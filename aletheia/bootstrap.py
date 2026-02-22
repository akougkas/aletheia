"""Cross-platform DB bootstrap helper for local ALETHEIA environments (SurrealDB)."""

from __future__ import annotations

import argparse
import asyncio
import json

from aletheia.data_loader import load_agencies, load_datasets, load_indicators
from aletheia.db import apply_schema, get_connection, get_db_url
from aletheia.ingest import seed_phase3_methodology_breaks


def _query_result_rows(result):
    if not result:
        return []
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                rows = item.get("result", [])
                if isinstance(rows, list):
                    return rows
            elif isinstance(item, list):
                return item
        return result if all(isinstance(r, dict) for r in result) else []
    return []


def _surreal_id(record):
    if isinstance(record, dict):
        return str(record.get("id", ""))
    if isinstance(record, list) and record:
        return _surreal_id(record[0])
    return str(record)


async def _seed_reference_data(db) -> list[str]:
    """Seed agencies, datasets, indicators, and their graph edges."""
    actions: list[str] = []

    # Agencies
    for a in load_agencies():
        await db.query(
            """
            UPSERT agency SET
                code = $code, name = $name, country = $country, url = $url
            WHERE code = $code
            """,
            {"code": a["code"], "name": a["name"], "country": a["country"], "url": a["url"]},
        )
    actions.append("agencies")

    # Datasets + publishes edges
    for ds in load_datasets():
        result = await db.query(
            """
            UPSERT dataset SET
                code = $code, name = $name, description = $description, frequency = $frequency
            WHERE code = $code
            """,
            {"code": ds["code"], "name": ds["name"], "description": ds["description"], "frequency": ds["frequency"]},
        )
        ds_rows = _query_result_rows(result)
        if ds_rows:
            ds_id = _surreal_id(ds_rows[0])
            agency_result = await db.query(
                "SELECT * FROM agency WHERE code = $code LIMIT 1",
                {"code": ds["agency_code"]},
            )
            agency_rows = _query_result_rows(agency_result)
            if agency_rows:
                agency_id = _surreal_id(agency_rows[0])
                await db.query(
                    "RELATE $agency->publishes->$dataset",
                    {"agency": agency_id, "dataset": ds_id},
                )
    actions.append("datasets")

    # Indicators + has_indicator edges
    for ind in load_indicators():
        result = await db.query(
            """
            UPSERT indicator SET
                code = $code, name = $name, unit = $unit, description = $description
            WHERE code = $code
            """,
            {"code": ind["code"], "name": ind["name"], "unit": ind["unit"], "description": ind["description"]},
        )
        ind_rows = _query_result_rows(result)
        if ind_rows:
            ind_id = _surreal_id(ind_rows[0])
            ds_result = await db.query(
                "SELECT * FROM dataset WHERE code = $code LIMIT 1",
                {"code": ind["dataset_code"]},
            )
            ds_rows = _query_result_rows(ds_result)
            if ds_rows:
                ds_id = _surreal_id(ds_rows[0])
                await db.query(
                    "RELATE $dataset->has_indicator->$indicator",
                    {"dataset": ds_id, "indicator": ind_id},
                )
    actions.append("indicators")

    return actions


async def _has_seeded_benchmark_cases(db) -> bool:
    """Detect whether benchmark seed rows are already present."""
    result = await db.query(
        """
        SELECT count() AS total FROM methodology_change
        WHERE benchmark_case_id CONTAINS 'MB-'
        GROUP ALL
        """
    )
    rows = _query_result_rows(result)
    return bool(rows and int(rows[0].get("total", 0)) >= 10)


async def bootstrap_db(
    *,
    include_seed: bool = True,
    include_validate: bool = True,
    include_phase3_breaks: bool = True,
) -> dict[str, str]:
    """Apply schema, seed reference data, and optionally seed Phase 3 breaks."""
    await apply_schema()

    actions: list[str] = ["schema"]

    async with get_connection() as db:
        if include_seed:
            seed_actions = await _seed_reference_data(db)
            actions.extend(seed_actions)

            if include_phase3_breaks:
                await seed_phase3_methodology_breaks(dry_run=False)
                actions.append("seed_phase3_breaks")

        if include_validate:
            has_cases = await _has_seeded_benchmark_cases(db)
            if include_seed or has_cases:
                # Validate: count methodology changes
                result = await db.query(
                    "SELECT count() AS total FROM methodology_change GROUP ALL"
                )
                rows = _query_result_rows(result)
                count = int(rows[0].get("total", 0)) if rows else 0
                actions.append(f"validate({count} changes)")
            else:
                actions.append("validate_skipped_no_seed_data")

    return {
        "db_url_redacted": get_db_url(redacted=True),
        "actions": ",".join(actions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap ALETHEIA SurrealDB schema and seed data."
    )
    parser.add_argument("--no-seed", action="store_true", help="Skip benchmark seed load.")
    parser.add_argument("--no-validate", action="store_true", help="Skip seed validation.")
    parser.add_argument("--no-phase3-breaks", action="store_true", help="Skip Phase 3 methodology breaks.")
    args = parser.parse_args()

    result = asyncio.run(
        bootstrap_db(
            include_seed=not args.no_seed,
            include_validate=not args.no_validate,
            include_phase3_breaks=not args.no_phase3_breaks,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
