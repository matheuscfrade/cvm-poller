from cvm_poller.parse import CvmAuthError, CvmResponseError, parse_download_multiplo

EMPTY_XML = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<DownloadMultiplo DataSolicitada="14/09/2026 00:00" TipoDocumento="IPE" DataConsulta="14/09/2026 10:28" >
</DownloadMultiplo>
"""

LINKS_XML = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<DownloadMultiplo DataSolicitada="14/09/2026 00:00" TipoDocumento="IPE" DataConsulta="14/09/2026 10:28">
<Link url="https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&amp;numProtocolo=1567737" Documento="IPE" ccvm="02201" DataRef="14/10/2026 16:00:00" FrmDtRef="14/10/2026 16:00" Categoria="Assembleia" Tipo="AGDEB" Especie="Edital de Convocação" Situacao="Liberado" />
<Link url="https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&amp;numProtocolo=1568001" Documento="IPE" ccvm="02612" DataRef="14/09/2026 00:00:00" FrmDtRef="14/09/2026" Categoria="Fato Relevante" Tipo="-" Especie="Mudanças na Diretoria" Situacao="Liberado" />
</DownloadMultiplo>
"""

AUTH_ERROR_XML = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<ERROS>
<NUMERO_DO_ERRO>1</NUMERO_DO_ERRO>
<DESCRICAO_DO_ERRO>LOGIN INCORRETO</DESCRICAO_DO_ERRO>
<FONTE_DO_ERRO>Autenticacao</FONTE_DO_ERRO>
</ERROS>
"""

NO_RECORDS_XML = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<ERROS>
<NUMERO_DO_ERRO>22016</NUMERO_DO_ERRO>
<DESCRICAO_DO_ERRO>Nenhum registro localizado</DESCRICAO_DO_ERRO>
<FONTE_DO_ERRO>DownloadMultiplo</FONTE_DO_ERRO>
</ERROS>
"""


def test_empty_download_multiplo_returns_no_links():
    result = parse_download_multiplo(EMPTY_XML)
    assert result.documento == "IPE"
    assert result.data_solicitada == "14/09/2026 00:00"
    assert result.data_consulta == "14/09/2026 10:28"
    assert result.links == []


def test_parses_link_attributes():
    result = parse_download_multiplo(LINKS_XML)
    assert len(result.links) == 2
    first = result.links[0]
    assert first.documento == "IPE"
    assert first.ccvm == "02201"
    assert first.categoria == "Assembleia"
    assert first.tipo == "AGDEB"
    assert first.especie == "Edital de Convocação"
    assert first.situacao == "Liberado"
    assert "numProtocolo=1567737" in first.url
    assert first.data_entrega == ""
    assert first.empresa == ""
    assert first.data_ref == "14/10/2026 16:00:00"
    assert result.links[1].categoria == "Fato Relevante"


def test_login_error_raises_auth_error():
    try:
        parse_download_multiplo(AUTH_ERROR_XML)
    except CvmAuthError as exc:
        assert exc.codigo == "1"
        assert "LOGIN INCORRETO" in str(exc)
    else:
        raise AssertionError("expected CvmAuthError")


def test_nenhum_registro_is_empty_result():
    result = parse_download_multiplo(NO_RECORDS_XML)
    assert result.links == []


def test_unknown_error_raises():
    xml = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<ERROS>
<NUMERO_DO_ERRO>22014</NUMERO_DO_ERRO>
<DESCRICAO_DO_ERRO>Data informada inválida</DESCRICAO_DO_ERRO>
<FONTE_DO_ERRO>Validacao</FONTE_DO_ERRO>
</ERROS>
"""
    try:
        parse_download_multiplo(xml)
    except CvmResponseError as exc:
        assert exc.codigo == "22014"
    else:
        raise AssertionError("expected CvmResponseError")
