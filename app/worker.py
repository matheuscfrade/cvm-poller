from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from app.notify import flush_outbox, smtp_send
from app.poller import poll_once
from app.store import Store
from app.timeutil import BRT, now_br

log = logging.getLogger("ipe.worker")

# Polling is suspended between QUIET_START (inclusive) and QUIET_END (exclusive).
# All times are in BRT (America/Sao_Paulo).
_QUIET_START_HOUR = 0   # midnight
_QUIET_END_HOUR   = 5   # 05:00


def _sleep_until_market_open() -> None:
    """If the current BRT time falls inside the quiet window [00:00, 05:00),
    sleep until 05:00 BRT of the same calendar day.

    The first poll after waking up will automatically fetch all data since
    00:00 because ``_window()`` in poller.py resets the cursor to "00:00"
    whenever the stored cursor date differs from today.
    """
    now = now_br()
    if _QUIET_START_HOUR <= now.hour < _QUIET_END_HOUR:
        wake = now.replace(hour=_QUIET_END_HOUR, minute=0, second=0, microsecond=0)
        delta = (wake - now).total_seconds()
        log.info(
            "fora do horário de coleta (%02d:%02d BRT). "
            "próxima coleta às %02d:00. dormindo %.0f s.",
            now.hour, now.minute, _QUIET_END_HOUR, delta,
        )
        time.sleep(delta)


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
        _sleep_until_market_open()
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
