from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.auth import complete_login, hash_token, request_login
from app.store import Store


def test_magic_link_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    sent = []

    def mailer(email, url):
        sent.append((email, url))

    raw = request_login(
        store,
        "Ana@Example.com",
        mailer=mailer,
        base_url="http://localhost:8765",
    )
    assert sent[0][0] == "ana@example.com"
    assert raw in sent[0][1]
    session = complete_login(store, raw)
    user = store.user_by_session(session)
    assert user is not None
    assert user["email"] == "ana@example.com"
    assert complete_login(store, raw) is None


def test_expired_magic_link_rejected(tmp_path: Path):
    store = Store(tmp_path / "ipe.db")
    user = store.upsert_user("a@b.com")
    token = "abc"
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    store.save_magic_link(hash_token(token), user["id"], expired)
    assert complete_login(store, token) is None
