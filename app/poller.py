from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime

from app.store import Store, protocolo_of
from app.timeutil import official_date, today_br
from cvm_poller.client import fetch_download_multiplo
from cvm_poller.parse import CvmAuthError, CvmResponseError, DownloadMultiploResult
from cvm_poller.rad import fetch_data_envio, fetch_listar_documentos
from cvm_poller.ticker import fetch_company_detail, listed_companies

log = logging.getLogger("ipe.poller")

LoginFetcher = Callable[..., DownloadMultiploResult]
PublicFetcher = Callable[..., DownloadMultiploResult]


@dataclass(frozen=True)
class PollResult:
    novos: int
    source: str
    erro: str = ""
    cursor: str = ""


def poll_once(
    store: Store,
    login: str,
    senha: str,
    documento: str = "IPE",
    fetch_login: LoginFetcher | None = None,
    fetch_public: PublicFetcher | None = None,
    load_companies: Callable[[], list] | None = None,
    fetch_detail: Callable[[str], dict | None] | None = None,
    fetch_envio: Callable[[str], str | None] | None = None,
    today: date | None = None,
    data_override: str | None = None,
) -> PollResult:
    today = today or today_br()
    if data_override:
        data = data_override.strip()
        hora = "00:00"
    else:
        data, hora = _window(store, today)
    source = "login"
    erro = ""
    result: DownloadMultiploResult | None = None
    login_fetch = fetch_login or fetch_download_multiplo
    public_fetch = fetch_public or fetch_listar_documentos
    try:
        result = login_fetch(
            login=login,
            senha=senha,
            data=data,
            hora=hora,
            documento=documento,
        )
    except (CvmAuthError, CvmResponseError) as exc:
        erro = str(exc)
        log.warning("login poll failed: %s", exc)
        source = "public"
        try:
            result = public_fetch(
                data_de=data,
                data_ate=data,
                hora_ini=hora,
            )
            erro = f"fallback RAD após: {erro}"
        except CvmResponseError as public_exc:
            erro = f"{erro}; RAD: {public_exc}"
            store.record_poll(source="login", novos=0,
                              erro=erro, cursor=f"{data} {hora}")
            return PollResult(novos=0, source="login", erro=erro, cursor=f"{data} {hora}")

    assert result is not None
    if source == "login":
        result = _with_rad_envio(
            result,
            public_fetch,
            data,
            fetch_envio=fetch_envio if fetch_envio is not None else fetch_data_envio,
        )
    if data_override:
        result = _only_delivery_day(result, data)
    try:
        loader = load_companies or listed_companies
        store.upsert_companies(loader())
    except Exception:
        log.warning("não deu para atualizar cadastro B3", exc_info=True)
    novos = store.upsert_filings(result.links, source=result.source or source)
    store.apply_entregas(
        {
            (link.protocolo or protocolo_of(link)): link.data_entrega
            for link in result.links
            if link.data_entrega
        }
    )
    store.enrich_missing(
        fetch_detail=fetch_detail if fetch_detail is not None else fetch_company_detail)
    if novos:
        store.enqueue_alerts_for_new(result.links)
    if data_override:
        cursor = f"{data_override.strip()} 00:00"
    else:
        cursor = result.data_consulta or f"{data} {hora}"
    store.record_poll(source=source, novos=novos, erro=erro, cursor=cursor)
    return PollResult(novos=novos, source=source, erro=erro, cursor=cursor)


def _only_delivery_day(
    result: DownloadMultiploResult,
    requested_day: str,
) -> DownloadMultiploResult:
    """Keep historical poll results whose known delivery date matches the request."""
    requested = official_date(requested_day).split(" ", 1)[0]
    links = [
        link for link in result.links
        if not link.data_entrega
        or official_date(link.data_entrega).split(" ", 1)[0] == requested
    ]
    return replace(result, links=links)


def _window(store: Store, today: date) -> tuple[str, str]:
    data = today.strftime("%d/%m/%Y")
    cursor = store.get_meta("last_cursor")
    if not cursor:
        return data, "00:00"
    try:
        parsed = datetime.strptime(cursor.strip(), "%d/%m/%Y %H:%M")
    except ValueError:
        return data, "00:00"
    if parsed.date() != today:
        return data, "00:00"
    return data, parsed.strftime("%H:%M")


def _with_rad_envio(
    result: DownloadMultiploResult,
    public_fetch: PublicFetcher,
    data: str,
    fetch_envio: Callable[[str], str | None] | None = None,
) -> DownloadMultiploResult:
    try:
        public = public_fetch(data_de=data, data_ate=data)
    except Exception:
        log.warning(
            "lista pública do RAD indisponível; usando cabeçalho por protocolo")
        public = None
    by_proto: dict[str, str] = {}
    by_nome: dict[str, str] = {}
    if public:
        for link in public.links:
            proto = link.protocolo or protocolo_of(link)
            if not proto:
                continue
            if link.data_entrega:
                by_proto[proto] = link.data_entrega
            if link.empresa:
                by_nome[proto] = link.empresa
    merged = []
    for link in result.links:
        proto = link.protocolo or protocolo_of(link)
        envio = official_date(by_proto.get(proto) or link.data_entrega)
        if not envio and fetch_envio and proto:
            envio = official_date(fetch_envio(proto) or "")
        nome = link.empresa or by_nome.get(proto) or ""
        merged.append(replace(link, protocolo=proto,
                      data_entrega=envio, empresa=nome))
    return DownloadMultiploResult(
        data_solicitada=result.data_solicitada,
        documento=result.documento,
        data_consulta=result.data_consulta,
        links=merged,
        source=result.source,
        ticker=result.ticker,
        ccvm_filtro=result.ccvm_filtro,
    )
