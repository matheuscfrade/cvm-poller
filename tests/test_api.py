from pathlib import Path

from fastapi.testclient import TestClient

from app.store import Store
from app.web import create_app
from cvm_poller.parse import IpeLink
from cvm_poller.ticker import TickerInfo, TickerNotFound


def _app(tmp_path: Path) -> tuple[TestClient, Store]:
    store = Store(tmp_path / "ipe.db")
    store.upsert_filings(
        [
            IpeLink(
                url="https://rad/p?numProtocolo=77",
                documento="IPE",
                ccvm="9512",
                data_ref="14/09/2026",
                frm_dt_ref="",
                categoria="Fato Relevante",
                tipo="-",
                especie="x",
                situacao="Liberado",
                empresa="PETROBRAS",
                data_entrega="14/09/2026 09:13",
                protocolo="77",
            )
        ],
        source="login",
    )
    store._conn.execute(
        "UPDATE filings SET ticker='PETR' WHERE protocolo='77'")
    store._conn.commit()

    def resolve(ticker: str) -> TickerInfo:
        return TickerInfo(
            ticker=ticker.upper(),
            ccvm="9512",
            issuing_company="PETR",
            company_name="PETROBRAS",
        )

    app = create_app(
        store=store,
        resolve=resolve,
        base_url="http://test",
        mailer=lambda email, url: None,
    )
    return TestClient(app), store


def test_feed_filters_by_entrega_date(tmp_path: Path):
    client, store = _app(tmp_path)
    store.upsert_filings(
        [
            IpeLink(
                url="https://rad/p?numProtocolo=88",
                documento="IPE",
                ccvm="4170",
                data_ref="15/09/2026",
                frm_dt_ref="",
                categoria="Assembleia",
                tipo="AGO",
                especie="Edital",
                situacao="Liberado",
                empresa="VALE",
                data_entrega="15/09/2026 11:00",
                protocolo="88",
            )
        ],
        source="login",
    )
    br = client.get(
        "/api/ipe", params={"data_de": "15/09/2026", "data_ate": "15/09/2026"})
    iso = client.get(
        "/api/ipe", params={"data_de": "2026-09-15", "data_ate": "2026-09-15"})
    assert br.status_code == 200
    assert iso.status_code == 200
    assert {row["protocolo"] for row in br.json()["links"]} == {"88"}
    assert {row["protocolo"] for row in iso.json()["links"]} == {"88"}
    none = client.get(
        "/api/ipe", params={"data_de": "16/09/2026", "data_ate": "16/09/2026"})
    assert none.json()["total"] == 0


def test_feed_filters_by_reference_date_and_entrega_date(tmp_path: Path):
    client, store = _app(tmp_path)
    store.upsert_filings(
        [
            IpeLink(
                url="https://rad/p?numProtocolo=88",
                documento="IPE",
                ccvm="4170",
                data_ref="15/09/2026 08:10",
                frm_dt_ref="",
                categoria="Assembleia",
                tipo="AGO",
                especie="Edital",
                situacao="Liberado",
                empresa="VALE",
                data_entrega="29/05/2026 11:01",
                protocolo="88",
            )
        ],
        source="login",
    )
    by_ref = client.get(
        "/api/ipe", params={"data_ref_de": "2026-09-15", "data_ref_ate": "2026-09-15"})
    by_entrega = client.get(
        "/api/ipe", params={"data_de": "2026-05-29", "data_ate": "2026-05-29"})
    assert by_ref.status_code == 200
    assert by_entrega.status_code == 200
    assert {row["protocolo"] for row in by_ref.json()["links"]} == {"88"}
    assert {row["protocolo"] for row in by_entrega.json()["links"]} == {"88"}


def test_protocolos_lists_all_ids_for_filter(tmp_path: Path):
    client, store = _app(tmp_path)
    for i in range(2, 12):
        store.upsert_filings(
            [
                IpeLink(
                    url=f"https://rad/p?numProtocolo={i}",
                    documento="IPE",
                    ccvm="9512",
                    data_ref="14/09/2026",
                    frm_dt_ref="",
                    categoria="Fato Relevante",
                    tipo="-",
                    especie="x",
                    situacao="Liberado",
                    empresa="PETROBRAS",
                    data_entrega="14/09/2026 09:13",
                    protocolo=str(i),
                )
            ],
            source="login",
        )
    store._conn.execute("UPDATE filings SET ticker='PETR'")
    store._conn.commit()
    paged = client.get("/api/ipe", params={"ticker": "PETR4", "page_size": 5})
    assert paged.json()["total"] == 11
    assert len(paged.json()["links"]) == 5
    ids = client.get("/api/protocolos", params={"ticker": "PETR4"})
    assert ids.status_code == 200
    assert len(ids.json()["ids"]) == 11
    assert set(ids.json()["ids"]) == {"77"} | {str(i) for i in range(2, 12)}


def test_tickers_catalog_lists_known_codes(tmp_path: Path):
    client, store = _app(tmp_path)
    store.upsert_filings(
        [
            IpeLink(
                url="https://rad/p?numProtocolo=88",
                documento="IPE",
                ccvm="4170",
                data_ref="14/09/2026",
                frm_dt_ref="",
                categoria="Assembleia",
                tipo="AGO",
                especie="Edital",
                situacao="Liberado",
                empresa="VALE",
                data_entrega="14/09/2026 11:00",
                protocolo="88",
            )
        ],
        source="login",
    )
    store._conn.execute(
        "UPDATE filings SET ticker='VALE3' WHERE protocolo='88'")
    store._conn.commit()
    res = client.get("/api/tickers")
    assert res.status_code == 200
    codes = {row["ticker"] for row in res.json()["tickers"]}
    assert "PETR4" in codes or "PETR" in codes
    assert "VALE3" in codes
    filtered = client.get("/api/tickers", params={"q": "VALE"})
    assert [row["ticker"] for row in filtered.json()["tickers"]] == ["VALE3"]


def test_public_feed_filters_ticker(tmp_path: Path):
    client, _ = _app(tmp_path)
    res = client.get("/api/ipe", params={"ticker": "PETR4"})
    assert res.status_code == 200
    body = res.json()
    assert body["ccvm_filtro"] == "9512"
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["pages"] == 1
    assert body["links"][0]["empresa"] == "PETROBRAS"


def test_feed_filters_by_company_name(tmp_path: Path):
    client, store = _app(tmp_path)
    store.upsert_filings(
        [
            IpeLink(
                url="https://rad/p?numProtocolo=88",
                documento="IPE",
                ccvm="22012",
                data_ref="14/09/2026",
                frm_dt_ref="",
                categoria="Assembleia",
                tipo="AGDEB",
                especie="Edital",
                situacao="Liberado",
                empresa="MILLS LOCAÇÃO, SERVIÇOS E LOGÍSTICA S.A",
                data_entrega="14/09/2026 10:30",
                protocolo="88",
            )
        ],
        source="login",
    )
    store._conn.execute(
        "UPDATE filings SET ticker='MILS' WHERE protocolo='88'")
    store._conn.commit()
    mills = client.get("/api/ipe", params={"empresa": "mills", "listagem": ""})
    assert mills.status_code == 200
    body = mills.json()
    assert body["total"] == 1
    assert "MILLS" in body["links"][0]["empresa"]
    assembleia = client.get(
        "/api/ipe",
        params={"empresa": "mills", "categoria": "Assembleia", "listagem": ""},
    )
    assert assembleia.json()["total"] == 1
    fato = client.get(
        "/api/ipe",
        params={"empresa": "mills",
                "categoria": "Fato Relevante", "listagem": ""},
    )
    assert fato.json()["total"] == 0


def test_feed_filters_by_tickers(tmp_path: Path):
    client, store = _app(tmp_path)
    store.upsert_filings(
        [
            IpeLink(
                url="https://rad/p?numProtocolo=88",
                documento="IPE",
                ccvm="4170",
                data_ref="14/09/2026",
                frm_dt_ref="",
                categoria="Assembleia",
                tipo="AGO",
                especie="Edital",
                situacao="Liberado",
                empresa="VALE",
                data_entrega="14/09/2026 11:00",
                protocolo="88",
            ),
            IpeLink(
                url="https://rad/p?numProtocolo=99",
                documento="IPE",
                ccvm="50571",
                data_ref="14/09/2026",
                frm_dt_ref="",
                categoria="Fato Relevante",
                tipo="-",
                especie="x",
                situacao="Liberado",
                empresa="JPMORGAN",
                data_entrega="14/09/2026 12:00",
                protocolo="99",
            ),
        ],
        source="login",
    )
    store._conn.execute(
        "UPDATE filings SET ticker='VALE3' WHERE protocolo='88'")
    store._conn.execute(
        "UPDATE filings SET ticker='JPMC34' WHERE protocolo='99'")
    store._conn.commit()
    res = client.get("/api/ipe", params={"tickers": "PETR4,VALE3"})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    assert {row["protocolo"] for row in body["links"]} == {"77", "88"}


def test_favorite_requires_session(tmp_path: Path):
    client, store = _app(tmp_path)
    denied = client.post("/api/favorites", json={"ticker": "PETR4"})
    assert denied.status_code == 401
    user = store.upsert_user("a@b.com")
    store.create_session(user["id"], "sess", "2099-01-01T00:00:00Z")
    client.cookies.set("mesa_session", "sess")
    ok = client.post("/api/favorites", json={"ticker": "PETR4"})
    assert ok.status_code == 200
    listed = client.get("/api/favorites")
    assert listed.json()[0]["ticker"] == "PETR4"


def test_categorias_lists_what_is_in_store(tmp_path: Path):
    client, _ = _app(tmp_path)
    res = client.get("/api/categorias", params={"listagem": ""})
    assert res.status_code == 200
    assert "Fato Relevante" in res.json()["categorias"]


def test_create_account_rejects_bad_email(tmp_path: Path):
    client, _ = _app(tmp_path)
    res = client.post("/api/entrar", json={"email": "nao-e-email"})
    assert res.status_code == 400


def test_entrar_does_not_return_dev_link_by_default(tmp_path: Path):
    client, _ = _app(tmp_path)
    res = client.post("/api/entrar", json={"email": "pessoa@exemplo.com"})
    assert res.status_code == 200
    assert "dev_link" not in res.json()


def test_create_account_returns_dev_link_and_callback_sets_cookie(tmp_path: Path):
    sent = []
    store = Store(tmp_path / "ipe.db")
    app = create_app(
        store=store,
        resolve=lambda t: (_ for _ in ()).throw(Exception("no")),
        mailer=lambda email, url: sent.append((email, url)),
        base_url="http://test",
        expose_magic_link=True,
    )
    client = TestClient(app, follow_redirects=False)
    res = client.post("/api/entrar", json={"email": "pessoa@exemplo.com"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "dev_link" in body
    assert sent[0][0] == "pessoa@exemplo.com"
    token = sent[0][1].split("token=")[-1]
    cb = client.get("/api/entrar/callback", params={"token": token})
    assert cb.status_code in (302, 303)
    assert "mesa_session" in cb.cookies
    me = client.get("/api/me")
    assert me.json()["email"] == "pessoa@exemplo.com"


def test_home_is_html(tmp_path: Path):
    client, _ = _app(tmp_path)
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert "Mesa IPE" in html
    assert "Favoritos" in html
    assert "class=\"chips\"" in html
    assert "class=\"chip\"" in html
    assert "fav-picker" in html
    assert "fav-menu" in html
    assert 'id="busca-fav"' in html
    assert "/api/tickers" in html
    assert "loadTickersFromFeed" in html
    assert 'role="combobox"' in html
    assert "alerts-pop" not in html
    assert "alerts-btn" not in html
    assert 'data-lido="nao"' in html
    assert 'id="lido-n"' in html
    assert "mesa_ipe_favoritos" in html
    assert "<aside" not in html
    assert "/api/ticker" in html
    assert "somente-favoritos" in html
    assert 'aria-pressed' in html
    assert 'qs.set("tickers"' in html
    assert "/api/protocolos" in html
    assert "loadAllIds" in html
    assert "updateLidoBadge([])" not in html
    assert 'id="data_de"' in html
    assert 'id="data_ate"' in html
    assert 'placeholder="DD/MM/AAAA"' in html
    assert 'id="cal-pop"' in html
    assert "data-cal" in html
    assert "toIsoDate" in html
    assert "toBrDate" in html
    assert "formatDateInput" in html
    assert 'type="date"' not in html
    assert "data-read-toggle" in html
    assert "Criar conta" not in html
    assert 'id="login"' not in html


def test_old_login_pages_redirect_home(tmp_path: Path):
    client, _ = _app(tmp_path)
    for path in ("/entrar", "/conta"):
        res = client.get(path, follow_redirects=False)
        assert res.status_code in (302, 303)
        assert res.headers["location"] == "/"


def test_ticker_lookup_accepts_known_ticker(tmp_path: Path):
    client, _ = _app(tmp_path)
    res = client.get("/api/ticker", params={"ticker": "PETR4"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["ticker"] == "PETR4"
    assert body["ccvm"] == "9512"


def test_ticker_lookup_rejects_garbage(tmp_path: Path):
    client, _ = _app(tmp_path)
    for value in ("asdf", "PETROBRAS", "1234", ""):
        res = client.get("/api/ticker", params={"ticker": value})
        assert res.status_code == 400, value


def test_ticker_lookup_unknown_share_is_404(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")

    def resolve(ticker: str) -> TickerInfo:
        raise TickerNotFound(ticker)

    app = create_app(store=store, resolve=resolve, base_url="http://test")
    client = TestClient(app)
    res = client.get("/api/ticker", params={"ticker": "XXXX9"})
    assert res.status_code == 404


def test_ticker_lookup_falls_back_to_filings(tmp_path: Path):
    _, store = _app(tmp_path)

    def resolve(ticker: str) -> TickerInfo:
        raise TickerNotFound(ticker)

    app = create_app(store=store, resolve=resolve, base_url="http://test")
    client = TestClient(app)
    res = client.get("/api/ticker", params={"ticker": "PETR4"})
    assert res.status_code == 200
    assert res.json()["ticker"] == "PETR4"


def test_ticker_lookup_accepts_bdr_with_digit_in_code(tmp_path: Path):
    _, store = _app(tmp_path)
    store.upsert_filings(
        [
            IpeLink(
                url="https://rad/p?numProtocolo=99",
                documento="IPE",
                ccvm="1234",
                data_ref="14/09/2026",
                frm_dt_ref="",
                categoria="Fato Relevante",
                tipo="-",
                especie="x",
                situacao="Liberado",
                empresa="COMCAST CORPORATION",
                data_entrega="14/09/2026 10:00",
                protocolo="99",
            )
        ],
        source="login",
    )
    store._conn.execute(
        "UPDATE filings SET ticker='C1MG34' WHERE protocolo='99'")
    store._conn.commit()

    def resolve(ticker: str) -> TickerInfo:
        raise TickerNotFound(ticker)

    app = create_app(store=store, resolve=resolve, base_url="http://test")
    client = TestClient(app)
    res = client.get("/api/ticker", params={"ticker": "C1MG34"})
    assert res.status_code == 200
    body = res.json()
    assert body["ticker"] == "C1MG34"
    assert body["empresa"] == "COMCAST CORPORATION"
