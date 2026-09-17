from pathlib import Path

from cvm_poller.parse import IpeLink
from app.store import Store


def _link(**kwargs) -> IpeLink:
    base = dict(
        url="https://example/pdf?numProtocolo=111",
        documento="IPE",
        ccvm="9512",
        data_ref="14/09/2026",
        frm_dt_ref="14/09/2026",
        categoria="Fato Relevante",
        tipo="-",
        especie="Mudança",
        situacao="Liberado",
        empresa="PETROBRAS",
        data_entrega="14/09/2026 09:13",
        protocolo="",
    )
    base.update(kwargs)
    return IpeLink(**base)


def test_insert_is_idempotent(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    first = store.upsert_filings([_link()], source="login")
    second = store.upsert_filings([_link()], source="login")
    assert first == 1
    assert second == 0
    rows = store.list_filings()
    assert len(rows) == 1
    assert rows[0]["protocolo"] == "111"
    assert rows[0]["ccvm"] == "9512"


def test_list_filters_ccvm_and_categoria(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    store.upsert_filings(
        [
            _link(protocolo="1", url="https://a?numProtocolo=1", ccvm="9512"),
            _link(
                protocolo="2",
                url="https://b?numProtocolo=2",
                ccvm="4170",
                categoria="Assembleia",
                empresa="VALE",
            ),
        ],
        source="login",
    )
    store._conn.execute("UPDATE filings SET ticker='PETR' WHERE protocolo='1'")
    store._conn.commit()
    only_petro = store.list_filings(ccvm="9512")
    assert [row["ccvm"] for row in only_petro] == ["9512"]
    by_ticker = store.list_filings(ticker="PETR4")
    assert [row["ticker"] for row in by_ticker] == ["PETR"]
    fatos = store.list_filings(categoria="Fato Relevante")
    assert len(fatos) == 1
    paged = store.list_filings(limit=1, offset=1)
    assert len(paged) == 1
    assert paged[0]["protocolo"] != store.list_filings(limit=1, offset=0)[0]["protocolo"]
    vale = store.list_filings(empresa="vale")
    assert [row["empresa"] for row in vale] == ["VALE"]
    cats = store.list_categorias()
    assert "Fato Relevante" in cats
    assert "Assembleia" in cats
    nenhum = store.list_filings(empresa="vale", categoria="Fato Relevante")
    assert nenhum == []


def test_list_filings_can_keep_only_b3_or_brazilian_stocks(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    store.upsert_filings(
        [
            _link(protocolo="1", url="https://a?numProtocolo=1", ccvm="9512"),
            _link(
                protocolo="2",
                url="https://b?numProtocolo=2",
                ccvm="50571",
                empresa="JPMORGAN",
            ),
            _link(
                protocolo="3",
                url="https://c?numProtocolo=3",
                ccvm="10561",
                empresa="SEIVA",
            ),
        ],
        source="login",
    )
    store._conn.execute("UPDATE filings SET ticker='PETR' WHERE protocolo='1'")
    store._conn.execute("UPDATE filings SET ticker='JPMC34' WHERE protocolo='2'")
    store._conn.execute("UPDATE filings SET ticker='' WHERE protocolo='3'")
    store._conn.commit()
    assert {row["ticker"] for row in store.list_filings(listagem="b3")} == {"PETR", "JPMC34"}
    assert {row["ticker"] for row in store.list_filings(listagem="acoes")} == {"PETR"}
    assert store.count_filings(listagem="todas") == 3
    assert store.count_filings(listagem="") == 3


def test_list_filings_tickers_matches_any_favorite(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    store.upsert_filings(
        [
            _link(protocolo="1", url="https://a?numProtocolo=1", ccvm="9512"),
            _link(
                protocolo="2",
                url="https://b?numProtocolo=2",
                ccvm="4170",
                empresa="VALE",
            ),
            _link(
                protocolo="3",
                url="https://c?numProtocolo=3",
                ccvm="50571",
                empresa="JPMORGAN",
            ),
        ],
        source="login",
    )
    store._conn.execute("UPDATE filings SET ticker='PETR' WHERE protocolo='1'")
    store._conn.execute("UPDATE filings SET ticker='VALE3' WHERE protocolo='2'")
    store._conn.execute("UPDATE filings SET ticker='JPMC34' WHERE protocolo='3'")
    store._conn.commit()
    rows = store.list_filings(tickers=["PETR4", "VALE3"])
    assert {row["protocolo"] for row in rows} == {"1", "2"}
    assert store.count_filings(tickers=["PETR4", "VALE3"]) == 2
    assert store.list_filings(tickers=["JPMC34"])[0]["ticker"] == "JPMC34"
    assert store.list_filings(tickers=[]) == store.list_filings()


def test_list_protocolos_returns_all_ids_without_pagination(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    store.upsert_filings(
        [
            _link(protocolo=str(i), url=f"https://a?numProtocolo={i}", data_entrega="14/09/2026 09:13")
            for i in range(1, 61)
        ],
        source="login",
    )
    ids = store.list_protocolos()
    assert len(ids) == 60
    assert set(ids) == {str(i) for i in range(1, 61)}
    assert len(store.list_filings(limit=50)) == 50


def test_list_filings_filters_by_entrega_date(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    store.upsert_filings(
        [
            _link(protocolo="1", url="https://a?numProtocolo=1", data_entrega="14/09/2026 09:13"),
            _link(protocolo="2", url="https://b?numProtocolo=2", data_entrega="15/09/2026 18:40"),
            _link(protocolo="3", url="https://c?numProtocolo=3", data_entrega="16/09/2026 07:01"),
        ],
        source="login",
    )
    only_15 = store.list_filings(data_de="15/09/2026", data_ate="15/09/2026")
    assert [row["protocolo"] for row in only_15] == ["2"]
    assert [row["protocolo"] for row in store.list_filings(data_de="2026-09-15", data_ate="2026-09-15")] == ["2"]
    assert {row["protocolo"] for row in store.list_filings(data_de="15/09/2026 00:00", data_ate="15/09/2026 23:59")} == {"2"}
    assert {row["protocolo"] for row in store.list_filings(data_de="2026-09-14", data_ate="2026-09-15")} == {"1", "2"}
    assert store.count_filings(data_de="16/09/2026") == 1


def test_login_link_does_not_copy_ref_into_entrega(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    store.upsert_filings(
        [_link(data_entrega="", data_ref="14/10/2026 16:00:00")],
        source="login",
    )
    row = store.list_filings()[0]
    assert row["data_ref"] == "14/10/2026 16:00:00"
    assert row["data_entrega"] == ""


def test_list_tickers_returns_distinct_and_filters_query(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    store.upsert_filings(
        [
            _link(protocolo="1", url="https://a?numProtocolo=1"),
            _link(protocolo="2", url="https://b?numProtocolo=2", ccvm="4170", empresa="VALE"),
        ],
        source="login",
    )
    store._conn.execute("UPDATE filings SET ticker='PETR4' WHERE protocolo='1'")
    store._conn.execute("UPDATE filings SET ticker='VALE3' WHERE protocolo='2'")
    store._conn.commit()
    tickers = {row["ticker"] for row in store.list_tickers()}
    assert tickers == {"PETR4", "VALE3"}
    only_petr = store.list_tickers(query="pet")
    assert [row["ticker"] for row in only_petr] == ["PETR4"]
    assert only_petr[0]["empresa"] == "PETROBRAS"
    assert only_petr[0]["has_docs"] is True


def test_list_tickers_includes_listed_without_filings_and_does_not_cap_early(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    store.upsert_companies(
        [
            {
                "codeCVM": "4170",
                "issuingCompany": "VALE3",
                "tradingName": "VALE",
                "companyName": "VALE S.A.",
                "otherCodes": [{"code": "VALE3"}, {"code": "VALE5"}],
            },
            {
                "codeCVM": "99999",
                "issuingCompany": "NOVA",
                "tradingName": "NOVA EMPRESA",
                "companyName": "NOVA EMPRESA S.A.",
                "otherCodes": [{"code": "NOVA3"}],
            },
        ]
    )
    store.upsert_filings(
        [
            _link(protocolo=str(i), url=f"https://a?numProtocolo={i}", empresa=f"C{i:03d}")
            for i in range(1, 130)
        ],
        source="login",
    )
    for i in range(1, 130):
        store._conn.execute(
            "UPDATE filings SET ticker=? WHERE protocolo=?",
            (f"T{i:03d}", str(i)),
        )
    store._conn.commit()
    rows = store.list_tickers()
    codes = {row["ticker"] for row in rows}
    assert len(rows) > 120
    assert "T001" in codes
    assert "T129" in codes
    assert "NOVA3" in codes
    assert "VALE5" in codes
    nova = next(row for row in rows if row["ticker"] == "NOVA3")
    assert nova["has_docs"] is False
    vale = store.list_tickers(query="VALE5")
    assert {row["ticker"] for row in vale} >= {"VALE5"}
    petr = store.list_tickers(query="NOVA4")
    assert "NOVA3" in {row["ticker"] for row in petr}


def test_enriches_ticker_from_companies(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    store.upsert_companies(
        [
            {
                "codeCVM": "9512",
                "issuingCompany": "PETR",
                "tradingName": "PETROBRAS",
                "companyName": "PETROLEO BRASILEIRO S.A. PETROBRAS",
            }
        ]
    )
    store.upsert_filings([_link(data_entrega="", empresa="")], source="login")
    row = store.list_filings()[0]
    assert row["ticker"] == "PETR"
    assert row["empresa"] == "PETROLEO BRASILEIRO S.A. PETROBRAS"


def test_enriches_via_b3_detail_lookup(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    store.upsert_filings(
        [_link(ccvm="50571", empresa="", data_entrega="")],
        source="login",
    )

    def fake_detail(ccvm: str):
        assert ccvm == "50571"
        return {
            "codeCVM": "50571",
            "issuingCompany": "JPMC",
            "tradingName": "JPMORGAN",
            "companyName": "JPMORGAN CHASE & CO.",
            "otherCodes": [{"code": "JPMC34"}],
        }

    updated = store.enrich_missing(fetch_detail=fake_detail)
    assert updated == 1
    row = store.list_filings()[0]
    assert row["ticker"] == "JPMC34"
    assert row["empresa"] == "JPMORGAN CHASE & CO."


def test_find_known_ticker_matches_bdr_and_prefix(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    store.upsert_filings([_link(protocolo="1", url="https://a?numProtocolo=1")], source="login")
    store._conn.execute("UPDATE filings SET ticker='PETR' WHERE protocolo='1'")
    store.upsert_filings(
        [
            _link(
                protocolo="2",
                url="https://b?numProtocolo=2",
                ccvm="26100",
                empresa="COMCAST CORPORATION",
            )
        ],
        source="login",
    )
    store._conn.execute("UPDATE filings SET ticker='C1MG34' WHERE protocolo='2'")
    store._conn.commit()
    petr = store.find_known_ticker("PETR4")
    assert petr is not None
    assert petr["ticker"] == "PETR4"
    comcast = store.find_known_ticker("c1mg34")
    assert comcast is not None
    assert comcast["ticker"] == "C1MG34"
    assert comcast["empresa"] == "COMCAST CORPORATION"
    assert store.find_known_ticker("XXXX9") is None


def test_favorites_and_outbox(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    user = store.upsert_user("ana@example.com")
    store.add_favorite(user["id"], ccvm="9512", ticker="PETR4")
    inserted = store.upsert_filings([_link()], source="login")
    queued = store.enqueue_alerts_for_new([_link()])
    assert inserted == 1
    assert queued == 1
    pending = store.pending_outbox()
    assert pending[0]["canal"] == "email"
    assert pending[0]["filing_protocolo"] == "111"
