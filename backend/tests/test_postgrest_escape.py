from utils.postgrest_escape import escape_postgrest_ilike


def test_escape_wildcards_and_commas():
    assert escape_postgrest_ilike("a%b_c,d") == "a\\%b\\_cd"


def test_escape_truncates_long_input():
    assert len(escape_postgrest_ilike("x" * 200)) == 100
