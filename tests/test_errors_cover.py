"""Mensagens de erro (gui/errors.py) e leitura da capa (main.MetadataWorker)."""

import traceback

import pytest

from gui.errors import describe_error


def _traceback_of(exc: BaseException) -> str:
    try:
        raise exc
    except BaseException:
        return traceback.format_exc()


@pytest.mark.parametrize("error, summary, hint", [
    (_traceback_of(ModuleNotFoundError("No module named 'torch'", name="torch")), "biblioteca", "pip install"),
    (_traceback_of(MemoryError()), "Memória insuficiente", "Feche"),
    ("Traceback (most recent call last):\ntorch.OutOfMemoryError: CUDA out of memory.", "Memória insuficiente", None),
    (_traceback_of(FileNotFoundError(2, "No such file or directory", "/x/musica.mp3")), "/x/musica.mp3", "movido"),
    ("Traceback (most recent call last):\nOSError: [Errno 28] No space left on device", "espaço livre", None),
    (_traceback_of(RuntimeError("Modelo não carregou")), "Modelo não carregou", None),
])
def test_erros_viram_mensagens_amigaveis(error, summary, hint):
    info = describe_error(error)
    assert summary in info.summary
    if hint:
        assert hint in info.hint
    assert "Traceback" in info.details


def test_mensagem_ja_amigavel_e_mantida():
    info = describe_error("Timeout ao comunicar com /dev/ttyACM0")
    assert info.summary.startswith("Timeout") and info.details is None


JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32


def test_capa_normal_nao_e_alterada(qapp):
    from main import MetadataWorker
    assert MetadataWorker._strip_to_image(JPEG) == JPEG


def _fake_tag(data, mime="image/jpeg", name="front_cover"):
    from types import SimpleNamespace
    image = SimpleNamespace(data=data, mime_type=mime, name=name)
    return SimpleNamespace(images=SimpleNamespace(any=image))


def test_capa_deslocada_pela_tinytag_e_corrigida(qapp):
    # Quadro ID3 v2.4 com "data length indicator": a tinytag devolve a
    # descrição antes da imagem (caso real de arquivos baixados com yt-dlp).
    # Passa pelo mesmo caminho usado pelo programa (_extract_cover).
    from main import MetadataWorker
    broken = b"\x03Album cover\x00" + JPEG
    tag = _fake_tag(broken, mime="\x04`f", name="unknown")
    assert MetadataWorker._extract_cover(tag) == JPEG


def test_arquivo_sem_capa(qapp):
    from types import SimpleNamespace
    from main import MetadataWorker
    assert MetadataWorker._extract_cover(SimpleNamespace(images=SimpleNamespace(any=None))) is None


def test_dados_desconhecidos_sao_devolvidos_como_estao(qapp):
    from main import MetadataWorker
    data = b"isto nao e uma imagem" * 10
    assert MetadataWorker._strip_to_image(data) == data
