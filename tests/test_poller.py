from datetime import date
from pathlib import Path

from app.poller import poll_once
from app.store import Store
from cvm_poller.parse import DownloadMultiploResult, IpeLink

EMPTY_PUBLIC = DownloadMultiploResult(
    data_solicitada="",
    documento="IPE",
    data_consulta="",
    links=[],
    source="public",
)


def _result(*ccvms: str, data: str = "14/09/2026") -> DownloadMultiploResult:
    links = [
        IpeLink(
            url=f"https://rad.example/{ccvm}?numProtocolo={i}",
            documento="IPE",
            ccvm=ccvm,
            data_ref=data,
            frm_dt_ref=data,
            categoria="Fato Relevante",
            tipo="-",
            especie="x",
            situacao="Liberado",
            empresa="CIA",
            data_entrega=f"{data} 09:13",
            protocolo=str(i),
        )
        for i, ccvm in enumerate(ccvms, start=1)
    ]
    return DownloadMultiploResult(
        data_solicitada=f"{data} 00:00",
        documento="IPE",
        data_consulta=f"{data} 10:28",
        links=links,
        source="login",
    )


def test_poll_is_idempotent(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    fake = lambda **kwargs: _result("9512", "4170")
    first = poll_once(
        store,
        login="u",
        senha="s",
        fetch_login=fake,
        fetch_public=lambda **k: EMPTY_PUBLIC,
        load_companies=lambda: [],
        fetch_detail=lambda ccvm: None,
    )
    second = poll_once(
        store,
        login="u",
        senha="s",
        fetch_login=fake,
        fetch_public=lambda **k: EMPTY_PUBLIC,
        load_companies=lambda: [],
        fetch_detail=lambda ccvm: None,
    )
    assert first.novos == 2
    assert second.novos == 0
    assert store.last_status()["last_cursor"] == "14/09/2026 10:28"


def test_poll_queues_favorite_alerts(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    user = store.upsert_user("a@b.com")
    store.add_favorite(user["id"], ccvm="9512", ticker="PETR4")
    poll_once(
        store,
        login="u",
        senha="s",
        fetch_login=lambda **k: _result("9512", "4170"),
        fetch_public=lambda **k: EMPTY_PUBLIC,
        load_companies=lambda: [],
        fetch_detail=lambda ccvm: None,
    )
    pending = store.pending_outbox()
    assert len(pending) == 1
    assert pending[0]["filing_protocolo"] == "1"


def test_poll_supports_manual_date_override(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    result = poll_once(
        store,
        login="u",
        senha="s",
        fetch_login=lambda **k: _result("9512", data="15/09/2026"),
        fetch_public=lambda **k: EMPTY_PUBLIC,
        load_companies=lambda: [],
        fetch_detail=lambda ccvm: None,
        today=date(2026, 9, 17),
        data_override="15/09/2026",
    )
    assert result.novos == 1
    assert store.last_status()["last_cursor"].startswith("15/09/2026")


def test_manual_date_override_discards_known_delivery_from_another_day(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    result = poll_once(
        store,
        login="u",
        senha="s",
        fetch_login=lambda **k: DownloadMultiploResult(
            data_solicitada="15/09/2026 00:00",
            documento="IPE",
            data_consulta="15/09/2026 10:28",
            links=[
                IpeLink(
                    url="https://rad.example/p?numProtocolo=89",
                    documento="IPE",
                    ccvm="9512",
                    data_ref="15/09/2026",
                    frm_dt_ref="15/09/2026",
                    categoria="Assembleia",
                    tipo="AGO",
                    especie="Edital",
                    situacao="Liberado",
                    empresa="CIA",
                    data_entrega="29/05/2026 11:01",
                    protocolo="89",
                )
            ],
            source="login",
        ),
        fetch_public=lambda **k: EMPTY_PUBLIC,
        load_companies=lambda: [],
        fetch_detail=lambda ccvm: None,
        data_override="15/09/2026",
    )
    assert result.novos == 0
    assert store.list_filings() == []


def test_poll_uses_rad_envio_date_not_data_ref(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    login_links = DownloadMultiploResult(
        data_solicitada="14/09/2026 00:00",
        documento="IPE",
        data_consulta="14/09/2026 10:28",
        links=[
            IpeLink(
                url="https://rad.example/p?numProtocolo=77",
                documento="IPE",
                ccvm="9512",
                data_ref="14/10/2026 16:00:00",
                frm_dt_ref="",
                categoria="Assembleia",
                tipo="AGDEB",
                especie="Edital",
                situacao="Liberado",
                empresa="",
                data_entrega="",
                protocolo="77",
            )
        ],
        source="login",
    )
    public_links = DownloadMultiploResult(
        data_solicitada="14/09/2026",
        documento="IPE",
        data_consulta="",
        links=[
            IpeLink(
                url="https://rad.example/p?numProtocolo=77",
                documento="IPE",
                ccvm="9512",
                data_ref="14/10/2026 16:00:00",
                frm_dt_ref="",
                categoria="Assembleia",
                tipo="AGDEB",
                especie="Edital",
                situacao="Ativo",
                empresa="PETROBRAS",
                data_entrega="14/09/2026 07:27",
                protocolo="77",
            )
        ],
        source="public",
    )
    poll_once(
        store,
        login="u",
        senha="s",
        fetch_login=lambda **k: login_links,
        fetch_public=lambda **k: public_links,
        load_companies=lambda: [],
        fetch_detail=lambda ccvm: None,
    )
    row = store.list_filings()[0]
    assert row["data_entrega"] == "14/09/2026 07:27"
    assert row["data_ref"] == "14/10/2026 16:00:00"
    assert row["empresa"] == "PETROBRAS"


def test_poll_fills_envio_from_header_when_public_list_misses(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    login_links = DownloadMultiploResult(
        data_solicitada="14/09/2026 00:00",
        documento="IPE",
        data_consulta="14/09/2026 10:28",
        links=[
            IpeLink(
                url="https://rad.example/p?numProtocolo=88",
                documento="IPE",
                ccvm="9512",
                data_ref="31/12/2026 00:00:00",
                frm_dt_ref="",
                categoria="Comunicado ao Mercado",
                tipo="-",
                especie="x",
                situacao="Liberado",
                empresa="",
                data_entrega="",
                protocolo="88",
            )
        ],
        source="login",
    )
    poll_once(
        store,
        login="u",
        senha="s",
        fetch_login=lambda **k: login_links,
        fetch_public=lambda **k: EMPTY_PUBLIC,
        fetch_envio=lambda proto: "14/09/2026 07:11:35" if proto == "88" else None,
        load_companies=lambda: [],
        fetch_detail=lambda ccvm: None,
    )
    assert store.list_filings()[0]["data_entrega"] == "14/09/2026 07:11"
