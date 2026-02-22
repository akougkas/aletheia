from psycopg import sql

from aletheia.ingest import _guess_agency_code, _table_count


class _FakeCursor:
    def __init__(self):
        self.query = None

    def execute(self, query):
        self.query = query

    def fetchone(self):
        return (7,)


def test_table_count_uses_identifier_composition():
    cur = _FakeCursor()
    count = _table_count(cur, "documents")
    assert count == 7
    assert isinstance(cur.query, sql.Composed)


def test_guess_agency_code_maps_federal_reserve_domain():
    code = _guess_agency_code(
        "https://www.federalreserve.gov/econres/feds/example.htm",
        "Federal Reserve analysis",
    )
    assert code == "FED"


def test_guess_agency_code_maps_nber_domain():
    code = _guess_agency_code("https://www.nber.org/papers/w27352", "NBER paper")
    assert code == "NBER"
