import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _query_rows(result):
    if not result:
        return []
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                rows = item.get("result", [])
                if isinstance(rows, list):
                    return rows
    return []


@pytest.mark.skipif(
    os.environ.get("ALETHEIA_RUN_INTEGRATION") != "1",
    reason="Set ALETHEIA_RUN_INTEGRATION=1 to run Surreal-backed CLI integration checks.",
)
def test_case_history_export_and_graph_with_live_db():
    from aletheia.db import get_connection

    async def _setup_data():
        async with get_connection() as db:
            case_result = await db.query(
                "CREATE case SET name = $name, description = 'integration-test', status = 'active'",
                {"name": "integration-case-cli"},
            )
            case_rows = _query_rows(case_result)
            case_id = str(case_rows[0]["id"])

            session_result = await db.query(
                """
                CREATE session SET
                    claim_text = 'Integration session claim',
                    claim_indicator = 'integration',
                    case_id = $case,
                    status = 'completed',
                    started_at = time::now(),
                    completed_at = time::now()
                """,
                {"case": case_id},
            )
            session_id = str(_query_rows(session_result)[0]["id"])

            batch_result = await db.query(
                """
                CREATE batch SET
                    name = 'integration-batch',
                    case_id = $case,
                    status = 'completed',
                    total_claims = 1,
                    completed_claims = 1,
                    started_at = time::now(),
                    completed_at = time::now(),
                    results = { succeeded: 1, failed: 0, avg_confidence: 0.8 }
                """,
                {"case": case_id},
            )
            batch_id = str(_query_rows(batch_result)[0]["id"])

            await db.query(
                "RELATE $case->has_session->$session",
                {"case": case_id, "session": session_id},
            )
            await db.query(
                "RELATE $case->has_batch->$batch", {"case": case_id, "batch": batch_id}
            )

            await db.query(
                "CREATE agency:integration SET code = 'INT-AGENCY', name = 'Integration Agency'"
            )
            await db.query(
                "CREATE dataset:integration SET code = 'INT-DS', name = 'Integration Dataset'"
            )
            await db.query(
                "CREATE methodology_change:integration SET change_type = 'definition_change', description = 'Integration change', effective_date = time::now()"
            )
            await db.query(
                "CREATE document:integration SET title = 'Integration method note', url = 'https://example.org/integration'"
            )
            await db.query("RELATE agency:integration->publishes->dataset:integration")
            await db.query(
                "RELATE methodology_change:integration->belongs_to->dataset:integration"
            )
            await db.query(
                "RELATE document:integration->describes->methodology_change:integration"
            )
            await db.query(
                "RELATE $session->found->document:integration", {"session": session_id}
            )

            return case_id, session_id

    case_id, session_id = asyncio.run(_setup_data())

    history = subprocess.run(
        ["uv", "run", "aletheia", "--plain", "case", "history", case_id, "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert history.returncode == 0, history.stderr
    history_payload = json.loads(history.stdout)
    assert history_payload["case"]["id"] == case_id
    assert history_payload["rollup"]["total_sessions"] >= 1
    assert history_payload["rollup"]["total_batches"] >= 1

    export = subprocess.run(
        [
            "uv",
            "run",
            "aletheia",
            "--plain",
            "case",
            "export",
            case_id,
            "--format",
            "jsonl",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert export.returncode == 0, export.stderr
    lines = [line for line in export.stdout.splitlines() if line.strip()]
    types = [json.loads(line)["type"] for line in lines]
    assert "case" in types
    assert "session" in types
    assert "batch" in types

    provenance = subprocess.run(
        ["uv", "run", "aletheia", "--plain", "graph", "provenance", session_id],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert provenance.returncode == 0, provenance.stderr
    assert "Evidence Documents" in provenance.stdout
    assert "Methodology Changes" in provenance.stdout

    timeline = subprocess.run(
        ["uv", "run", "aletheia", "--plain", "graph", "timeline", "INT-DS"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert timeline.returncode == 0, timeline.stderr
    assert "Methodology Timeline" in timeline.stdout
