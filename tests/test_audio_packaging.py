"""Partes do áudio que dependem do ambiente (AppImage, bibliotecas do sistema)."""

import ctypes.util

import pytest

from core import audio_recorder


@pytest.fixture
def reset_fallback(monkeypatch):
    monkeypatch.setattr(audio_recorder, "_portaudio_fallback_installed", False)
    monkeypatch.setattr(ctypes.util, "find_library", ctypes.util.find_library)


def test_portaudio_embutida_usada_quando_o_sistema_nao_tem(reset_fallback, monkeypatch, tmp_path):
    bundled = tmp_path / "libportaudio.so.2"
    bundled.write_bytes(b"")
    monkeypatch.setenv("UNINSTRUMEPHY_PORTAUDIO", str(bundled))
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
    audio_recorder._install_portaudio_fallback()
    assert ctypes.util.find_library("portaudio") == str(bundled)
    assert ctypes.util.find_library("outra") is None


def test_portaudio_do_sistema_tem_preferencia(reset_fallback, monkeypatch, tmp_path):
    bundled = tmp_path / "libportaudio.so.2"
    bundled.write_bytes(b"")
    monkeypatch.setenv("UNINSTRUMEPHY_PORTAUDIO", str(bundled))
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: "libportaudio.so.2")
    audio_recorder._install_portaudio_fallback()
    assert ctypes.util.find_library("portaudio") == "libportaudio.so.2"


def test_sem_appimage_nada_muda(reset_fallback, monkeypatch):
    monkeypatch.delenv("UNINSTRUMEPHY_PORTAUDIO", raising=False)
    original = ctypes.util.find_library
    audio_recorder._install_portaudio_fallback()
    assert ctypes.util.find_library is original


def test_mensagem_quando_a_portaudio_falta():
    msg = audio_recorder._sounddevice_error_message(OSError("PortAudio library not found"))
    assert "PortAudio" in msg and "dnf install portaudio" in msg


def test_mensagem_quando_o_ffmpeg_falta():
    from gui.errors import describe_error
    tb = ("Traceback (most recent call last):\n"
          "FileNotFoundError: [Errno 2] No such file or directory: 'ffprobe'")
    info = describe_error(tb)
    assert "ffmpeg" in info.summary and "dnf install" in info.hint
