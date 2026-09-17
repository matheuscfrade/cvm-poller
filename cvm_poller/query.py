from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cvm_poller.client import fetch_download_multiplo
from cvm_poller.parse import DownloadMultiploResult, IpeLink
from cvm_poller.rad import fetch_listar_documentos
from cvm_poller.ticker import resolve_ticker

PublicFetcher = Callable[..., DownloadMultiploResult]
LoginFetcher = Callable[..., DownloadMultiploResult]


def filter_links(
    links: list[IpeLink],
    categoria: str = "",
    ccvm: str = "",
) -> list[IpeLink]:
    kept = list(links)
    if categoria:
        needle = categoria.casefold()
        kept = [link for link in kept if needle in link.categoria.casefold()]
    if ccvm:
        target = ccvm.lstrip("0")
        kept = [link for link in kept if link.ccvm.lstrip("0") == target]
    return kept


def run_query(
    source: str,
    data: str,
    data_ate: str = "",
    hora: str = "00:00",
    hora_fim: str = "",
    categoria: str = "",
    ticker: str = "",
    documento: str = "IPE",
    login: str = "",
    senha: str = "",
    fetch_public: PublicFetcher | None = None,
    fetch_login: LoginFetcher | None = None,
    resolve: Callable[..., Any] | None = None,
) -> DownloadMultiploResult:
    ccvm = ""
    ticker_norm = ticker.strip().upper()
    if ticker_norm:
        resolver = resolve or resolve_ticker
        info = resolver(ticker_norm)
        ccvm = info.ccvm
        ticker_norm = info.ticker
    if source == "public":
        fetcher = fetch_public or fetch_listar_documentos
        result = fetcher(
            data_de=data,
            data_ate=data_ate or data,
            hora_ini=hora,
            hora_fim=hora_fim,
            empresa="",
        )
    else:
        fetcher = fetch_login or fetch_download_multiplo
        result = fetcher(
            login=login,
            senha=senha,
            data=data,
            hora=hora,
            documento=documento,
        )
    links = filter_links(result.links, categoria=categoria, ccvm=ccvm)
    return DownloadMultiploResult(
        data_solicitada=result.data_solicitada,
        documento=result.documento,
        data_consulta=result.data_consulta,
        links=links,
        source=result.source,
        ticker=ticker_norm,
        ccvm_filtro=ccvm,
    )
