"""Cross-platform DB bootstrap helper for local ALETHEIA environments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from aletheia.db import get_db_url, install_pgai


ROOT = Path(__file__).resolve().parents[1]


def _execute_sql(conn: psycopg.Connection, sql_path: Path) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    if not sql.strip():
        return
    with conn.cursor() as cur:
        cur.execute(sql)


def _has_seeded_benchmark_cases(conn: psycopg.Connection) -> bool:
    """Detect whether benchmark seed rows are already present."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS case_count
            FROM methodology_changes
            WHERE benchmark_case_id LIKE 'MB-%'
            """
        )
        row = cur.fetchone()
    return bool(row and int(row[0]) >= 10)


def bootstrap_db(
    *,
    include_seed: bool = True,
    include_validate: bool = True,
) -> dict[str, str]:
    """Install pgai and optionally seed/validate."""
    install_pgai()

    actions: list[str] = []
    with psycopg.connect(get_db_url()) as conn:
        if include_seed:
            _execute_sql(conn, ROOT / "sql" / "seed_cases.sql")
            actions.append("seed")

        if include_validate:
            if include_seed or _has_seeded_benchmark_cases(conn):
                _execute_sql(conn, ROOT / "sql" / "validate_seed_cases.sql")
                actions.append("validate")
            else:
                actions.append("validate_skipped_no_seed_data")

        conn.commit()

    return {
        "db_url_redacted": get_db_url(redacted=True),
        "actions": ",".join(actions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap ALETHEIA DB without psql dependency."
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Skip benchmark seed load.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip seed validation script.",
    )
    args = parser.parse_args()

    result = bootstrap_db(
        include_seed=not args.no_seed,
        include_validate=not args.no_validate,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
