from __future__ import annotations

from dataclasses import asdict, dataclass
from xml.etree import ElementTree as ET

AUTH_ERROR_CODE = "1"
NO_RECORDS_CODE = "22016"


class CvmResponseError(Exception):
    def __init__(self, codigo: str, mensagem: str, fonte: str = ""):
        super().__init__(mensagem)
        self.codigo = codigo
        self.fonte = fonte


class CvmAuthError(CvmResponseError):
    pass


@dataclass(frozen=True)
class IpeLink:
    url: str
    documento: str
    ccvm: str
    data_ref: str
    frm_dt_ref: str
    categoria: str
    tipo: str
    especie: str
    situacao: str
    empresa: str = ""
    data_entrega: str = ""
    protocolo: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DownloadMultiploResult:
    data_solicitada: str
    documento: str
    data_consulta: str
    links: list[IpeLink]
    source: str = "login"
    ticker: str = ""
    ccvm_filtro: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "data_solicitada": self.data_solicitada,
            "data_consulta": self.data_consulta,
            "documento": self.documento,
            "ticker": self.ticker,
            "ccvm_filtro": self.ccvm_filtro,
            "links": [link.to_dict() for link in self.links],
        }


def parse_download_multiplo(xml: str) -> DownloadMultiploResult:
    root = ET.fromstring(_normalize_xml(xml))
    tag = _local_name(root.tag)

    if tag == "ERROS":
        return _parse_erros(root)
    if tag == "DownloadMultiplo":
        return _parse_success(root)
    raise CvmResponseError("?", f"Resposta XML inesperada: <{tag}>")


def _normalize_xml(xml: str) -> str:
    text = xml.strip()
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    return text


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _child_text(parent: ET.Element, name: str) -> str:
    for child in parent:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _parse_erros(root: ET.Element) -> DownloadMultiploResult:
    codigo = _child_text(root, "NUMERO_DO_ERRO")
    mensagem = _child_text(root, "DESCRICAO_DO_ERRO")
    fonte = _child_text(root, "FONTE_DO_ERRO")
    if codigo == AUTH_ERROR_CODE:
        raise CvmAuthError(codigo, mensagem or "LOGIN INCORRETO", fonte)
    if codigo == NO_RECORDS_CODE:
        return DownloadMultiploResult(
            data_solicitada="",
            documento="",
            data_consulta="",
            links=[],
        )
    raise CvmResponseError(codigo, mensagem or "Erro no Download Múltiplo", fonte)


def _parse_success(root: ET.Element) -> DownloadMultiploResult:
    links = [
        IpeLink(
            url=node.attrib.get("url", ""),
            documento=node.attrib.get("Documento", ""),
            ccvm=node.attrib.get("ccvm", ""),
            data_ref=node.attrib.get("DataRef", ""),
            frm_dt_ref=node.attrib.get("FrmDtRef", ""),
            categoria=node.attrib.get("Categoria", ""),
            tipo=node.attrib.get("Tipo", ""),
            especie=node.attrib.get("Especie", ""),
            situacao=node.attrib.get("Situacao", ""),
        )
        for node in root
        if _local_name(node.tag) == "Link"
    ]
    return DownloadMultiploResult(
        data_solicitada=root.attrib.get("DataSolicitada", ""),
        documento=root.attrib.get("TipoDocumento", ""),
        data_consulta=root.attrib.get("DataConsulta", ""),
        links=links,
    )
