"""Run a UV-native smoke flow for the case-centric CLI."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path


def _run(cmd: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc.stdout


def _extract_case_id(text: str) -> str:
    match = re.search(r"Case created:\s*(case:[^\s]+)", text)
    if not match:
        raise RuntimeError("Failed to parse case id from case create output")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run case-centric smoke workflow")
    parser.add_argument(
        "--claim",
        default="The US unemployment rate fell in 2021.",
        help="Primary claim for the smoke run.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]

    with tempfile.TemporaryDirectory(prefix="aletheia-smoke-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        claims_file = tmp_path / "claims.txt"
        export_file = tmp_path / "case_export.json"
        claims_file.write_text(
            f"{args.claim}\nThe US CPI rose in 2022.\n", encoding="utf-8"
        )

        case_name = f"smoke-case-{int(time.time())}"
        create_output = _run(
            ["uv", "run", "aletheia", "--plain", "case", "create", case_name],
            cwd=repo_root,
        )
        case_id = _extract_case_id(create_output)

        _run(
            [
                "uv",
                "run",
                "aletheia",
                "--plain",
                "claim",
                args.claim,
                "--case",
                case_id,
            ],
            cwd=repo_root,
        )
        _run(
            [
                "uv",
                "run",
                "aletheia",
                "--plain",
                "batch",
                str(claims_file),
                "--case",
                case_id,
            ],
            cwd=repo_root,
        )
        history_output = _run(
            [
                "uv",
                "run",
                "aletheia",
                "--plain",
                "case",
                "history",
                case_id,
                "--json",
            ],
            cwd=repo_root,
        )
        history_payload = json.loads(history_output)
        if history_payload.get("rollup", {}).get("total_sessions", 0) < 1:
            raise RuntimeError(
                "Smoke workflow expected at least one session in case history"
            )

        _run(
            [
                "uv",
                "run",
                "aletheia",
                "--plain",
                "case",
                "export",
                case_id,
                "--format",
                "json",
                "--output",
                str(export_file),
            ],
            cwd=repo_root,
        )
        if not export_file.exists():
            raise RuntimeError("Smoke workflow expected exported JSON file")

        print(f"Smoke workflow complete for {case_id}")
        print(f"Export file: {export_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
