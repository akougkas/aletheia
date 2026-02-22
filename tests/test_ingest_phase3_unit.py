from aletheia.ingest import _guess_agency_code


def test_guess_agency_code_maps_federal_reserve_domain():
    code = _guess_agency_code(
        "https://www.federalreserve.gov/econres/feds/example.htm",
        "Federal Reserve analysis",
    )
    assert code == "FED"


def test_guess_agency_code_maps_nber_domain():
    code = _guess_agency_code("https://www.nber.org/papers/w27352", "NBER paper")
    assert code == "NBER"
