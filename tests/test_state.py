from pathlib import Path

from cvm_poller.parse import IpeLink
from cvm_poller.state import SeenStore

LINK_A = IpeLink(
    url="https://example/a",
    documento="IPE",
    ccvm="1",
    data_ref="",
    frm_dt_ref="",
    categoria="Fato Relevante",
    tipo="",
    especie="",
    situacao="Liberado",
)
LINK_B = IpeLink(
    url="https://example/b",
    documento="IPE",
    ccvm="2",
    data_ref="",
    frm_dt_ref="",
    categoria="Assembleia",
    tipo="",
    especie="",
    situacao="Liberado",
)


def test_first_poll_treats_all_as_new(tmp_path: Path):
    store = SeenStore(tmp_path / "seen.json")
    new = store.filter_new([LINK_A, LINK_B])
    assert new == [LINK_A, LINK_B]


def test_second_poll_skips_already_seen(tmp_path: Path):
    path = tmp_path / "seen.json"
    store = SeenStore(path)
    store.mark_seen([LINK_A])
    later = SeenStore(path)
    new = later.filter_new([LINK_A, LINK_B])
    assert new == [LINK_B]
