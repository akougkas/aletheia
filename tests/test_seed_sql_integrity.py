"""Validate seed data YAML files have expected content."""

from aletheia.data_loader import load_agencies, load_datasets, load_indicators


def test_seed_agencies_count_and_codes():
    agencies = load_agencies()
    assert len(agencies) == 9
    codes = {a["code"] for a in agencies}
    assert codes == {"CDC", "BLS", "CENSUS", "EUROSTAT", "ECB", "CSO", "FED", "NBER", "UNECE"}


def test_seed_datasets_count_and_codes():
    datasets = load_datasets()
    assert len(datasets) == 9
    codes = {d["code"] for d in datasets}
    expected = {"NHIS", "CPS", "ACS", "CPI", "EU-LFS", "HICP",
                "EU-MORTALITY", "ESA2010", "EU-SILC"}
    assert codes == expected


def test_seed_indicators_count():
    assert len(load_indicators()) == 10


def test_each_indicator_references_valid_dataset():
    ds_codes = {d["code"] for d in load_datasets()}
    for ind in load_indicators():
        assert ind["dataset_code"] in ds_codes, (
            f"Indicator {ind['code']} references unknown dataset {ind['dataset_code']}"
        )


def test_each_dataset_references_valid_agency():
    agency_codes = {a["code"] for a in load_agencies()}
    for ds in load_datasets():
        assert ds["agency_code"] in agency_codes, (
            f"Dataset {ds['code']} references unknown agency {ds['agency_code']}"
        )


def test_eu_mortality_dataset_exists():
    """MB-008 depends on EU-MORTALITY — must be present."""
    ds_codes = {d["code"] for d in load_datasets()}
    assert "EU-MORTALITY" in ds_codes
