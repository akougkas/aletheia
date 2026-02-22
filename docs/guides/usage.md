# Usage & Execution Paths (AI Context)

**Target Audience**: AI coding assistants writing run scripts, modifying CLI endpoints, or creating testing harnesses.

## 1. Interactive CLI (`cli.py`)
The primary interactive surface. Utilizes `Typer` and `Rich`.

**Commands**:
- `uv run python cli.py interactive`: Starts a REPL session.
- `uv run python cli.py claim "<TEXT>"`: Process a single claim.
  - Flags: `--trace` (print agent logs), `--json` (raw JSON output), `--profile-file <PATH>` (load specific config).
- `uv run python cli.py retrieval-stats`: Prints hit rates and cache observability.

## 2. Integration Demo Harness (`demo.py`)
Used for full-system E2E validation against the 10 seeded benchmark cases.

**Execution Modes**:
- `uv run python demo.py --quick`: Executes the Phase 2 pipeline (Parser -> Router -> Aggregator -> Editor) across all benchmark cases.
- `uv run python demo.py --quick --assert-phase2`: Strict mode. Fails with a non-zero exit code if required routing logic (e.g., fallback/deep research) is missing or broken. Used in CI.
- `uv run python demo.py --quick --plain`: Disables rich UI rendering, outputting raw text.

**Programmatic Access**:
The `demo.py` script relies on `aletheia.agents.orchestrator.OrchestratorAgent.process_claim()`. When modifying orchestrator inputs, ensure `demo.py` is updated.

## 3. Testing (`tests/`)
Uses `pytest`. Tests are heavily isolated into unit vs integration.

**Run All Tests**:
```bash
uv run --extra dev pytest
```

**Integration Tests**:
Tests requiring a live, seeded Postgres instance are marked with `@pytest.mark.integration`.
```bash
ALETHEIA_RUN_INTEGRATION=1 uv run --extra dev pytest -m integration -q
```
*Note*: If `ALETHEIA_RUN_INTEGRATION` is not set, these tests are skipped.

**Key Test Files for AI Modification Reference**:
- `test_analyst_break_detection.py`: Mathematical break algorithms.
- `test_evidence_phase2.py`: Router logic and aggregator scoring heuristics.
- `test_editor_policy_logic.py`: Synthesis and `VerdictStatus` logic rules.