from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.timeutil import official_date
from cvm_poller.parse import IpeLink

_PROTO = re.compile(r"numProtocolo=(\d+)", re.I)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_BR_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})")


def protocolo_of(link: IpeLink) -> str:
    if link.protocolo.strip():
        return link.protocolo.strip()
    match = _PROTO.search(link.url or "")
    if match:
        return match.group(1)
    return link.url


def _date_key(value: str) -> str:
    text = (value or "").strip()
    iso = _ISO_DATE.match(text)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    br = _BR_DATE.match(text)
    return f"{br.group(3)}-{br.group(2)}-{br.group(1)}" if br else ""


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    ccvm TEXT PRIMARY KEY,
    tickers TEXT NOT NULL DEFAULT '[]',
    nome TEXT NOT NULL DEFAULT '',
    atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS filings (
    protocolo TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    documento TEXT NOT NULL DEFAULT 'IPE',
    ccvm TEXT NOT NULL DEFAULT '',
    ticker TEXT NOT NULL DEFAULT '',
    empresa TEXT NOT NULL DEFAULT '',
    categoria TEXT NOT NULL DEFAULT '',
    tipo TEXT NOT NULL DEFAULT '',
    especie TEXT NOT NULL DEFAULT '',
    situacao TEXT NOT NULL DEFAULT '',
    data_ref TEXT NOT NULL DEFAULT '',
    data_entrega TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'login',
    first_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_filings_entrega ON filings(data_entrega DESC);
CREATE INDEX IF NOT EXISTS idx_filings_ccvm ON filings(ccvm, data_entrega DESC);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS magic_links (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS favorites (
    user_id TEXT NOT NULL,
    ccvm TEXT NOT NULL,
    ticker TEXT NOT NULL DEFAULT '',
    categorias TEXT NOT NULL DEFAULT '[]',
    instantaneo INTEGER NOT NULL DEFAULT 1,
    email INTEGER NOT NULL DEFAULT 1,
    telegram INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, ccvm)
);
CREATE TABLE IF NOT EXISTS telegram (
    user_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    vinculado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY,
    filing_protocolo TEXT NOT NULL,
    user_id TEXT NOT NULL,
    canal TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status);
CREATE TABLE IF NOT EXISTS poll_runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    source TEXT NOT NULL,
    novos INTEGER NOT NULL DEFAULT 0,
    erro TEXT NOT NULL DEFAULT '',
    cursor TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def upsert_companies(self, rows: list[dict[str, Any]]) -> int:
        now = _now()
        count = 0
        for row in rows:
            ccvm = str(row.get("codeCVM") or "").lstrip("0") or "0"
            tickers = _tickers_from_b3(row)
            nome = str(row.get("companyName") or row.get("tradingName") or "")
            self._conn.execute(
                """INSERT INTO companies (ccvm, tickers, nome, atualizado_em)
                   VALUES (?,?,?,?)
                   ON CONFLICT(ccvm) DO UPDATE SET
                     tickers=excluded.tickers,
                     nome=excluded.nome,
                     atualizado_em=excluded.atualizado_em""",
                (ccvm, json.dumps(tickers), nome, now),
            )
            count += 1
        self._conn.commit()
        return count

    def company_for_ccvm(self, ccvm: str) -> dict[str, Any] | None:
        key = (ccvm or "").lstrip("0") or ccvm
        row = self._conn.execute(
            "SELECT * FROM companies WHERE ccvm = ?", (key,)
        ).fetchone()
        return dict(row) if row else None

    def list_tickers(self, query: str = "", limit: int = 5000) -> list[dict[str, Any]]:
        wanted = query.strip().upper()
        wanted_prefix = re.sub(r"\d+$", "", wanted) or wanted
        found: dict[str, str] = {}
        has_docs: set[str] = set()
        for row in self._conn.execute(
            "SELECT ticker, empresa FROM filings WHERE ticker != ''"
        ):
            code = str(row["ticker"] or "").strip().upper()
            if not code:
                continue
            found.setdefault(code, str(row["empresa"] or ""))
            has_docs.add(code)
        for row in self._conn.execute("SELECT tickers, nome FROM companies"):
            nome = str(row["nome"] or "")
            try:
                codes = json.loads(row["tickers"] or "[]")
            except json.JSONDecodeError:
                codes = []
            if isinstance(codes, str):
                codes = [codes]
            elif not isinstance(codes, list):
                codes = []
            for item in codes:
                code = str(item or "").strip().upper()
                if code:
                    found.setdefault(code, nome)
        items = []
        for code, nome in found.items():
            if wanted and not _ticker_query_match(code, nome, wanted, wanted_prefix):
                continue
            items.append({
                "ticker": code,
                "empresa": nome,
                "has_docs": code in has_docs,
            })
        items.sort(key=lambda item: (
            0 if item["has_docs"] else 1, item["ticker"]))
        return items[: max(1, min(limit, 10000))]

    def find_known_ticker(self, ticker: str) -> dict[str, Any] | None:
        raw = ticker.strip().upper()
        if not raw:
            return None
        prefix = re.sub(r"\d+$", "", raw) or raw
        codes = (raw, prefix) if len(prefix) >= 4 and prefix != raw else (raw,)
        placeholders = ",".join("?" * len(codes))
        row = self._conn.execute(
            f"""SELECT ticker, ccvm, empresa FROM filings
                WHERE upper(ticker) IN ({placeholders})
                LIMIT 1""",
            codes,
        ).fetchone()
        if row:
            return {
                "ticker": raw,
                "ccvm": row["ccvm"] or "",
                "empresa": row["empresa"] or "",
            }
        like = f"%{raw}%"
        candidates = self._conn.execute(
            "SELECT ccvm, tickers, nome FROM companies WHERE tickers LIKE ?",
            (like,),
        ).fetchall()
        wanted = {raw}
        if len(prefix) >= 4:
            wanted.add(prefix)
        for company in candidates:
            try:
                stored = {str(item).upper()
                          for item in json.loads(company["tickers"] or "[]")}
            except json.JSONDecodeError:
                continue
            if stored & wanted:
                return {
                    "ticker": raw,
                    "ccvm": company["ccvm"] or "",
                    "empresa": company["nome"] or "",
                }
        return None

    def upsert_filings(self, links: list[IpeLink], source: str, ticker: str = "") -> int:
        now = _now()
        inserted = 0
        for link in links:
            proto = protocolo_of(link)
            ccvm = (link.ccvm or "").lstrip("0") or link.ccvm
            company = self.company_for_ccvm(ccvm)
            tickers = json.loads(company["tickers"]) if company else []
            resolved_ticker = ticker or (tickers[0] if tickers else "")
            empresa = link.empresa or (company["nome"] if company else "")
            cur = self._conn.execute(
                """INSERT OR IGNORE INTO filings (
                    protocolo, url, documento, ccvm, ticker, empresa, categoria,
                    tipo, especie, situacao, data_ref, data_entrega, source, first_seen
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    proto,
                    link.url,
                    link.documento,
                    ccvm,
                    resolved_ticker,
                    empresa,
                    link.categoria,
                    link.tipo,
                    link.especie,
                    link.situacao,
                    link.data_ref,
                    official_date(link.data_entrega),
                    source,
                    now,
                ),
            )
            inserted += cur.rowcount
        self._conn.commit()
        self.enrich_missing()
        return inserted

    def enrich_missing(self, fetch_detail: Any = None) -> int:
        self._conn.execute(
            "UPDATE filings SET data_entrega = '' WHERE data_entrega = data_ref"
        )
        updated = 0
        rows = self._conn.execute(
            "SELECT protocolo, ccvm FROM filings").fetchall()
        seen: set[str] = set()
        for row in rows:
            company = self.company_for_ccvm(row["ccvm"])
            if (not company or not json.loads(company.get("tickers") or "[]")) and fetch_detail:
                if row["ccvm"] not in seen:
                    seen.add(row["ccvm"])
                    detail = fetch_detail(row["ccvm"])
                    if detail:
                        self.upsert_companies([detail])
                        company = self.company_for_ccvm(row["ccvm"])
            if not company:
                continue
            tickers = json.loads(company["tickers"] or "[]")
            self._conn.execute(
                """UPDATE filings SET ticker = CASE WHEN ticker = '' THEN ? ELSE ticker END,
                     empresa = CASE WHEN length(?) > length(empresa) THEN ? ELSE empresa END
                   WHERE protocolo = ?""",
                (
                    tickers[0] if tickers else "",
                    company["nome"],
                    company["nome"],
                    row["protocolo"],
                ),
            )
            updated += 1
        self._conn.commit()
        return updated

    def apply_entregas(self, entregas: dict[str, str]) -> int:
        changed = 0
        for proto, when in entregas.items():
            day = official_date(when)
            if not proto or not day:
                continue
            cur = self._conn.execute(
                "UPDATE filings SET data_entrega = ? WHERE protocolo = ?",
                (day, proto),
            )
            changed += cur.rowcount
        self._conn.commit()
        return changed

    def apply_nomes(self, nomes: dict[str, str]) -> int:
        changed = 0
        for proto, nome in nomes.items():
            nome = (nome or "").strip()
            if not proto or not nome:
                continue
            cur = self._conn.execute(
                """UPDATE filings SET empresa = ?
                   WHERE protocolo = ? AND (empresa = '' OR length(?) > length(empresa))""",
                (nome, proto, nome),
            )
            changed += cur.rowcount
        self._conn.commit()
        return changed

    def protocolos_nome_curto(self, max_len: int = 24) -> list[str]:
        rows = self._conn.execute(
            "SELECT protocolo FROM filings WHERE empresa = '' OR length(empresa) <= ?",
            (max_len,),
        ).fetchall()
        return [row["protocolo"] for row in rows]

    def protocolos_sem_entrega(self) -> list[str]:
        rows = self._conn.execute(
            """SELECT protocolo FROM filings
               WHERE data_entrega = '' OR data_entrega = data_ref
                  OR data_entrega NOT LIKE '%:%'"""
        ).fetchall()
        return [row["protocolo"] for row in rows]

    def list_filings(
        self,
        ccvm: str = "",
        categoria: str = "",
        listagem: str = "",
        empresa: str = "",
        ticker: str = "",
        data_de: str = "",
        data_ate: str = "",
        data_ref_de: str = "",
        data_ref_ate: str = "",
        tickers: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where, params = self._filings_where(
            ccvm, categoria, listagem, empresa, ticker, data_de, data_ate,
            data_ref_de=data_ref_de, data_ref_ate=data_ref_ate,
            tickers=tickers,
        )
        sql = (
            f"SELECT * FROM filings WHERE {where} "
            "ORDER BY data_entrega DESC, first_seen DESC LIMIT ? OFFSET ?"
        )
        rows = self._conn.execute(
            sql, [*params, limit, max(0, offset)]).fetchall()
        return [dict(row) for row in rows]

    def list_protocolos(
        self,
        ccvm: str = "",
        categoria: str = "",
        listagem: str = "",
        empresa: str = "",
        ticker: str = "",
        data_de: str = "",
        data_ate: str = "",
        data_ref_de: str = "",
        data_ref_ate: str = "",
        tickers: list[str] | None = None,
    ) -> list[str]:
        where, params = self._filings_where(
            ccvm, categoria, listagem, empresa, ticker, data_de, data_ate,
            data_ref_de=data_ref_de, data_ref_ate=data_ref_ate,
            tickers=tickers,
        )
        rows = self._conn.execute(
            f"SELECT protocolo FROM filings WHERE {where}", params
        ).fetchall()
        return [str(row["protocolo"]) for row in rows if row["protocolo"]]

    def list_categorias(
        self,
        ccvm: str = "",
        listagem: str = "",
        empresa: str = "",
    ) -> list[str]:
        where, params = self._filings_where(ccvm, "", listagem, empresa)
        rows = self._conn.execute(
            f"""SELECT DISTINCT categoria FROM filings
                WHERE {where} AND categoria != ''
                ORDER BY categoria COLLATE NOCASE""",
            params,
        ).fetchall()
        return [row["categoria"] for row in rows]

    def count_filings(
        self,
        ccvm: str = "",
        categoria: str = "",
        listagem: str = "",
        empresa: str = "",
        ticker: str = "",
        data_de: str = "",
        data_ate: str = "",
        data_ref_de: str = "",
        data_ref_ate: str = "",
        tickers: list[str] | None = None,
    ) -> int:
        where, params = self._filings_where(
            ccvm, categoria, listagem, empresa, ticker, data_de, data_ate,
            data_ref_de=data_ref_de, data_ref_ate=data_ref_ate,
            tickers=tickers,
        )
        row = self._conn.execute(
            f"SELECT count(*) AS c FROM filings WHERE {where}", params
        ).fetchone()
        return int(row["c"] if row else 0)

    def _filings_where(
        self,
        ccvm: str,
        categoria: str,
        listagem: str,
        empresa: str = "",
        ticker: str = "",
        data_de: str = "",
        data_ate: str = "",
        data_ref_de: str = "",
        data_ref_ate: str = "",
        tickers: list[str] | None = None,
    ) -> tuple[str, list[Any]]:
        sql = "1=1"
        params: list[Any] = []
        if ccvm:
            sql += " AND ccvm = ?"
            params.append(ccvm.lstrip("0") or ccvm)
        if ticker.strip():
            sql += " AND " + _ticker_clause(ticker, params)
        extra = [_ticker_clause(item, params)
                 for item in (tickers or []) if str(item).strip()]
        if extra:
            sql += " AND (" + " OR ".join(extra) + ")"
        if categoria:
            sql += " AND categoria LIKE ? COLLATE NOCASE"
            params.append(f"%{categoria.strip()}%")
        if empresa.strip():
            sql += " AND empresa LIKE ? COLLATE NOCASE"
            params.append(f"%{empresa.strip()}%")

        entrega_expr = "(substr(data_entrega, 7, 4) || '-' || substr(data_entrega, 4, 2) || '-' || substr(data_entrega, 1, 2))"
        ref_expr = "(substr(data_ref, 7, 4) || '-' || substr(data_ref, 4, 2) || '-' || substr(data_ref, 1, 2))"

        start = _date_key(data_de)
        end = _date_key(data_ate)
        if start:
            sql += f" AND {entrega_expr} >= ?"
            params.append(start)
        if end:
            sql += f" AND {entrega_expr} <= ?"
            params.append(end)

        ref_start = _date_key(data_ref_de)
        ref_end = _date_key(data_ref_ate)
        if ref_start:
            sql += f" AND {ref_expr} >= ?"
            params.append(ref_start)
        if ref_end:
            sql += f" AND {ref_expr} <= ?"
            params.append(ref_end)

        if listagem in ("", "todas"):
            pass
        elif listagem == "b3":
            sql += " AND ticker != ''"
        elif listagem == "acoes":
            sql += (
                " AND ticker != ''"
                " AND ticker NOT LIKE '%32'"
                " AND ticker NOT LIKE '%33'"
                " AND ticker NOT LIKE '%34'"
                " AND ticker NOT LIKE '%35'"
                " AND ticker NOT LIKE '%39'"
            )
        return sql, params

    def delete_user(self, user_id: str) -> None:
        self._conn.execute(
            "DELETE FROM favorites WHERE user_id = ?", (user_id,))
        self._conn.execute(
            "DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self._conn.execute(
            "DELETE FROM magic_links WHERE user_id = ?", (user_id,))
        self._conn.execute(
            "DELETE FROM telegram WHERE user_id = ?", (user_id,))
        self._conn.execute("DELETE FROM outbox WHERE user_id = ?", (user_id,))
        self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self._conn.commit()

    def upsert_user(self, email: str) -> dict[str, Any]:
        email = email.strip().lower()
        now = _now()
        existing = self._conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        if existing:
            return dict(existing)
        user_id = str(uuid4())
        self._conn.execute(
            "INSERT INTO users (id, email, created_at) VALUES (?,?,?)",
            (user_id, email, now),
        )
        self._conn.commit()
        return {"id": user_id, "email": email, "created_at": now, "last_login": None}

    def add_favorite(self, user_id: str, ccvm: str, ticker: str = "") -> None:
        self._conn.execute(
            """INSERT INTO favorites (user_id, ccvm, ticker)
               VALUES (?,?,?)
               ON CONFLICT(user_id, ccvm) DO UPDATE SET ticker=excluded.ticker""",
            (user_id, ccvm.lstrip("0") or ccvm, ticker.upper()),
        )
        self._conn.commit()

    def remove_favorite(self, user_id: str, ccvm: str) -> None:
        self._conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND ccvm = ?",
            (user_id, ccvm.lstrip("0") or ccvm),
        )
        self._conn.commit()

    def list_favorites(self, user_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM favorites WHERE user_id = ? ORDER BY ticker",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def enqueue_alerts_for_new(self, links: list[IpeLink]) -> int:
        queued = 0
        now = _now()
        for link in links:
            proto = protocolo_of(link)
            ccvm = link.ccvm.lstrip("0") or link.ccvm
            favs = self._conn.execute(
                "SELECT * FROM favorites WHERE ccvm = ?", (ccvm,)
            ).fetchall()
            for fav in favs:
                cats = json.loads(fav["categorias"] or "[]")
                if cats and link.categoria not in cats:
                    continue
                if fav["email"]:
                    queued += self._enqueue(proto,
                                            fav["user_id"], "email", link, now)
                if fav["telegram"]:
                    queued += self._enqueue(proto,
                                            fav["user_id"], "telegram", link, now)
        self._conn.commit()
        return queued

    def pending_outbox(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM outbox WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_outbox(self, item_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE outbox SET status = ?, attempts = attempts + 1 WHERE id = ?",
            (status, item_id),
        )
        self._conn.commit()

    def record_poll(
        self,
        source: str,
        novos: int,
        erro: str = "",
        cursor: str = "",
        started_at: str | None = None,
    ) -> None:
        now = _now()
        self._conn.execute(
            """INSERT INTO poll_runs (id, started_at, finished_at, source, novos, erro, cursor)
               VALUES (?,?,?,?,?,?,?)""",
            (str(uuid4()), started_at or now, now, source, novos, erro, cursor),
        )
        self.set_meta("last_cursor", cursor)
        self.set_meta("last_poll_at", now)
        self.set_meta("last_poll_error", erro)
        self.set_meta("last_poll_source", source)
        self._conn.commit()

    def last_status(self) -> dict[str, str]:
        keys = ("last_cursor", "last_poll_at",
                "last_poll_error", "last_poll_source")
        return {key: self.get_meta(key) for key in keys}

    def get_meta(self, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def create_session(self, user_id: str, token: str, expires_at: str) -> None:
        self._conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
            (token, user_id, expires_at),
        )
        self._conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (_now(), user_id),
        )
        self._conn.commit()

    def user_by_session(self, token: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """SELECT users.* FROM sessions
               JOIN users ON users.id = sessions.user_id
               WHERE sessions.token = ? AND sessions.expires_at > ?""",
            (token, _now()),
        ).fetchone()
        return dict(row) if row else None

    def save_magic_link(self, token_hash: str, user_id: str, expires_at: str) -> None:
        self._conn.execute(
            "INSERT INTO magic_links (token_hash, user_id, expires_at) VALUES (?,?,?)",
            (token_hash, user_id, expires_at),
        )
        self._conn.commit()

    def consume_magic_link(self, token_hash: str) -> str | None:
        row = self._conn.execute(
            "SELECT user_id FROM magic_links WHERE token_hash = ? AND expires_at > ?",
            (token_hash, _now()),
        ).fetchone()
        if not row:
            return None
        self._conn.execute(
            "DELETE FROM magic_links WHERE token_hash = ?", (token_hash,))
        self._conn.commit()
        return row["user_id"]

    def link_telegram(self, user_id: str, chat_id: str) -> None:
        self._conn.execute(
            """INSERT INTO telegram (user_id, chat_id, vinculado_em)
               VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id""",
            (user_id, chat_id, _now()),
        )
        self._conn.commit()

    def _enqueue(self, proto: str, user_id: str, canal: str, link: IpeLink, now: str) -> int:
        exists = self._conn.execute(
            """SELECT 1 FROM outbox WHERE filing_protocolo = ? AND user_id = ? AND canal = ?""",
            (proto, user_id, canal),
        ).fetchone()
        if exists:
            return 0
        payload = json.dumps(link.to_dict(), ensure_ascii=False)
        self._conn.execute(
            """INSERT INTO outbox (id, filing_protocolo, user_id, canal, payload, created_at)
               VALUES (?,?,?,?,?,?)""",
            (str(uuid4()), proto, user_id, canal, payload, now),
        )
        return 1


def _ticker_clause(ticker: str, params: list[Any]) -> str:
    raw = ticker.strip().upper()
    prefix = re.sub(r"\d+$", "", raw) or raw
    params.extend([raw, prefix, prefix + "%"])
    return "(upper(ticker) = ? OR upper(ticker) = ? OR upper(ticker) LIKE ?)"


def _ticker_query_match(code: str, nome: str, wanted: str, wanted_prefix: str) -> bool:
    if wanted in code or wanted in (nome or "").upper():
        return True
    prefix = re.sub(r"\d+$", "", code) or code
    if wanted_prefix and len(wanted_prefix) >= 3 and prefix.startswith(wanted_prefix):
        return True
    if len(prefix) >= 4 and wanted.startswith(prefix):
        return True
    return False


def _tickers_from_b3(row: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for item in row.get("otherCodes") or []:
        if isinstance(item, dict) and item.get("code"):
            codes.append(str(item.get("code") or "").strip().upper())
        elif isinstance(item, str) and item.strip():
            codes.append(item.strip().upper())
    issuing = str(row.get("issuingCompany") or "").strip().upper()
    if issuing and issuing not in codes:
        codes.append(issuing)
    unique: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code and code not in seen:
            seen.add(code)
            unique.append(code)
    return unique


def _ticker_from_b3(row: dict[str, Any]) -> str:
    codes = _tickers_from_b3(row)
    return codes[0] if codes else ""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
