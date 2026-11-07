"""Interface: carregamento dos .ui, diálogo de gravação e abas."""

import time

import pytest
from PyQt6.QtWidgets import QMessageBox, QWidget


def _pump(app, seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def test_janela_principal_monta_pelos_ui(qapp):
    import main
    win = main.MainWindow()
    assert win.tabsMain.count() == 3
    assert len(win.tab_hardware.effect_widgets) == 12
    assert (win.lbl_cover.width(), win.lbl_cover.height()) == (158, 158)


def test_icones_do_tema_em_pasta_propria_da_execucao(qapp):
    # Uma pasta fixa em /tmp, compartilhada entre usuários, impedia o
    # programa de abrir para o segundo usuário (PermissionError).
    import os
    import tempfile
    from pathlib import Path
    from gui import theme
    theme.install(qapp)
    folder = theme._icon_cache_dir()
    assert folder == theme._icon_cache_dir()  # a mesma durante toda a execução
    assert folder != Path(tempfile.gettempdir()) / "uninstrumephy_theme"
    assert folder.stat().st_uid == os.getuid() and any(folder.rglob("*.svg"))


def test_ui_em_classe_errada_da_erro_claro(qapp):
    from gui.ui_loader import UiLoadError, load_ui_file
    with pytest.raises(UiLoadError, match="QDialog"):
        load_ui_file("mainwindow.ui", QWidget())


def test_faixa_da_guitarra_e_selecionada_apos_separacao(qapp, tmp_path):
    import main
    win = main.MainWindow()
    for name in ("bass", "drums", "other", "vocals"):
        (tmp_path / f"{name}.wav").write_bytes(b"")
    win.path_guitarra = str(tmp_path / "other.wav")  # modelo de 4 faixas
    win.path_stems_dir = str(tmp_path)
    win._populate_stems_combo(str(tmp_path))
    assert win.combo_stems.currentText() == "other"


def test_modelos_de_4_faixas_usam_other(monkeypatch):
    from core.separator import AudioSeparator
    sep = object.__new__(AudioSeparator)
    sep.model_name = "htdemucs"
    sep.model = type("M", (), {"sources": ["drums", "bass", "other", "vocals"]})()
    asked = []
    monkeypatch.setattr(sep, "extract_stem", lambda path, stem_name, **kw: asked.append(stem_name) or stem_name)
    assert sep.extract_guitar("musica.mp3") == "other"
    sep.model.sources = ["drums", "bass", "other", "vocals", "guitar", "piano"]
    assert sep.extract_guitar("musica.mp3") == "guitar"


@pytest.mark.parametrize("close", ["cancel", "accept_path", "x"])
def test_fechar_dialogo_para_o_monitor(qapp, fake_sounddevice, tmp_path, close, monkeypatch):
    from gui.dialog_record import RecordDialog

    class SlowStream(fake_sounddevice.Stream):
        def __enter__(self):  # fica aberto até o pedido de parada
            return self
    monkeypatch.setattr(fake_sounddevice, "Stream", SlowStream)

    dlg = RecordDialog(None, default_output_dir=tmp_path)
    assert "ESP32" in dlg.combo_devices.currentText()
    dlg._toggle_monitoring()
    _pump(qapp)
    assert dlg.monitor_thread.isRunning()
    {"cancel": dlg.btn_cancel.click, "accept_path": lambda: dlg.done(1), "x": dlg.close}[close]()
    _pump(qapp)
    assert not dlg.monitor_thread.isRunning()


def test_erro_de_envio_mostra_uma_unica_caixa(qapp, monkeypatch):
    import main
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()) or 0)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[2]) or 0)
    win = main.MainWindow()
    win.tab_hardware._on_send_error("A Placa A rejeitou o comando CDC (status 3).")
    assert len(shown) == 1 and "rejeitou" in shown[0]
