from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from app.notify import flush_outbox, smtp_send
from app.poller import poll_once
from app.store import Store

log = logging.getLogger("ipe.worker")


def _store() -> Store:
    return Store(Path(os.environ.get("DATABASE_PATH", "data/ipe.db")))


def _mailer():
    host = os.environ.get("SMTP_HOST", "")
    if not host:
        return None

    def send(to: str, subject: str, body: str) -> None:
        smtp_send(
            host=host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ.get("SMTP_USER", ""),
            password=os.environ.get("SMTP_PASSWORD", ""),
            from_addr=os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "")),
            to=to,
            subject=subject,
            body=body,
        )

    return send


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    store = _store()
    login = os.environ.get("CVM_LOGIN", "").strip()
    senha = os.environ.get("CVM_SENHA", "").strip()
    if not login or not senha:
        raise SystemExit("CVM_LOGIN e CVM_SENHA são obrigatórios no worker")
    interval = max(60, int(os.environ.get("POLL_INTERVAL_SECONDS", "120")))
    mail = _mailer()
    while True:
        try:
            result = poll_once(store, login=login, senha=senha)
            log.info("poll %s novos=%s %s", result.source, result.novos, result.erro)
            if mail:
                flush_outbox(store, send_email=mail)
        except Exception:
            log.exception("ciclo do worker falhou")
        time.sleep(interval)


if __name__ == "__main__":
    main()
