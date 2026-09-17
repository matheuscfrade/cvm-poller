import json
from pathlib import Path

import pytest

from cvm_poller.cli import main
from cvm_poller.parse import DownloadMultiploResult, IpeLink

SAMPLE = DownloadMultiploResult(
    data_solicitada="14/09/2026 00:00",
    documento="IPE",
    data_consulta="14/09/2026 10:28",
    links=[
        IpeLink(
            url="https://example/a",
            documento="IPE",
            ccvm="9512",
            data_ref="14/09/2026 09:13:00",
            frm_dt_ref="14/09/2026 09:13",
            categoria="Fato Relevante",
            tipo="-",
            especie="Mudanças na Diretoria",
            situacao="Liberado",
        )
    ],
    source="login",
)


def test_cli_prints_json(monkeypatch, capsys, tmp_path: Path):
    monkeypatch.setenv("CVM_LOGIN", "user")
    monkeypatch.setenv("CVM_SENHA", "secret")

    def fake_run(**kwargs):
        assert kwargs["login"] == "user"
        assert kwargs["senha"] == "secret"
        return SAMPLE

    monkeypatch.setattr("cvm_poller.cli.run_query", fake_run)
    code = main(["--data", "14/09/2026"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["documento"] == "IPE"
    assert payload["links"][0]["categoria"] == "Fato Relevante"


def test_cli_auth_error_is_clear(monkeypatch, capsys):
    monkeypatch.setenv("CVM_LOGIN", "user")
    monkeypatch.setenv("CVM_SENHA", "secret")

    def boom(**kwargs):
        from cvm_poller.parse import CvmAuthError

        raise CvmAuthError("1", "LOGIN INCORRETO", "Autenticacao")

    monkeypatch.setattr("cvm_poller.cli.run_query", boom)
    assert main(["--data", "14/09/2026"]) == 1
    err = capsys.readouterr().err
    assert "LOGIN INCORRETO" in err
    assert "aspas simples" in err.casefold()


def test_cli_public_skips_credentials(monkeypatch, capsys):
    monkeypatch.delenv("CVM_LOGIN", raising=False)
    monkeypatch.delenv("CVM_SENHA", raising=False)

    def fake_public(**kwargs):
        assert kwargs["source"] == "public"
        assert kwargs["ticker"] == "PETR4"
        return DownloadMultiploResult(
            data_solicitada=SAMPLE.data_solicitada,
            documento=SAMPLE.documento,
            data_consulta=SAMPLE.data_consulta,
            links=SAMPLE.links,
            source="public",
            ticker="PETR4",
            ccvm_filtro="9512",
        )

    monkeypatch.setattr("cvm_poller.cli.run_query", fake_public)
    code = main(["--source", "public", "--data", "14/09/2026", "--ticker", "PETR4"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "public"
    assert payload["ticker"] == "PETR4"


def test_cli_requires_credentials(monkeypatch):
    monkeypatch.delenv("CVM_LOGIN", raising=False)
    monkeypatch.delenv("CVM_SENHA", raising=False)
    with pytest.raises(SystemExit):
        main(["--data", "14/09/2026"])


def test_cli_new_only_skips_seen(monkeypatch, capsys, tmp_path: Path):
    monkeypatch.setenv("CVM_LOGIN", "user")
    monkeypatch.setenv("CVM_SENHA", "secret")
    state = tmp_path / "seen.json"
    monkeypatch.setattr("cvm_poller.cli.run_query", lambda **kwargs: SAMPLE)
    assert main(["--data", "14/09/2026", "--new-only", "--state", str(state)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert len(first["links"]) == 1
    assert main(["--data", "14/09/2026", "--new-only", "--state", str(state)]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["links"] == []
