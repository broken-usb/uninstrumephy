from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QDialog, QPushButton, QMessageBox
from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal

from gui import icons, theme
from gui.ui_loader import load_ui_file
from core.audio_recorder import (
    list_input_devices,
    list_output_devices,
    refresh_devices,
    get_default_input_device_index,
    get_default_output_device_index,
    AudioRecorderThread,
    LiveMonitorThread,
)


class RecordDialog(QDialog):
    """
    Diálogo para captura direta de áudio a partir da ESP32-S3 ou microfone,
    com medidor VU em tempo real e opção de ir direto para o Tone Matching.
    """
    recording_finished = pyqtSignal(str, bool)  # (caminho_arquivo, auto_tone_matching)

    # (rótulo, duração em segundos; 0 = manual). O índice padrão é o de 15 s.
    DURATIONS: tuple[tuple[str, float], ...] = (
        ("5 segundos", 5.0),
        ("10 segundos", 10.0),
        ("15 segundos (Recomendado)", 15.0),
        ("30 segundos", 30.0),
        ("Manual (Iniciar / Parar)", 0.0),
    )
    DEFAULT_DURATION_INDEX = 2

    def __init__(self, parent=None, default_output_dir: str = "output/recordings") -> None:
        super().__init__(parent)
        self.output_dir = Path(default_output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.recorded_filepath: Optional[str] = None
        self.recorder_thread: Optional[AudioRecorderThread] = None
        self.monitor_thread: Optional[LiveMonitorThread] = None
        self._deletion_pending = False

        self._init_ui()
        # A placa pode ter sido conectada depois que o programa abriu: relê a
        # lista do sistema se o kernel registrou mudança de placas de som.
        refresh_devices(force=False)
        self._refresh_device_list()
        theme.on_change(self._refresh_icons)
        # A UAC pode ser enumerada depois de o diálogo abrir. Atualizamos a
        # lista somente quando ela mudou e nunca durante gravação/monitor.
        self._device_refresh_timer = QTimer(self)
        self._device_refresh_timer.setInterval(2000)
        self._device_refresh_timer.timeout.connect(self._refresh_device_list_if_changed)
        self._device_refresh_timer.start()

    def _init_ui(self) -> None:
        # Layout, textos, tamanhos e papéis visuais estão em gui/dialog_record.ui.
        # Aqui fica só o que depende de dados ou do tema: opções de duração,
        # ícones (recoloridos quando o tema muda) e conexões de sinais.
        load_ui_file("dialog_record.ui", self)

        for label, seconds in self.DURATIONS:
            self.combo_duration.addItem(label, seconds)
        self.combo_duration.setCurrentIndex(self.DEFAULT_DURATION_INDEX)

        self._set_action(self.btn_refresh, "Atualizar", "refresh")
        self._set_action(self.btn_monitor_toggle, "Monitorar ao vivo", "play")
        self._set_action(self.btn_record_toggle, "Iniciar Gravação", "record", "record")
        self._set_action(self.btn_accept, "Usar Gravação", "check", "accent")

        self.btn_refresh.clicked.connect(self._on_refresh_clicked)
        self.btn_monitor_toggle.clicked.connect(self._toggle_monitoring)
        self.btn_record_toggle.clicked.connect(self._toggle_recording)
        self.btn_accept.clicked.connect(self._accept_recording)
        self.btn_cancel.clicked.connect(self.reject)

    _ICON_ROLE = Qt.ItemDataRole.UserRole + 1

    def _set_action(self, button: QPushButton, text: str, icon_name: str, tone: str = "normal") -> None:
        """Define texto e ícone de um botão; o ícone é recolorido se o tema mudar."""
        button.setText(text)
        button.setProperty("icon_name", icon_name)
        button.setProperty("icon_tone", tone)
        button.setIcon(icons.icon(icon_name, tone))
        button.setIconSize(QSize(18, 18))

    def _refresh_icons(self) -> None:
        """Recolore os ícones dos botões e das listas quando o tema muda."""
        for btn in (self.btn_refresh, self.btn_monitor_toggle, self.btn_record_toggle, self.btn_accept):
            name = btn.property("icon_name")
            if name:
                btn.setIcon(icons.icon(name, btn.property("icon_tone") or "normal"))
        for combo in (self.combo_devices, self.combo_outputs):
            for i in range(combo.count()):
                name = combo.itemData(i, self._ICON_ROLE)
                if name:
                    combo.setItemIcon(i, icons.icon(name))

    def _refresh_device_list(self) -> None:
        self.combo_devices.clear()
        self.combo_outputs.clear()
        devices = list_input_devices()
        outputs = list_output_devices()
        self._input_names_by_index = {d["index"]: d["name"] for d in devices}
        self._output_names_by_index = {d["index"]: d["name"] for d in outputs}
        self._last_input_signature = tuple(
            (d["index"], d["name"], d["channels"], d["default_samplerate"]) for d in devices
        )
        self._last_output_signature = tuple(
            (d["index"], d["name"], d["channels"], d["default_samplerate"]) for d in outputs
        )
        default_idx = get_default_input_device_index()
        default_output = get_default_output_device_index()
        selected_combo_idx = 0
        selected_output_idx = 0

        for idx, d in enumerate(devices):
            label = f"ESP32-S3: {d['name']}" if d["is_esp32"] else d["name"]
            icon_name = "plug" if d["is_esp32"] else "microphone"
            self.combo_devices.addItem(icons.icon(icon_name), label, d["index"])
            self.combo_devices.setItemData(self.combo_devices.count() - 1, icon_name, self._ICON_ROLE)
            if d["index"] == default_idx:
                selected_combo_idx = idx

        for idx, d in enumerate(outputs):
            self.combo_outputs.addItem(icons.icon("speaker"), d["name"], d["index"])
            self.combo_outputs.setItemData(self.combo_outputs.count() - 1, "speaker", self._ICON_ROLE)
            if d["index"] == default_output:
                selected_output_idx = idx

        if self.combo_devices.count() > 0:
            self.combo_devices.setCurrentIndex(selected_combo_idx)
            self.btn_record_toggle.setEnabled(True)
        else:
            self.combo_devices.addItem("Nenhum dispositivo de entrada encontrado", None)
            self.btn_record_toggle.setEnabled(False)

        if self.combo_outputs.count() > 0:
            self.combo_outputs.setCurrentIndex(selected_output_idx)
            self.btn_monitor_toggle.setEnabled(self.combo_devices.currentData() is not None)
        else:
            self.combo_outputs.addItem("Nenhuma saída de áudio encontrada", None)
            self.btn_monitor_toggle.setEnabled(False)

    def _on_refresh_clicked(self) -> None:
        """Botão Atualizar: sempre relê a lista do sistema, não a cópia guardada."""
        refresh_devices(force=True)
        self._refresh_device_list()

    def _refresh_device_list_if_changed(self) -> None:
        if (self.recorder_thread is not None and self.recorder_thread.isRunning()) or (
            self.monitor_thread is not None and self.monitor_thread.isRunning()
        ):
            return
        # Leitura barata de /proc/asound/cards; o PortAudio só é reiniciado
        # (operação cara) quando uma placa foi conectada ou removida.
        refresh_devices(force=False)
        devices = list_input_devices()
        outputs = list_output_devices()
        input_signature = tuple(
            (d["index"], d["name"], d["channels"], d["default_samplerate"]) for d in devices
        )
        output_signature = tuple(
            (d["index"], d["name"], d["channels"], d["default_samplerate"]) for d in outputs
        )
        if (
            input_signature != getattr(self, "_last_input_signature", ())
            or output_signature != getattr(self, "_last_output_signature", ())
        ):
            self._refresh_device_list()

    def _toggle_monitoring(self) -> None:
        if self.monitor_thread is not None and self.monitor_thread.isRunning():
            self.btn_monitor_toggle.setText("Parando monitor…")
            self.btn_monitor_toggle.setEnabled(False)
            self.monitor_thread.request_stop()
            return

        input_idx = self.combo_devices.currentData()
        output_idx = self.combo_outputs.currentData()
        if input_idx is None or output_idx is None:
            QMessageBox.warning(self, "Monitoramento", "Selecione uma entrada e uma saída de áudio.")
            return
        if self.recorder_thread is not None and self.recorder_thread.isRunning():
            QMessageBox.information(
                self,
                "Gravação em andamento",
                "Pare a gravação antes de iniciar o monitoramento ao vivo.",
            )
            return

        self.monitor_thread = LiveMonitorThread(
            input_idx,
            output_idx,
            sample_rate=44100,
            input_name_hint=self._input_names_by_index.get(input_idx, ""),
            output_name_hint=self._output_names_by_index.get(output_idx, ""),
            parent=self,
        )
        self.monitor_thread.error.connect(self._on_monitor_error)
        self.monitor_thread.status_msg.connect(self._on_monitor_status)
        self.monitor_thread.level_meter.connect(
            lambda value: self.meter_bar.setValue(int(round(value)))
        )
        self.monitor_thread.finished.connect(self._on_monitor_finished)
        self.monitor_thread.start()
        self._set_action(self.btn_monitor_toggle, "Parar monitor", "stop")
        self.combo_devices.setEnabled(False)
        self.combo_outputs.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.btn_record_toggle.setEnabled(False)

    def _on_monitor_status(self, message: str) -> None:
        self.lbl_timer.setText(message)

    def _on_monitor_error(self, message: str) -> None:
        QMessageBox.critical(self, "Monitoramento ao vivo", message)
        self._restore_device_controls()

    def _on_monitor_finished(self) -> None:
        self._restore_device_controls()

    def _restore_device_controls(self) -> None:
        self._set_action(self.btn_monitor_toggle, "Monitorar ao vivo", "play")
        self.btn_monitor_toggle.setEnabled(
            self.combo_devices.currentData() is not None
            and self.combo_outputs.currentData() is not None
        )
        self.combo_devices.setEnabled(True)
        self.combo_outputs.setEnabled(True)
        self.btn_refresh.setEnabled(True)
        self.btn_record_toggle.setEnabled(self.combo_devices.currentData() is not None)

    def _toggle_recording(self) -> None:
        if self.monitor_thread is not None and self.monitor_thread.isRunning():
            QMessageBox.information(
                self,
                "Monitoramento em andamento",
                "Pare o monitoramento ao vivo antes de iniciar uma gravação.",
            )
            return
        if self.recorder_thread is not None and self.recorder_thread.isRunning():
            self.btn_record_toggle.setText("Parando…")
            self.btn_record_toggle.setEnabled(False)
            self.recorder_thread.request_stop()
            return

        device_idx = self.combo_devices.currentData()
        duration_s = float(self.combo_duration.currentData())

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = self.output_dir / f"guitar_esp_{timestamp}.wav"

        self.recorder_thread = AudioRecorderThread(
            output_filepath=str(target_path),
            device_index=device_idx,
            duration_s=duration_s,
            sample_rate=44100,
            channels=1,
            parent=self
        )
        self.recorder_thread.progress.connect(self._on_record_progress)
        self.recorder_thread.level_meter.connect(
            lambda value: self.meter_bar.setValue(int(round(value)))
        )
        self.recorder_thread.finished_recording.connect(self._on_record_finished)
        self.recorder_thread.error.connect(self._on_record_error)
        self.recorder_thread.status_msg.connect(self._on_record_status)

        self._set_action(self.btn_record_toggle, "Parar Gravação", "stop")
        self.btn_record_toggle.setEnabled(True)
        self.combo_devices.setEnabled(False)
        self.combo_duration.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.btn_accept.setEnabled(False)

        self.recorder_thread.start()

    def _on_record_progress(self, elapsed: float, total: float) -> None:
        mins_e, secs_e = divmod(int(elapsed), 60)
        if total > 0:
            mins_t, secs_t = divmod(int(total), 60)
            self.lbl_timer.setText(f"Tempo: {mins_e:02d}:{secs_e:02d} / {mins_t:02d}:{secs_t:02d}")
        else:
            self.lbl_timer.setText(f"Tempo: {mins_e:02d}:{secs_e:02d} (Manual)")

    def _on_record_status(self, message: str) -> None:
        if self.recorder_thread is not None and self.recorder_thread.isRunning():
            self.lbl_timer.setText(message)

    def _on_record_finished(self, filepath: str) -> None:
        self.recorded_filepath = filepath
        self.meter_bar.setValue(0)
        self.lbl_timer.setText("Gravação Concluída com Sucesso!")
        self._set_action(self.btn_record_toggle, "Gravar Novamente", "record", "record")
        self.btn_record_toggle.setEnabled(True)
        self.btn_accept.setEnabled(True)
        self.combo_devices.setEnabled(True)
        self.combo_duration.setEnabled(True)
        self.btn_refresh.setEnabled(True)

    def _on_record_error(self, err_msg: str) -> None:
        QMessageBox.critical(self, "Erro de Gravação", err_msg)
        self.meter_bar.setValue(0)
        self.lbl_timer.setText("Falha na Gravação")
        self._set_action(self.btn_record_toggle, "Iniciar Gravação", "record", "record")
        self.btn_record_toggle.setEnabled(True)
        self.combo_devices.setEnabled(True)
        self.combo_duration.setEnabled(True)
        self.btn_refresh.setEnabled(True)

    def _accept_recording(self) -> None:
        if self.recorded_filepath:
            auto_tone = self.chk_auto_tone.isChecked()
            self.recording_finished.emit(self.recorded_filepath, auto_tone)
            self.accept()

    # ------------------------------------------------------------------ #
    # Encerramento
    # ------------------------------------------------------------------ #
    # O QDialog pode ser fechado por quatro caminhos: botão Cancelar, tecla
    # Esc, "Usar Gravação" e o "X" da janela. Os três primeiros passam por
    # done() e NÃO disparam closeEvent(); por isso a limpeza fica em um único
    # método chamado pelos dois.

    def done(self, result: int) -> None:
        self._stop_workers()
        super().done(result)

    def closeEvent(self, event) -> None:
        self._stop_workers()
        super().closeEvent(event)

    def _running_workers(self) -> list:
        return [
            t for t in (self.monitor_thread, self.recorder_thread)
            if t is not None and t.isRunning()
        ]

    def _stop_workers(self) -> None:
        """Para o monitor ao vivo, a gravação e a atualização de dispositivos."""
        if hasattr(self, "_device_refresh_timer"):
            self._device_refresh_timer.stop()
        for thread in self._running_workers():
            thread.request_stop()
        for thread in self._running_workers():
            # Ambos verificam o pedido de parada a cada ~50–250 ms; o limite
            # evita travar a interface se o driver de áudio não responder.
            thread.wait(3000)

    def schedule_deletion(self) -> None:
        """Libera o diálogo da memória assim que nenhuma thread estiver rodando.

        As threads são filhas do diálogo: destruí-lo com uma delas ainda ativa
        derrubaria o aplicativo ("QThread: Destroyed while thread is still
        running"). Nesse caso raro, a exclusão espera a thread terminar.
        """
        running = self._running_workers()
        if not running:
            self.deleteLater()
            return
        if self._deletion_pending:
            return  # já aguardando; cada thread chamará de novo ao terminar
        self._deletion_pending = True
        for thread in running:
            thread.request_stop()
            thread.finished.connect(self._retry_deletion)

    def _retry_deletion(self) -> None:
        if not self._running_workers():
            self.deleteLater()


# Alias para compatibilidade com importações em diferentes versões da interface.
DialogRecord = RecordDialog