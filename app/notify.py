from __future__ import annotations

import json
import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any

from app.store import Store

log = logging.getLogger("ipe.notify")

SendEmail = Callable[[str, str, str], None]
SendTelegram = Callable[[str, str], None]


def flush_outbox(
    store: Store,
    send_email: SendEmail | None = None,
    send_telegram: SendTelegram | None = None,
    max_attempts: int = 5,
) -> int:
    sent = 0
    for item in store.pending_outbox():
        payload = json.loads(item["payload"])
        user = store._conn.execute(
            "SELECT * FROM users WHERE id = ?", (item["user_id"],)
        ).fetchone()
        if not user:
            store.mark_outbox(item["id"], "error")
            continue
        try:
            if item["canal"] == "email":
                if send_email is None:
                    continue
                send_email(user["email"], _subject(payload), _email_body(payload))
            elif item["canal"] == "telegram":
                if send_telegram is None:
                    continue
                row = store._conn.execute(
                    "SELECT chat_id FROM telegram WHERE user_id = ?",
                    (item["user_id"],),
                ).fetchone()
                if not row:
                    store.mark_outbox(item["id"], "error")
                    continue
                send_telegram(row["chat_id"], _telegram_body(payload))
            else:
                store.mark_outbox(item["id"], "error")
                continue
        except Exception:
            log.exception("notify failed %s", item["id"])
            if item["attempts"] + 1 >= max_attempts:
                store.mark_outbox(item["id"], "error")
            else:
                store.mark_outbox(item["id"], "pending")
            continue
        store.mark_outbox(item["id"], "sent")
        sent += 1
    return sent


def smtp_send(
    host: str,
    port: int,
    username: str,
    password: str,
    from_addr: str,
    to: str,
    subject: str,
    body: str,
    use_tls: bool = True,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(msg)


def _subject(payload: dict[str, Any]) -> str:
    empresa = payload.get("empresa") or payload.get("ccvm") or "IPE"
    cat = payload.get("categoria") or "documento"
    return f"{empresa}: {cat}"


def _email_body(payload: dict[str, Any]) -> str:
    return (
        f"{payload.get('empresa') or ''} ({payload.get('ccvm')})\n"
        f"{payload.get('categoria')} — {payload.get('especie')}\n"
        f"Entrega: {payload.get('data_entrega') or payload.get('data_ref')}\n\n"
        f"Abrir PDF:\n{payload.get('url')}\n"
    )


def _telegram_body(payload: dict[str, Any]) -> str:
    return _email_body(payload)
