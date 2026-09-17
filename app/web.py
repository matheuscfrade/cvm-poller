from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import re

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from app.auth import complete_login, request_login
from app.notify import smtp_send
from app.store import Store
from app.timeutil import format_br
from cvm_poller.ticker import TickerNotFound, looks_like_ticker, resolve_ticker

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

STATIC = Path(__file__).parent / "static"
ResolveFn = Callable[[str], Any]
MailerFn = Callable[[str, str], None]

COOKIE = "mesa_session"


class FavoriteIn(BaseModel):
    ticker: str


class LoginIn(BaseModel):
    email: str


def create_app(
    store: Store | None = None,
    resolve: ResolveFn | None = None,
    base_url: str = "",
    mailer: MailerFn | None = None,
    expose_magic_link: bool = False,
) -> FastAPI:
    db = store or Store(Path(os.environ.get("DATABASE_PATH", "data/ipe.db")))
    resolver = resolve or resolve_ticker
    public_url = base_url or os.environ.get(
        "APP_BASE_URL", "http://127.0.0.1:8765")
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    show_link = bool(expose_magic_link)

    def send_magic(email: str, url: str) -> None:
        if mailer:
            mailer(email, url)
            return
        if smtp_host:
            smtp_send(
                host=smtp_host,
                port=int(os.environ.get("SMTP_PORT", "587")),
                username=os.environ.get("SMTP_USER", ""),
                password=os.environ.get("SMTP_PASSWORD", ""),
                from_addr=os.environ.get("SMTP_FROM", os.environ.get(
                    "SMTP_USER", "mesa@localhost")),
                to=email,
                subject="Seu acesso à Mesa IPE",
                body=(
                    "Olá,\n\nPara entrar ou criar sua conta na Mesa IPE, abra este link "
                    "(vale 30 minutos):\n\n"
                    f"{url}\n\n"
                    "Se você não pediu isso, ignore o e-mail.\n"
                ),
            )
            return
        print(f"magic link for {email}: {url}")

    app = FastAPI(title="Mesa IPE")
    app.state.store = db

    def current_user(request: Request) -> dict | None:
        token = request.cookies.get(COOKIE)
        if not token:
            return None
        return db.user_by_session(token)

    @app.get("/api/status")
    def status() -> dict:
        meta = db.last_status()
        return {
            "last_poll_at": meta.get("last_poll_at") or "",
            "last_poll_at_br": format_br(meta.get("last_poll_at") or ""),
            "last_poll_source": meta.get("last_poll_source") or "",
            "last_poll_error": meta.get("last_poll_error") or "",
        }

    @app.get("/api/categorias")
    def categorias(listagem: str = "") -> dict:
        return {"categorias": db.list_categorias(listagem=listagem)}

    @app.get("/api/tickers")
    def tickers(q: str = "") -> dict:
        return {"tickers": db.list_tickers(query=q)}

    @app.get("/api/ticker")
    def lookup_ticker(ticker: str = "") -> dict:
        raw = ticker.strip().upper()
        if not raw:
            raise HTTPException(400, "Informe um ticker, ex.: PETR4 ou C1MG34")
        known = db.find_known_ticker(raw)
        if known:
            return {"ok": True, **known}
        if looks_like_ticker(raw):
            try:
                info = resolver(raw)
                return {
                    "ok": True,
                    "ticker": info.ticker,
                    "ccvm": info.ccvm,
                    "empresa": info.company_name or info.trading_name or "",
                }
            except TickerNotFound:
                raise HTTPException(
                    404, f"Ticker não encontrado: {raw}") from None
            except OSError:
                raise HTTPException(
                    404, f"Ticker não encontrado: {raw}") from None
        raise HTTPException(400, "Informe um ticker, ex.: PETR4 ou C1MG34")

    @app.get("/api/ipe")
    def feed(
        ticker: str = "",
        categoria: str = "",
        empresa: str = "",
        ccvm: str = "",
        q: str = "",
        data_de: str = "",
        data_ate: str = "",
        data_ref_de: str = "",
        data_ref_ate: str = "",
        listagem: str = "",
        tickers: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        ticker_norm = ticker.strip().upper()
        ticker_list = [item.strip().upper()
                       for item in tickers.split(",") if item.strip()]
        nome = (empresa or q).strip()
        size = min(max(page_size, 1), 100)
        page_n = max(page, 1)
        total = db.count_filings(
            categoria=categoria,
            listagem=listagem,
            empresa=nome,
            ccvm=ccvm,
            ticker=ticker_norm,
            data_de=data_de,
            data_ate=data_ate,
            data_ref_de=data_ref_de,
            data_ref_ate=data_ref_ate,
            tickers=ticker_list,
        )
        pages = max(1, (total + size - 1) // size) if total else 1
        if page_n > pages:
            page_n = pages
        rows = db.list_filings(
            categoria=categoria,
            listagem=listagem,
            empresa=nome,
            ccvm=ccvm,
            ticker=ticker_norm,
            data_de=data_de,
            data_ate=data_ate,
            data_ref_de=data_ref_de,
            data_ref_ate=data_ref_ate,
            tickers=ticker_list,
            limit=size,
            offset=(page_n - 1) * size,
        )
        return {
            "source": "db",
            "ticker": ticker_norm,
            "ccvm_filtro": rows[0]["ccvm"] if rows and ticker_norm else "",
            "total": total,
            "page": page_n,
            "page_size": size,
            "pages": pages,
            "links": rows,
        }

    @app.get("/api/protocolos")
    def protocolos(
        ticker: str = "",
        categoria: str = "",
        empresa: str = "",
        q: str = "",
        data_de: str = "",
        data_ate: str = "",
        data_ref_de: str = "",
        data_ref_ate: str = "",
        listagem: str = "",
        tickers: str = "",
    ) -> dict:
        ticker_norm = ticker.strip().upper()
        ticker_list = [item.strip().upper()
                       for item in tickers.split(",") if item.strip()]
        nome = (empresa or q).strip()
        return {
            "ids": db.list_protocolos(
                categoria=categoria,
                listagem=listagem,
                empresa=nome,
                ticker=ticker_norm,
                data_de=data_de,
                data_ate=data_ate,
                data_ref_de=data_ref_de,
                data_ref_ate=data_ref_ate,
                tickers=ticker_list,
            )
        }

    @app.post("/api/entrar")
    def entrar(body: LoginIn) -> dict:
        email = (body.email or "").strip().lower()
        if not _EMAIL.match(email):
            raise HTTPException(400, "E-mail inválido")
        raw = request_login(db, email, mailer=send_magic, base_url=public_url)
        payload: dict[str, Any] = {
            "ok": True,
            "email": email,
            "message": "Enviamos um link de acesso para o seu e-mail. Ele vale 30 minutos.",
        }
        if show_link:
            payload["dev_link"] = f"{public_url.rstrip('/')}/api/entrar/callback?token={raw}"
        return payload

    @app.get("/api/entrar/callback")
    def entrar_callback(token: str) -> RedirectResponse:
        session = complete_login(db, token)
        if not session:
            return RedirectResponse("/entrar?erro=expirado", status_code=303)
        dest = RedirectResponse("/conta", status_code=303)
        dest.set_cookie(
            COOKIE,
            session,
            httponly=True,
            samesite="lax",
            max_age=30 * 24 * 3600,
            secure=public_url.startswith("https://"),
        )
        return dest

    @app.post("/api/sair")
    def sair(response: Response) -> dict:
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.post("/api/conta/apagar")
    def apagar_conta(request: Request, response: Response) -> dict:
        user = current_user(request)
        if not user:
            raise HTTPException(401, "Entre para apagar a conta")
        db.delete_user(user["id"])
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(request: Request) -> dict:
        user = current_user(request)
        if not user:
            return {"email": None}
        return {"email": user["email"], "id": user["id"]}

    @app.get("/api/favorites")
    def favorites(request: Request) -> list:
        user = current_user(request)
        if not user:
            raise HTTPException(401, "Entre para ver favoritos")
        return db.list_favorites(user["id"])

    @app.post("/api/favorites")
    def add_fav(body: FavoriteIn, request: Request) -> dict:
        user = current_user(request)
        if not user:
            raise HTTPException(401, "Entre para favoritar")
        try:
            info = resolver(body.ticker)
        except TickerNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        db.add_favorite(user["id"], ccvm=info.ccvm, ticker=info.ticker)
        return {"ok": True, "ccvm": info.ccvm, "ticker": info.ticker}

    @app.delete("/api/favorites")
    def del_fav(ticker: str, request: Request) -> dict:
        user = current_user(request)
        if not user:
            raise HTTPException(401, "Entre para gerenciar favoritos")
        try:
            info = resolver(ticker)
        except TickerNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        db.remove_favorite(user["id"], info.ccvm)
        return {"ok": True}

    @app.get("/api/rss/{ticker}")
    def rss(ticker: str) -> Response:
        try:
            info = resolver(ticker.upper())
        except TickerNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        rows = db.list_filings(ccvm=info.ccvm, limit=30)
        items = []
        for row in rows:
            items.append(
                f"<item><title>{_xml(row['empresa'])} — {_xml(row['categoria'])}</title>"
                f"<link>{_xml(row['url'])}</link>"
                f"<description>{_xml(row['especie'])}</description></item>"
            )
        xml = (
            '<?xml version="1.0"?><rss version="2.0"><channel>'
            f"<title>Mesa IPE {info.ticker}</title>"
            + "".join(items)
            + "</channel></rss>"
        )
        return Response(xml, media_type="application/rss+xml")

    @app.get("/")
    def pages() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/entrar")
    @app.get("/conta")
    def old_auth_pages() -> RedirectResponse:
        return RedirectResponse("/", status_code=303)

    @app.get("/{ticker}")
    def company_page(ticker: str) -> FileResponse:
        if ticker.lower() in {"api", "static", "favicon.ico"}:
            raise HTTPException(404, "Not found")
        return FileResponse(STATIC / "index.html")

    return app


def _xml(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


app = create_app()
