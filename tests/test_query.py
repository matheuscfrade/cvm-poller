from cvm_poller.parse import DownloadMultiploResult, IpeLink
from cvm_poller.query import filter_links, run_query

LINKS = [
    IpeLink(
        url="https://example/a",
        documento="IPE",
        ccvm="2612",
        data_ref="14/09/2026",
        frm_dt_ref="14/09/2026",
        categoria="Fato Relevante",
        tipo="-",
        especie="-",
        situacao="Ativo",
        empresa="ONCOCLINICAS",
    ),
    IpeLink(
        url="https://example/b",
        documento="IPE",
        ccvm="2201",
        data_ref="14/09/2026",
        frm_dt_ref="14/09/2026",
        categoria="Assembleia",
        tipo="AGDEB",
        especie="Edital",
        situacao="Ativo",
        empresa="MILLS",
    ),
]


def test_filter_categoria_is_case_insensitive():
    kept = filter_links(LINKS, categoria="fato relevante")
    assert [item.ccvm for item in kept] == ["2612"]


def test_run_query_ticker_filters_by_resolved_ccvm():
    sample = DownloadMultiploResult(
        data_solicitada="14/09/2026 00:00",
        documento="IPE",
        data_consulta="",
        links=LINKS,
        source="public",
    )
    captured = {}

    def fake_public(**kwargs):
        captured.update(kwargs)
        return sample

    class Info:
        ccvm = "2612"
        issuing_company = "ONCO"
        ticker = "ONCO3"
        company_name = "ONCOCLINICAS"

    result = run_query(
        source="public",
        data="14/09/2026",
        ticker="ONCO3",
        fetch_public=fake_public,
        resolve=lambda ticker: Info(),
    )
    assert captured.get("empresa") == ""
    assert [item.ccvm for item in result.links] == ["2612"]
    assert result.ticker == "ONCO3"


def test_run_query_public_does_not_need_login():
    sample = DownloadMultiploResult(
        data_solicitada="14/09/2026 00:00",
        documento="IPE",
        data_consulta="",
        links=LINKS,
        source="public",
    )
    result = run_query(
        source="public",
        data="14/09/2026",
        categoria="Assembleia",
        fetch_public=lambda **kwargs: sample,
        fetch_login=lambda **kwargs: (_ for _ in ()).throw(AssertionError("login")),
    )
    assert result.source == "public"
    assert len(result.links) == 1
    assert result.links[0].empresa == "MILLS"
