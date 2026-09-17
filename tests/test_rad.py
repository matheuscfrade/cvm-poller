import json

from cvm_poller.rad import parse_listar_documentos

DADOS = (
    "02201-2$&MILLS S.A$&Assembleia$&AGDEB$&"
    "<spanOrder>AGE 10</spanOrder>Edital de Convocação$&"
    "<spanOrder>20261014</spanOrder> 14/10/2026 16:00$&"
    "<spanOrder>20260914</spanOrder> 14/09/2026 07:27$&"
    "Ativo$&1$&AP$&"
    "<i onclick=OpenPopUpVer('frmExibirArquivoIPEExterno.aspx?NumeroProtocoloEntrega=1567737')></i>"
    "<i onclick=OpenDownloadDocumentos('1092443','1','1567737','IPE')></i>$&"
    "AGE 10"
    "$&&*"
    "02612-3$&ONCOCLINICAS$&Fato Relevante$&-$&"
    "<spanOrder>Mudanças na Diretoria</spanOrder> -$&"
    "<spanOrder>20260914</spanOrder> 14/09/2026$&"
    "<spanOrder>20260914</spanOrder> 14/09/2026 09:13$&"
    "Ativo$&1$&AP$&"
    "<i onclick=OpenDownloadDocumentos('111','1','1568001','IPE')></i>$&"
    "Mudanças"
)


def test_parses_two_ipe_rows():
    result = parse_listar_documentos({"d": {"temErro": False, "dados": DADOS}})
    assert len(result.links) == 2
    mills = result.links[0]
    assert mills.ccvm == "22012"
    assert mills.empresa == "MILLS S.A"
    assert mills.categoria == "Assembleia"
    assert mills.tipo == "AGDEB"
    assert mills.especie == "Edital de Convocação"
    assert mills.situacao == "Ativo"
    assert mills.protocolo == "1567737"
    assert "numProtocolo=1567737" in mills.url
    assert "numSequencia=1092443" in mills.url
    assert result.links[1].categoria == "Fato Relevante"
    assert result.links[1].ccvm == "26123"


def test_ccvm_keeps_check_digit():
    dados = "00951-2$&PETROBRAS$&Fato Relevante$&-$&x$&d$&e$&Ativo$&1$&AP$&<i onclick=OpenDownloadDocumentos('1','1','2','IPE')></i>$&x"
    result = parse_listar_documentos({"d": {"temErro": False, "dados": dados}})
    assert result.links[0].ccvm == "9512"


def test_empty_dados_is_empty_list():
    result = parse_listar_documentos({"d": {"temErro": False, "dados": ""}})
    assert result.links == []


def test_tem_erro_raises():
    try:
        parse_listar_documentos({"d": {"temErro": True, "msgErro": "falha", "dados": ""}})
    except Exception as exc:
        assert "falha" in str(exc)
    else:
        raise AssertionError("expected error")


def test_fetch_posts_date_window():
    from cvm_poller.rad import fetch_listar_documentos

    captured = {}

    def fake_post(url, body):
        captured["url"] = url
        captured["body"] = body
        return json.dumps({"d": {"temErro": False, "dados": DADOS}})

    result = fetch_listar_documentos(
        data_de="14/09/2026",
        hora_ini="00:00",
        hora_fim="08:00",
        post=fake_post,
    )
    assert "ListarDocumentos" in captured["url"]
    assert captured["body"]["dataDe"] == "14/09/2026"
    assert captured["body"]["horaIni"] == "00:00"
    assert captured["body"]["horaFim"] == "08:00"
    assert captured["body"]["categoria"] == "IPE_-1_-1_-1"
    assert len(result.links) == 2
    assert result.source == "public"


def test_captcha_flag_n_is_not_requested():
    result = parse_listar_documentos(
        {"d": {"temErro": False, "SolicitarCaptcha": "N", "dados": ""}}
    )
    assert result.links == []


def test_captcha_raises():
    try:
        parse_listar_documentos(
            {"d": {"temErro": False, "SolicitarCaptcha": True, "dados": DADOS}}
        )
    except Exception as exc:
        assert "captcha" in str(exc).casefold()
    else:
        raise AssertionError("expected captcha error")
