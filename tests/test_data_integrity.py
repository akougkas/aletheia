"""Validate YAML data files: parseable, required fields, referential integrity."""

from aletheia.data_loader import (
    domain_to_agency_code,
    load_agencies,
    load_datasets,
    load_indicators,
    load_methodology_breaks,
    load_reference_docs,
)


def test_agencies_required_fields():
    for a in load_agencies():
        for key in ("code", "name", "country", "url", "domains"):
            assert key in a, f"Agency {a.get('code', '?')} missing field '{key}'"
        assert isinstance(a["domains"], list) and len(a["domains"]) > 0


def test_datasets_required_fields():
    for ds in load_datasets():
        for key in ("code", "name", "agency_code", "description", "frequency"):
            assert key in ds, f"Dataset {ds.get('code', '?')} missing field '{key}'"


def test_indicators_required_fields():
    for ind in load_indicators():
        for key in ("dataset_code", "code", "name", "unit", "description"):
            assert key in ind, f"Indicator {ind.get('code', '?')} missing field '{key}'"


def test_breaks_required_fields():
    required = (
        "benchmark_case_id", "dataset_code", "indicator_code",
        "change_type", "effective_date", "description",
        "impact_estimate", "severity", "comparability", "source_url",
    )
    for b in load_methodology_breaks():
        for key in required:
            assert key in b, f"Break {b.get('benchmark_case_id', '?')} missing field '{key}'"


def test_breaks_reference_valid_datasets():
    ds_codes = {d["code"] for d in load_datasets()}
    for b in load_methodology_breaks():
        assert b["dataset_code"] in ds_codes, (
            f"Break {b['benchmark_case_id']} references unknown dataset {b['dataset_code']}"
        )


def test_breaks_reference_valid_indicators():
    ind_codes = {i["code"] for i in load_indicators()}
    for b in load_methodology_breaks():
        assert b["indicator_code"] in ind_codes, (
            f"Break {b['benchmark_case_id']} references unknown indicator {b['indicator_code']}"
        )


def test_indicators_reference_valid_datasets():
    ds_codes = {d["code"] for d in load_datasets()}
    for ind in load_indicators():
        assert ind["dataset_code"] in ds_codes


def test_datasets_reference_valid_agencies():
    agency_codes = {a["code"] for a in load_agencies()}
    for ds in load_datasets():
        assert ds["agency_code"] in agency_codes


def test_reference_docs_structure():
    docs = load_reference_docs()
    assert "known_method_doc_urls" in docs
    assert "extra_reference_docs" in docs
    assert isinstance(docs["known_method_doc_urls"], dict)
    assert isinstance(docs["extra_reference_docs"], list)
    assert len(docs["known_method_doc_urls"]) >= 10
    assert len(docs["extra_reference_docs"]) >= 7


def test_domain_to_agency_code_mapping():
    mapping = domain_to_agency_code()
    assert mapping["bls.gov"] == "BLS"
    assert mapping["cdc.gov"] == "CDC"
    assert mapping["federalreserve.gov"] == "FED"
    assert len(mapping) == 9
