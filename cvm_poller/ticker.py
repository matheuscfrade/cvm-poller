from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from cvm_poller.parse import CvmResponseError

B3_COMPANIES_URL = (
    "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/"
    "CompanyCall/GetInitialCompanies/"
)
B3_DETAIL_URL = (
    "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/"
    "CompanyCall/GetDetail/"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_COMPANIES: list[dict[str, Any]] | None = None
# PETR4, SANB11, JPMC34 e BDRs com dígito no código (C1MG34, A1DM34).
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{2,5}\d{1,2}$")


class TickerNotFound(CvmResponseError):
    def __init__(self, ticker: str):
        super().__init__("ticker", f"Ticker não encontrado na B3: {ticker}")
        self.ticker = ticker


@dataclass(frozen=True)
class TickerInfo:
    ticker: str
    ccvm: str
    issuing_company: str
    company_name: str
    trading_name: str = ""


def looks_like_ticker(ticker: str) -> bool:
    return bool(_TICKER_RE.fullmatch(ticker.strip().upper()))


def issuing_code(ticker: str) -> str:
    text = ticker.strip().upper()
    return re.sub(r"\d+$", "", text)


def resolve_ticker(
    ticker: str,
    companies: list[dict[str, Any]] | None = None,
    load_companies: Any = None,
) -> TickerInfo:
    raw = ticker.strip().upper()
    if not raw:
        raise TickerNotFound(ticker)
    if raw.isdigit():
        return TickerInfo(
            ticker=raw,
            ccvm=str(int(raw)),
            issuing_company="",
            company_name="",
        )
    prefix = issuing_code(raw)
    rows = companies if companies is not None else (load_companies or listed_companies)()
    for row in rows:
        issuing = str(row.get("issuingCompany") or "").upper()
        if issuing == prefix or issuing == raw:
            return TickerInfo(
                ticker=raw,
                ccvm=str(row.get("codeCVM") or "").lstrip("0") or "0",
                issuing_company=issuing,
                company_name=str(row.get("companyName") or ""),
                trading_name=str(row.get("tradingName") or ""),
            )
        trading = str(row.get("tradingName") or "").upper()
        name = str(row.get("companyName") or "").upper()
        if raw == trading or prefix == trading:
            return TickerInfo(
                ticker=raw,
                ccvm=str(row.get("codeCVM") or "").lstrip("0") or "0",
                issuing_company=issuing,
                company_name=str(row.get("companyName") or ""),
                trading_name=str(row.get("tradingName") or ""),
            )
        if len(raw) >= 4 and raw in name and issuing:
            # avoid matching PETR inside ACU PETROLEO via issuing only
            continue
    raise TickerNotFound(raw)


def listed_companies() -> list[dict[str, Any]]:
    global _COMPANIES
    if _COMPANIES is None:
        _COMPANIES = _fetch_companies()
    return _COMPANIES


def fetch_company_detail(ccvm: str) -> dict[str, Any] | None:
    import base64

    payload = {"codeCVM": str(ccvm).lstrip("0") or ccvm, "language": "pt-br"}
    encoded = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()
    request = Request(B3_DETAIL_URL + encoded, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read()
    except OSError:
        return None
    if not raw:
        return None
    try:
        body = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict) or not body.get("codeCVM"):
        return None
    return body


def _fetch_companies() -> list[dict[str, Any]]:
    import base64

    encoded = base64.b64encode(
        json.dumps({"language": "pt-br"}, separators=(",", ":")).encode()
    ).decode()
    url = B3_COMPANIES_URL + encoded
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode("utf-8"))
    return list(body.get("results") or [])
