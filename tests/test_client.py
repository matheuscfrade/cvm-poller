from urllib.parse import parse_qs

from cvm_poller.client import encode_form, fetch_download_multiplo

LINKS_XML = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<DownloadMultiplo DataSolicitada="14/09/2026 00:00" TipoDocumento="IPE" DataConsulta="14/09/2026 10:28">
<Link url="https://example/doc" Documento="IPE" ccvm="9512" DataRef="14/09/2026 09:13:00" FrmDtRef="14/09/2026 09:13" Categoria="Fato Relevante" Tipo="-" Especie="-" Situacao="Liberado" />
</DownloadMultiplo>
"""


def test_posts_form_fields_and_parses_links():
    captured = {}

    def fake_post(url, data, encoding="ISO-8859-1"):
        captured["url"] = url
        captured["data"] = data
        captured["encoding"] = encoding
        return LINKS_XML

    result = fetch_download_multiplo(
        login="user",
        senha="secret",
        data="14/09/2026",
        hora="00:00",
        documento="IPE",
        post=fake_post,
    )
    assert captured["data"]["txtLogin"] == "user"
    assert captured["data"]["txtSenha"] == "secret"
    assert captured["data"]["txtData"] == "14/09/2026"
    assert captured["data"]["txtHora"] == "00:00"
    assert captured["data"]["txtDocumento"] == "IPE"
    assert captured["data"]["txtAssuntoIPE"] == "SIM"
    assert "SolicitaDownload.asp" in captured["url"]
    assert len(result.links) == 1
    assert result.links[0].ccvm == "9512"


def test_form_encodes_latin1_not_utf8():
    body = encode_form({"txtSenha": "senhação"})
    assert b"%E7%E3" in body
    assert b"%C3%A7" not in body
    parsed = parse_qs(body.decode("ascii"), encoding="ISO-8859-1")
    assert parsed["txtSenha"] == ["senhação"]
