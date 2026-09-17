from __future__ import annotations

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

_DATE = re.compile(r"(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2})(?::\d{2})?)?")

BRT = ZoneInfo("America/Sao_Paulo")


def now_br() -> datetime:
    return datetime.now(BRT)


def today_br() -> date:
    return now_br().date()


def format_br(iso_utc: str) -> str:
    if not iso_utc:
        return ""
    text = iso_utc.strip()
    if text.endswith("Z"):
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    else:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(BRT).strftime("%d/%m/%Y %H:%M")


def official_date(value: str) -> str:
    match = _DATE.search(value or "")
    if not match:
        return ""
    day, hour = match.group(1), match.group(2)
    if hour:
        return f"{day} {hour}"
    return day
