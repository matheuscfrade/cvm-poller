from __future__ import annotations

import json
import re
from collections.abc import Callable
from http.cookiejar import CookieJar
from typing import Any
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from cvm_poller.parse import CvmResponseError, DownloadMultiploResult, IpeLink

LISTAR_URL = "https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx/ListarDocumentos"
DOWNLOAD_URL = "https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx"
CONSULTA_REFERER = "https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx"
CABECALHO_URL = (
    "https://www.rad.cvm.gov.br/ENET/frmExibirArquivoIPEExterno.aspx/MontarDadosCabecalhoTela"
)
IPE_ALL = "IPE_-1_-1_-1"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_TAG = re.compile(r"<[^>]+>")
_DOWNLOAD = re.compile(
    r"OpenDownloadDocumentos\(\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*\)"
)
_VIEW_PROTO = re.compile(r"NumeroProtocoloEntrega=(\d+)")

Poster = Callable[..., str]


def fetch_cabecalho(protocolo: str) -> dict[str, str] | None:
    payload = json.dumps(
        {"codigoInstituicao": 1, "numeroProtocolo": int(protocolo)}
    ).encode("utf-8")
    request = Request(
        CABECALHO_URL,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.rad.cvm.gov.br",
            "Referer": (
                "https://www.rad.cvm.gov.br/ENET/"
                f"frmExibirArquivoIPEExterno.aspx?NumeroProtocoloEntrega={protocolo}"
            ),
        },
    )
    try:
        with urlopen(request, timeout=25) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    raw = str(body.get("d") or "")
    parts = raw.split(";")
    if len(parts) < 5:
        return None
    return {
        "empresa": parts[0].strip(),
        "envio": parts[4].strip(),
    }


def fetch_data_envio(protocolo: str) -> str | None:
    cab = fetch_cabecalho(protocolo)
    if not cab:
        return None
    return cab.get("envio") or None


def parse_listar_documentos(payload: dict[str, Any] | str) -> DownloadMultiploResult:
    if isinstance(payload, str):
        payload = json.loads(payload)
    data = payload.get("d", payload)
    if data.get("temErro"):
        raise CvmResponseError("rad", data.get("msgErro") or "Erro na consulta pública RAD")
    if _flag_true(data.get("SolicitarCaptcha")):
        raise CvmResponseError("captcha", "RAD pediu captcha; tente de novo em alguns minutos")
    if data.get("expirouSessao"):
        raise CvmResponseError("sessao", "Sessão RAD expirada")

    dados = data.get("dados") or ""
    links = [_parse_row(chunk) for chunk in dados.split("$&&*") if chunk.strip()]
    links = [link for link in links if link is not None]
    return DownloadMultiploResult(
        data_solicitada="",
        documento="IPE",
        data_consulta="",
        links=links,
        source="public",
    )


def fetch_listar_documentos(
    data_de: str,
    data_ate: str | None = None,
    hora_ini: str = "",
    hora_fim: str = "",
    categoria: str = IPE_ALL,
    empresa: str = "",
    post: Poster | None = None,
) -> DownloadMultiploResult:
    body = {
        "dataDe": data_de,
        "dataAte": data_ate or data_de,
        "empresa": empresa,
        "setorAtividade": "-1",
        "categoriaEmissor": "-1",
        "situacaoEmissor": "-1",
        "tipoParticipante": "1",
        "dataReferencia": "",
        "categoria": categoria,
        "periodo": "2",
        "horaIni": hora_ini,
        "horaFim": hora_fim,
        "palavraChave": "",
        "ultimaDtRef": "false",
        "tipoEmpresa": "0",
        "token": "",
        "versaoCaptcha": "",
    }
    poster = post or _json_post
    raw = poster(LISTAR_URL, body)
    parsed = json.loads(raw)
    result = parse_listar_documentos(parsed)
    return DownloadMultiploResult(
        data_solicitada=f"{data_de} {hora_ini or '00:00'}".strip(),
        documento="IPE",
        data_consulta=result.data_consulta,
        links=result.links,
        source="public",
    )


def _flag_true(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in {"s", "sim", "true", "1"}
    return False


def _json_post(url: str, body: dict[str, str]) -> str:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    warmup = Request(CONSULTA_REFERER, headers={"User-Agent": USER_AGENT})
    opener.open(warmup, timeout=60).read()
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.rad.cvm.gov.br",
            "Referer": CONSULTA_REFERER,
        },
    )
    with opener.open(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_row(chunk: str) -> IpeLink | None:
    parts = chunk.split("$&")
    if len(parts) < 11:
        return None
    acoes = parts[10]
    download = _DOWNLOAD.search(acoes)
    view = _VIEW_PROTO.search(acoes)
    if download:
        num_seq, instituicao, protocolo, desc_tipo = download.groups()
        url = (
            f"{DOWNLOAD_URL}?Tela=ext&descTipo={desc_tipo}"
            f"&CodigoInstituicao={instituicao}&numProtocolo={protocolo}"
            f"&numSequencia={num_seq}&numVersao=1"
        )
        documento = desc_tipo
    elif view:
        protocolo = view.group(1)
        url = (
            "https://www.rad.cvm.gov.br/ENET/"
            f"frmExibirArquivoIPEExterno.aspx?NumeroProtocoloEntrega={protocolo}"
        )
        documento = "IPE"
    else:
        protocolo = ""
        url = ""
        documento = "IPE"

    especie = _after_span(parts[4])
    data_ref = _after_span(parts[5])
    data_entrega = _after_span(parts[6])
    return IpeLink(
        url=url,
        documento=documento,
        ccvm=_ccvm(parts[0]),
        data_ref=data_ref,
        frm_dt_ref=data_ref,
        categoria=_plain(parts[2]),
        tipo=_plain(parts[3]),
        especie=especie,
        situacao=_plain(parts[7]),
        empresa=_plain(parts[1]),
        data_entrega=data_entrega,
        protocolo=protocolo,
    )


def _ccvm(raw: str) -> str:
    digits = re.sub(r"\D+", "", raw)
    return digits.lstrip("0") or "0"


def _plain(raw: str) -> str:
    text = _TAG.sub(" ", raw.replace("<spanOrder>", " ").replace("</spanOrder>", " "))
    return re.sub(r"\s+", " ", text).strip()


def _after_span(raw: str) -> str:
    if "</spanOrder>" in raw:
        return _plain(raw.split("</spanOrder>", 1)[1])
    return _plain(raw)
