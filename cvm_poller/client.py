from __future__ import annotations

from collections.abc import Callable
from typing import Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cvm_poller.parse import DownloadMultiploResult, parse_download_multiplo

DEFAULT_URL = "https://seguro.bmfbovespa.com.br/rad/download/SolicitaDownload.asp"
USER_AGENT = "cvm-poller/0.1"

Poster = Callable[..., str]


def fetch_download_multiplo(
    login: str,
    senha: str,
    data: str,
    hora: str = "00:00",
    documento: str = "IPE",
    assunto_ipe: str = "SIM",
    url: str = DEFAULT_URL,
    post: Poster | None = None,
) -> DownloadMultiploResult:
    form = {
        "txtLogin": login,
        "txtSenha": senha,
        "txtData": data,
        "txtHora": hora,
        "txtDocumento": documento,
        "txtAssuntoIPE": assunto_ipe,
    }
    poster = post or _urllib_post
    xml = poster(url, form, encoding="ISO-8859-1")
    return parse_download_multiplo(xml)


def encode_form(data: Mapping[str, str], encoding: str = "ISO-8859-1") -> bytes:
    return urlencode(data, encoding=encoding, errors="strict").encode("ascii")


def _urllib_post(url: str, data: Mapping[str, str], encoding: str = "ISO-8859-1") -> str:
    body = encode_form(data, encoding=encoding)
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
    )
    with urlopen(request, timeout=60) as response:
        raw = response.read()
    return raw.decode(encoding, errors="replace")
