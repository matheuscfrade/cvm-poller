from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from cvm_poller.parse import CvmAuthError, CvmResponseError, DownloadMultiploResult
from cvm_poller.query import run_query
from cvm_poller.state import SeenStore
from cvm_poller.ticker import TickerNotFound


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        import uvicorn

        host = "127.0.0.1"
        port = 8765
        rest = argv[1:]
        if "--host" in rest:
            host = rest[rest.index("--host") + 1]
        if "--port" in rest:
            port = int(rest[rest.index("--port") + 1])
        uvicorn.run("app.web:app", host=host, port=port, reload=False)
        return 0
    if argv and argv[0] == "worker":
        from app.worker import main as worker_main

        worker_main()
        return 0
    if argv and argv[0] == "poll":
        from app.poller import poll_once
        from app.store import Store

        login = os.environ.get("CVM_LOGIN", "").strip().strip("'\"")
        senha = os.environ.get("CVM_SENHA", "").strip().strip("'\"")
        if not login or not senha:
            print("Defina CVM_LOGIN e CVM_SENHA.", file=sys.stderr)
            return 2

        rest = argv[1:]
        data_override = ""
        if "--data" in rest:
            idx = rest.index("--data")
            if idx + 1 < len(rest):
                data_override = rest[idx + 1]

        store = Store(Path(os.environ.get("DATABASE_PATH", "data/ipe.db")))
        result = poll_once(store, login=login, senha=senha,
                           data_override=data_override or None)
        print(
            f"novos={result.novos} source={result.source} cursor={result.cursor} erro={result.erro}")
        return 0 if not result.erro or result.novos or result.source == "public" else 1
    if argv and argv[0] == "enrich":
        from app.store import Store
        from cvm_poller.ticker import fetch_company_detail, listed_companies

        store = Store(Path(os.environ.get("DATABASE_PATH", "data/ipe.db")))
        from datetime import timedelta

        from app.timeutil import today_br
        from cvm_poller.rad import fetch_cabecalho, fetch_listar_documentos

        n = store.upsert_companies(listed_companies())
        u = store.enrich_missing(fetch_detail=fetch_company_detail)
        envios = {}
        nomes = {}
        end = today_br()
        for offset in range(8):
            day = (end - timedelta(days=offset)).strftime("%d/%m/%Y")
            public = fetch_listar_documentos(day, day)
            for link in public.links:
                if not link.protocolo:
                    continue
                if link.data_entrega:
                    envios[link.protocolo] = link.data_entrega
                if link.empresa:
                    nomes[link.protocolo] = link.empresa
        e = store.apply_entregas(envios)
        store.apply_nomes(nomes)
        extras = {}
        cab_nomes = {}
        seen = set(store.protocolos_sem_entrega()) | set(
            store.protocolos_nome_curto())
        for proto in seen:
            cab = fetch_cabecalho(proto)
            if not cab:
                continue
            if cab.get("envio"):
                extras[proto] = cab["envio"]
            if cab.get("empresa"):
                cab_nomes[proto] = cab["empresa"]
        e += store.apply_entregas(extras)
        m = store.apply_nomes(cab_nomes)
        print(f"empresas={n} cadastro={u} datas_envio={e} nomes={m}")
        return 0

    args = _parse_args(argv)
    login = os.environ.get("CVM_LOGIN", "").strip().strip("'\"")
    senha = os.environ.get("CVM_SENHA", "").strip().strip("'\"")
    if args.source == "login" and (not login or not senha):
        print(
            "Defina CVM_LOGIN e CVM_SENHA no ambiente, ou use --source public.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if args.debug and args.source == "login":
        print(
            f"login_len={len(login)} senha_len={len(senha)}",
            file=sys.stderr,
        )

    try:
        result = run_query(
            source=args.source,
            data=args.data,
            data_ate=args.data_ate,
            hora=args.hora,
            hora_fim=args.hora_fim,
            categoria=args.categoria,
            ticker=args.ticker,
            documento=args.documento,
            login=login,
            senha=senha,
        )
    except TickerNotFound as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except CvmAuthError as exc:
        detalhe = str(exc)
        print(f"{detalhe} (código {exc.codigo}).", file=sys.stderr)
        if "SUSPENSO" in detalhe.upper():
            print(
                "A CVM reconheceu o login, mas a conta está suspensa.\n"
                "Peça reativação: suporteexterno@cvm.gov.br | 0800 944-3535.",
                file=sys.stderr,
            )
        else:
            print(
                "No PowerShell use aspas simples, para $ na senha não ser expandido:\n"
                "  $env:CVM_LOGIN = 'seu_login'\n"
                "  $env:CVM_SENHA = 'sua_senha'",
                file=sys.stderr,
            )
        return 1
    except CvmResponseError as exc:
        print(
            f"CVM recusou a consulta: {exc} (código {exc.codigo})", file=sys.stderr)
        return 1

    links = result.links
    if args.new_only:
        store = SeenStore(Path(args.state))
        links = store.filter_new(links)
        store.mark_seen(links)

    payload = DownloadMultiploResult(
        data_solicitada=result.data_solicitada,
        documento=result.documento,
        data_consulta=result.data_consulta,
        links=links,
        source=result.source,
        ticker=result.ticker,
        ccvm_filtro=result.ccvm_filtro,
    ).to_dict()
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consulta IPE ao vivo: RAD público (sem senha) ou Download Múltiplo (login CVM)."
    )
    parser.add_argument(
        "--source",
        choices=("public", "login"),
        default="login",
        help="public = consulta RAD sem senha; login = Download Múltiplo.",
    )
    parser.add_argument("--ticker", default="", help="Ticker B3, ex.: PETR4.")
    parser.add_argument(
        "--data",
        default=date.today().strftime("%d/%m/%Y"),
        help="Data da pesquisa (dd/mm/aaaa). Padrão: hoje.",
    )
    parser.add_argument("--hora", default="00:00",
                        help="Hora inicial (HH:MM).")
    parser.add_argument("--data-ate", default="",
                        help="Data final (consulta pública).")
    parser.add_argument("--hora-fim", default="",
                        help="Hora final (consulta pública).")
    parser.add_argument("--documento", default="IPE")
    parser.add_argument("--categoria", default="",
                        help='Ex.: "Fato Relevante".')
    parser.add_argument("--new-only", action="store_true")
    parser.add_argument("--state", default=".cvm-poller-seen.json")
    parser.add_argument(
        "--assunto",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)
