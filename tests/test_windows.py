"""Comportamento específico do Windows.

Rodam em qualquer sistema: o Windows é simulado (sys.platform = "win32" e um
`sounddevice` falso com os sistemas de áudio do Windows). No CI eles também
rodam num Windows de verdade.
"""

import logging
import sys
import types

import pytest

from core import audio_recorder, paths


# --------------------------------------------------------------------------- #
# Áudio: um único sistema de áudio (WASAPI)
# --------------------------------------------------------------------------- #

@pytest.fixture
def windows_sounddevice(monkeypatch, fake_sounddevice):
    """Pedaleira e fones listados por MME, DirectSound e WASAPI, como no Windows."""
    sd = fake_sounddevice
    monkeypatch.setattr(sys, "platform", "win32")
    sd.HOSTAPIS = [
        {"name": "MME", "default_input_device": 0, "default_output_device": 1},
        {"name": "Windows DirectSound", "default_input_device": 2, "default_output_device": 3},
        {"name": "Windows WASAPI", "default_input_device": 5, "default_output_device": 6},
    ]

    def dev(name, hostapi, ins, outs, rate=44100):
        return {"name": name, "hostapi": hostapi, "max_input_channels": ins,
                "max_output_channels": outs, "default_samplerate": rate}

    sd.DEVICES = [
        dev("Microfone (ESP32-S3 Processed A", 0, 1, 0),      # 0  MME corta em 31 caracteres
        dev("Fones de ouvido (Realtek(R) Aud", 0, 0, 2),     # 1
        dev("Microfone (ESP32-S3 Processed Audio)", 1, 1, 0),  # 2  DirectSound
        dev("Fones de ouvido (Realtek(R) Audio)", 1, 0, 2),  # 3
        dev("Microfone (Realtek(R) Audio)", 2, 2, 0, 48000),  # 4  WASAPI
        dev("Microfone (ESP32-S3 Processed Audio)", 2, 1, 0),  # 5
        dev("Fones de ouvido (Realtek(R) Audio)", 2, 0, 2, 48000),  # 6
    ]
    sd.default = types.SimpleNamespace(device=[0, 1])  # padrão do PortAudio = MME
    sd.query_hostapis = lambda index=None: sd.HOSTAPIS if index is None else sd.HOSTAPIS[index]

    class WasapiSettings:
        def __init__(self, exclusive=False, auto_convert=False):
            self.exclusive, self.auto_convert = exclusive, auto_convert

    sd.WasapiSettings = WasapiSettings
    return sd


def test_windows_lista_cada_dispositivo_uma_vez_so_no_wasapi(windows_sounddevice):
    inputs = audio_recorder.list_input_devices()
    outputs = audio_recorder.list_output_devices()
    assert [d["index"] for d in inputs] == [4, 5]
    assert [d["index"] for d in outputs] == [6]
    assert [d["name"] for d in inputs if d["is_esp32"]] == ["Microfone (ESP32-S3 Processed Audio)"]


def test_windows_padroes_vem_do_wasapi_e_nao_do_mme(windows_sounddevice):
    assert audio_recorder.get_default_input_device_index() == 5   # a pedaleira, no WASAPI
    assert audio_recorder.get_default_output_device_index() == 6  # padrão do WASAPI, não o 1 (MME)


def test_windows_wasapi_converte_a_taxa_automaticamente(windows_sounddevice):
    extra = audio_recorder._extra_settings(windows_sounddevice, 6)
    assert extra is not None and extra.auto_convert and not extra.exclusive
    assert audio_recorder._extra_settings(windows_sounddevice, 1) is None  # MME não precisa


def test_windows_monitor_abre_entrada_e_saida_no_wasapi(qapp, windows_sounddevice):
    sd = windows_sounddevice
    monitor = audio_recorder.LiveMonitorThread(
        5, 6,
        input_name_hint="Microfone (ESP32-S3 Processed Audio)",
        output_name_hint="Fones de ouvido (Realtek(R) Audio)",
    )
    errors = []
    monitor.error.connect(errors.append)

    class StreamQueParaAoAbrir(sd.Stream):
        def __enter__(self):
            monitor.request_stop()  # encerra o laço logo depois de o fluxo abrir
            return super().__enter__()

    sd.Stream = StreamQueParaAoAbrir
    monitor.run()  # síncrono: o fluxo falso só registra os argumentos
    assert not errors
    kwargs = sd.last_stream_kwargs
    assert kwargs["device"] == (5, 6)
    assert all(s.auto_convert for s in kwargs["extra_settings"])


def test_windows_reencontra_a_pedaleira_com_prefixo_2(windows_sounddevice):
    # Após reconectar, o Windows pode renomear para "Microfone (2- ESP32-...)".
    sd = windows_sounddevice
    sd.DEVICES[5] = dict(sd.DEVICES[5], name="Microfone (2- ESP32-S3 Processed Audio)")
    found = audio_recorder.LiveMonitorThread._find_device_index(
        sd, "Microfone (ESP32-S3 Processed Audio)", True)
    assert found == 5  # e não 0 ou 2 (mesmo dispositivo em MME/DirectSound)


@pytest.mark.parametrize("name, key", [
    ("ESP32-S3 Processed Audio: USB Audio (hw:2,0)", "esp32-s3 processed audio"),
    ("Microfone (2- ESP32-S3 Processed Audio)", "microfone (esp32-s3 processed audio)"),
    ("Microfone (ESP32-S3 Processed Audio)", "microfone (esp32-s3 processed audio)"),
])
def test_chave_estavel_do_nome_do_dispositivo(name, key):
    assert audio_recorder._device_key(name) == key


def test_erro_de_dispositivo_invalido_permite_nova_tentativa():
    class PortAudioError(Exception):
        pass
    assert audio_recorder._is_retryable(PortAudioError("Invalid device", -9996))
    assert audio_recorder._is_retryable(PortAudioError("Device unavailable", -9985))
    assert not audio_recorder._is_retryable(PortAudioError("Invalid sample rate", -9997))


def test_sem_assinatura_releitura_as_cegas_respeita_o_intervalo(monkeypatch, fake_sounddevice):
    calls = []
    fake_sounddevice._terminate = lambda: calls.append("terminate")
    monkeypatch.setattr(audio_recorder, "_sound_cards_signature", lambda: None)
    monkeypatch.setattr(audio_recorder, "_last_refresh", 0.0)
    assert audio_recorder.refresh_devices(force=False) is False          # sem intervalo: nada
    assert audio_recorder.refresh_devices(force=False, blind_interval=2.0) is True
    assert audio_recorder.refresh_devices(force=False, blind_interval=2.0) is False  # cedo demais
    assert calls == ["terminate"]


# --------------------------------------------------------------------------- #
# Pastas
# --------------------------------------------------------------------------- #

@pytest.fixture
def clean_paths(monkeypatch, tmp_path):
    for var in ("UNINSTRUMEPHY_DATA_DIR", "APPIMAGE", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    return tmp_path


def test_windows_empacotado_usa_localappdata(clean_paths, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.data_dir() == clean_paths / "AppData" / "Local" / "uninstrumephy"


def test_pasta_do_programa_sem_escrita_conta_como_empacotado(clean_paths, monkeypatch):
    monkeypatch.setattr(paths, "_project_is_writable", lambda: False)
    assert paths.is_packaged()


def test_pasta_do_programa_testada_criando_arquivo_de_verdade(tmp_path, monkeypatch):
    paths._project_is_writable.cache_clear()
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    try:
        assert paths._project_is_writable() is True
        assert list(tmp_path.iterdir()) == []  # o arquivo de teste não fica para trás
    finally:
        paths._project_is_writable.cache_clear()


# --------------------------------------------------------------------------- #
# Mensagens de erro e log
# --------------------------------------------------------------------------- #

WINDOWS_FFPROBE_TB = (
    "Traceback (most recent call last):\n"
    '  File "C:\\Users\\Joao\\uninstrumephy\\.venv\\Lib\\site-packages\\demucs\\audio.py", '
    "line 21, in _read_info\n"
    "    stdout_data = sp.check_output([\n"
    '  File "C:\\Python312\\Lib\\subprocess.py", line 1538, in _execute_child\n'
    "    hp, ht, pid, tid = _winapi.CreateProcess(executable, args,\n"
    "FileNotFoundError: [WinError 2] O sistema não pode encontrar o arquivo especificado"
)


def test_windows_ffmpeg_ausente_e_reconhecido(monkeypatch):
    from gui.errors import describe_error
    monkeypatch.setattr(sys, "platform", "win32")
    info = describe_error(WINDOWS_FFPROBE_TB)
    assert "ffmpeg" in info.summary and "winget install Gyan.FFmpeg" in info.hint


def test_windows_outro_arquivo_ausente_nao_vira_ffmpeg(monkeypatch):
    from gui.errors import describe_error
    monkeypatch.setattr(sys, "platform", "win32")
    tb = WINDOWS_FFPROBE_TB.replace("demucs\\audio.py", "core\\analyzer.py")
    assert "ffmpeg" not in describe_error(tb).summary


def test_log_sem_console_grava_so_no_arquivo(monkeypatch, tmp_path):
    # pythonw.exe (Windows, sem console): sys.stdout é None.
    from core.logger import setup_logging
    monkeypatch.setattr(sys, "stdout", None)
    root = setup_logging(tmp_path)
    try:
        logging.getLogger("teste").info("Aplicação inicializada — çãõ")
        assert all(isinstance(h, logging.FileHandler) for h in root.handlers)
        text = (tmp_path / "latest-log.txt").read_text(encoding="utf-8")
        assert "Aplicação inicializada — çãõ" in text
    finally:
        for handler in list(root.handlers):
            handler.close()
            root.removeHandler(handler)


# --------------------------------------------------------------------------- #
# Porta serial e tema
# --------------------------------------------------------------------------- #

def test_dtr_e_rts_desligados_antes_de_abrir_a_porta(monkeypatch):
    from core import hardware as hw

    events = []

    class FakeSerial:
        def __init__(self, **kwargs):
            self._dtr = self._rts = True

        def __setattr__(self, name, value):
            if name in ("dtr", "rts"):
                events.append((name, value))
            object.__setattr__(self, name, value)

        def open(self):
            events.append(("open", None))

        def reset_input_buffer(self):
            pass

    monkeypatch.setattr(hw.serial, "Serial", FakeSerial)
    monkeypatch.setattr(hw.ESP32Link, "BOOT_DELAY_S", 0)
    hw.ESP32Link(port="COM5").connect()
    assert events.index(("open", None)) > events.index(("dtr", False))
    assert events.index(("open", None)) > events.index(("rts", False))


def test_tema_funciona_com_espaco_no_caminho_dos_icones(qapp, monkeypatch, tmp_path):
    # No Windows, a pasta temporária fica dentro da pasta do usuário, e
    # "C:/Users/João Silva/..." tem espaço. Sem aspas no url(), o Qt descartava
    # a folha de estilo inteira (o programa abria sem tema).
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QCheckBox
    from gui import theme
    folder = tmp_path / "João Silva" / "Temp"
    folder.mkdir(parents=True)
    monkeypatch.setattr(theme, "_icon_cache", folder)
    theme.apply(qapp, "light")
    try:
        assert f'url("{folder.as_posix()}/light/check.svg")' in qapp.styleSheet()
        box = QCheckBox("x")
        box.setChecked(True)
        box.show()
        qapp.processEvents()
        img = box.grab().toImage()
        accent = QColor(theme.tokens().accent).name()
        # O indicador marcado é pintado com a cor de destaque do tema.
        assert any(QColor(img.pixel(x, y)).name() == accent
                   for x in range(img.width()) for y in range(img.height()))
    finally:
        monkeypatch.undo()
        theme.apply(qapp, "system")
