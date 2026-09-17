import pytest

from cvm_poller.ticker import TickerNotFound, issuing_code, looks_like_ticker, resolve_ticker


def test_looks_like_ticker():
    assert looks_like_ticker("PETR4")
    assert looks_like_ticker("vale3")
    assert looks_like_ticker("SANB11")
    assert looks_like_ticker("JPMC34")
    assert looks_like_ticker("C1MG34")
    assert looks_like_ticker("A1DM34")
    assert not looks_like_ticker("PETR")
    assert not looks_like_ticker("PETROBRAS")
    assert not looks_like_ticker("asdf")
    assert not looks_like_ticker("1234")
    assert not looks_like_ticker("")


def test_issuing_code_strips_share_class():
    assert issuing_code("PETR4") == "PETR"
    assert issuing_code("vale3") == "VALE"
    assert issuing_code("SANB11") == "SANB"
    assert issuing_code("C1MG34") == "C1MG"
    assert issuing_code("PETR") == "PETR"


def test_resolve_ticker_matches_issuing_company():
    companies = [
        {
            "codeCVM": "9512",
            "issuingCompany": "PETR",
            "companyName": "PETROLEO BRASILEIRO S.A. PETROBRAS",
            "tradingName": "PETROBRAS",
        }
    ]
    info = resolve_ticker("PETR4", companies=companies)
    assert info.ccvm == "9512"
    assert info.issuing_company == "PETR"
    assert info.ticker == "PETR4"


def test_resolve_unknown_ticker_raises():
    with pytest.raises(TickerNotFound):
        resolve_ticker("XXXX9", companies=[])
