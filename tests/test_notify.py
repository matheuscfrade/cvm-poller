from pathlib import Path

from app.notify import flush_outbox
from app.store import Store
from cvm_poller.parse import IpeLink


def test_flush_sends_email_and_marks_sent(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    user = store.upsert_user("a@b.com")
    store.add_favorite(user["id"], ccvm="9512", ticker="PETR4")
    link = IpeLink(
        url="https://rad/x?numProtocolo=9",
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
        protocolo="9",
    )
    store.upsert_filings([link], source="login")
    store.enqueue_alerts_for_new([link])
    emails = []
    sent = flush_outbox(
        store,
        send_email=lambda to, subject, body: emails.append((to, subject, body)),
        send_telegram=lambda chat, text: None,
    )
    assert sent == 1
    assert emails[0][0] == "a@b.com"
    assert "PETROBRAS" in emails[0][2]
    assert store.pending_outbox() == []
