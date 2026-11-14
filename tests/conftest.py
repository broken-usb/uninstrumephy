"""Configuração comum dos testes.

- Interface sem janela (QT_QPA_PLATFORM=offscreen) e uma QApplication única.
- Dados dos testes (logs, gravações, presets) numa pasta temporária, nunca em output/.
- Se torch/demucs não estiverem instalados (máquina de desenvolvimento sem
  as dependências pesadas), eles são substituídos por módulos falsos, para
  que o resto da interface possa ser testado. No CI eles estão instalados e
  são usados de verdade.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Sem tela não há som a tocar. Fixar o backend de áudio do Qt evita que os
# testes dependam do áudio da máquina: com a biblioteca do PipeWire instalada
# sem a configuração dele (comum em servidores de CI), o player do Qt trava
# com falha de segmentação ao criar a janela principal.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_AUDIO_BACKEND", "alsa")
os.environ["UNINSTRUMEPHY_DATA_DIR"] = tempfile.mkdtemp(prefix="uninstrumephy-tests-")

if importlib.util.find_spec("torch") is None or importlib.util.find_spec("demucs") is None:
    for name in ("torch", "torchaudio", "demucs", "demucs.pretrained", "demucs.apply", "demucs.audio"):
        sys.modules.setdefault(name, mock.MagicMock(name=name))


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui import theme
    theme.install(app)
    return app


@pytest.fixture
def fake_sounddevice(monkeypatch):
    """`sounddevice` falso: uma entrada ESP32, uma saída e fluxos que só esperam parar."""
    import numpy as np

    sd = types.ModuleType("sounddevice")
    sd.DEVICES = [
        {"name": "ESP32-S3 Processed Audio: USB Audio (hw:2,0)", "max_input_channels": 1,
         "max_output_channels": 0, "default_samplerate": 44100},
        {"name": "Headphones (hw:3,0)", "max_input_channels": 0,
         "max_output_channels": 2, "default_samplerate": 44100},
    ]
    sd.default = types.SimpleNamespace(device=[0, 1])
    sd.query_devices = lambda index=None: sd.DEVICES if index is None else sd.DEVICES[index]
    sd.check_input_settings = lambda **kw: None
    sd.check_output_settings = lambda **kw: None
    sd._terminate = lambda: None
    sd._initialize = lambda: None

    class Stream:
        latency = (0.005, 0.005)

        def __init__(self, callback=None, **kw):
            sd.last_stream_kwargs = kw
            self.callback = callback

        def __enter__(self):
            indata = np.full((256, 1), 0.5, dtype=np.float32)
            outdata = np.zeros((256, kw_channels_out(sd)), dtype=np.float32)
            self.callback(indata, outdata, 256, None, None)
            sd.last_outdata = outdata
            return self

        def __exit__(self, *exc):
            return False

    def kw_channels_out(module):
        return module.last_stream_kwargs["channels"][1]

    class InputStream:
        def __init__(self, callback=None, **kw):
            self.callback = callback

        def __enter__(self):
            self.callback(np.full((1024, 1), 0.3, dtype=np.float32), 1024, None, None)
            return self

        def __exit__(self, *exc):
            return False

    sd.Stream, sd.InputStream = Stream, InputStream
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    return sd
