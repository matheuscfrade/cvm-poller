from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.store import Store

Mailer = Callable[[str, str], None]


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def request_login(
    store: Store,
    email: str,
    mailer: Mailer,
    base_url: str,
    ttl_minutes: int = 30,
) -> str:
    user = store.upsert_user(email)
    raw = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    store.save_magic_link(
        hash_token(raw),
        user["id"],
        expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    url = f"{base_url.rstrip('/')}/api/entrar/callback?token={raw}"
    mailer(user["email"], url)
    return raw


def complete_login(store: Store, raw_token: str, session_days: int = 30) -> str | None:
    user_id = store.consume_magic_link(hash_token(raw_token))
    if not user_id:
        return None
    session = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=session_days)
    store.create_session(user_id, session, expires.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return session
