from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SEED_SQL = ROOT / "sql" / "seed_cases.sql"
VALIDATION_SQL = ROOT / "sql" / "validate_seed_cases.sql"


def test_seed_cases_include_all_benchmark_ids_and_complete_links():
    sql = SEED_SQL.read_text(encoding="utf-8")

    expected_ids = [f"MB-{idx:03d}" for idx in range(1, 11)]
    for case_id in expected_ids:
        assert f"'{case_id}'" in sql

    link_ids = re.findall(r"WHERE mc\.benchmark_case_id = '(MB-\d{3})'", sql)
    assert sorted(set(link_ids)) == expected_ids


def test_case_8_is_mapped_to_mortality_dataset():
    sql = SEED_SQL.read_text(encoding="utf-8")
    case8_insert = re.search(
        r"'MB-008'.+?\(SELECT id FROM datasets WHERE code = '([^']+)'\)",
        sql,
        re.DOTALL,
    )
    assert case8_insert, "Could not locate MB-008 insert block"
    assert case8_insert.group(1) == "EU-MORTALITY"


def test_validation_script_checks_case_ids_and_indicator_links():
    sql = VALIDATION_SQL.read_text(encoding="utf-8")
    assert "Missing benchmark_case_id values" in sql
    assert "do not map to indicators" in sql
    assert "MB-008 must be mapped to EU-MORTALITY dataset" in sql
