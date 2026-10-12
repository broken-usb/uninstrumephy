from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QProgressBar, QCheckBox, QGroupBox, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from core.audio_recorder import (
    list_input_devices,
    list_output_devices,
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

    def __init__(self, parent=None, default_output_dir: str = "output/recordings") -> None:
        super().__init__(parent)
        self.setWindowTitle("Gravação Direta — ESP32-S3 / Microfone")
        self.resize(680, 410)
        self.output_dir = Path(default_output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.recorded_filepath: Optional[str] = None
        self.recorder_thread: Optional[AudioRecorderThread] = None
        self.monitor_thread: Optional[LiveMonitorThread] = None

        self._init_ui()
        self._refresh_device_list()
        # A UAC pode ser enumerada depois de o diálogo abrir. Atualizamos a
        # lista somente quando ela mudou e nunca durante gravação/monitor.
        self._device_refresh_timer = QTimer(self)
        self._device_refresh_timer.setInterval(2000)
        self._device_refresh_timer.timeout.connect(self._refresh_device_list_if_changed)
        self._device_refresh_timer.start()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 1. Seleção dos dispositivos. A Placa A fornece apenas a captura
        # UAC; o monitor é reproduzido em uma saída do computador.
        grp_dev = QGroupBox("Áudio da pedaleira e saída do computador")
        dev_layout = QVBoxLayout(grp_dev)
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("Entrada UAC:"))
        self.combo_devices = QComboBox()
        self.btn_refresh = QPushButton("🔄 Atualizar")
        self.btn_refresh.setFixedWidth(90)
        self.btn_refresh.clicked.connect(self._refresh_device_list)
        input_row.addWidget(self.combo_devices, 1)
        input_row.addWidget(self.btn_refresh)
        dev_layout.addLayout(input_row)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Saída para escutar:"))
        self.combo_outputs = QComboBox()
        output_row.addWidget(self.combo_outputs, 1)
        self.btn_monitor_toggle = QPushButton("▶ Monitorar ao vivo")
        self.btn_monitor_toggle.setToolTip(
            "Reproduz em tempo real o áudio processado recebido pela UAC da Placa A"
        )
        self.btn_monitor_toggle.clicked.connect(self._toggle_monitoring)
        output_row.addWidget(self.btn_monitor_toggle)
        dev_layout.addLayout(output_row)
        layout.addWidget(grp_dev)

        # 2. Configuração de Duração
        grp_dur = QGroupBox("Configuração da Gravação")
        l_dur = QHBoxLayout(grp_dur)
        l_dur.addWidget(QLabel("Duração:"))
        self.combo_duration = QComboBox()
        self.combo_duration.addItem("5 segundos", 5.0)
        self.combo_duration.addItem("10 segundos", 10.0)
        self.combo_duration.addItem("15 segundos (Recomendado)", 15.0)
        self.combo_duration.addItem("30 segundos", 30.0)
        self.combo_duration.addItem("Manual (Iniciar / Parar)", 0.0)
        self.combo_duration.setCurrentIndex(2)  # 15s padrão
        l_dur.addWidget(self.combo_duration, 1)
        layout.addWidget(grp_dur)

        # 3. Medidor VU e Temporizador
        grp_meter = QGroupBox("Nível de Entrada (Sinal) e Tempo")
        l_meter = QVBoxLayout(grp_meter)
        l_meter.setSpacing(6)

        self.lbl_timer = QLabel("Tempo: 00:00 / 00:15")
        self.lbl_timer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_timer.setStyleSheet("font-size: 13px; font-weight: bold;")
        l_meter.addWidget(self.lbl_timer)

        self.meter_bar = QProgressBar()
        self.meter_bar.setRange(0, 100)
        self.meter_bar.setValue(0)
        self.meter_bar.setTextVisible(False)
        self.meter_bar.setFixedHeight(16)
        self.meter_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid rgba(128, 128, 128, 0.4);
                border-radius: 4px;
                background-color: rgba(0, 0, 0, 0.08);
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #38a169, stop:0.75 #d69e2e, stop:0.95 #e53e3e);
                border-radius: 3px;
            }
        """)
        l_meter.addWidget(self.meter_bar)
        layout.addWidget(grp_meter)

        self.chk_auto_tone = QCheckBox("Pular Demucs e executar Tone Matching automaticamente")
        self.chk_auto_tone.setChecked(True)
        self.chk_auto_tone.setStyleSheet("font-weight: bold; color: #2b6cb0;")
        layout.addWidget(self.chk_auto_tone)

        # 4. Botões de Ação
        l_actions = QHBoxLayout()
        self.btn_record_toggle = QPushButton("🔴 Iniciar Gravação")
        self.btn_record_toggle.setStyleSheet("font-weight: bold; padding: 6px 14px;")
        self.btn_record_toggle.clicked.connect(self._toggle_recording)

        self.btn_accept = QPushButton("✅ Usar Gravação")
        self.btn_accept.setEnabled(False)
        self.btn_accept.clicked.connect(self._accept_recording)

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.reject)

        l_actions.addWidget(self.btn_record_toggle)
        l_actions.addWidget(self.btn_accept)
        l_actions.addWidget(self.btn_cancel)
        layout.addLayout(l_actions)

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
            prefix = "🎸 ESP32-S3: " if d["is_esp32"] else "🎙 "
            self.combo_devices.addItem(f"{prefix}{d['name']}", d["index"])
            if d["index"] == default_idx:
                selected_combo_idx = idx

        for idx, d in enumerate(outputs):
            self.combo_outputs.addItem(f"🔊 {d['name']}", d["index"])
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

    def _refresh_device_list_if_changed(self) -> None:
        if (self.recorder_thread is not None and self.recorder_thread.isRunning()) or (
            self.monitor_thread is not None and self.monitor_thread.isRunning()
        ):
            return
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
        self.btn_monitor_toggle.setText("⏹ Parar monitor")
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
        self.btn_monitor_toggle.setText("▶ Monitorar ao vivo")
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

        self.btn_record_toggle.setText("⏹ Parar Gravação")
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
        self.btn_record_toggle.setText("🔴 Gravar Novamente")
        self.btn_record_toggle.setEnabled(True)
        self.btn_accept.setEnabled(True)
        self.combo_devices.setEnabled(True)
        self.combo_duration.setEnabled(True)
        self.btn_refresh.setEnabled(True)

    def _on_record_error(self, err_msg: str) -> None:
        QMessageBox.critical(self, "Erro de Gravação", err_msg)
        self.meter_bar.setValue(0)
        self.lbl_timer.setText("Falha na Gravação")
        self.btn_record_toggle.setText("🔴 Iniciar Gravação")
        self.btn_record_toggle.setEnabled(True)
        self.combo_devices.setEnabled(True)
        self.combo_duration.setEnabled(True)
        self.btn_refresh.setEnabled(True)

    def _accept_recording(self) -> None:
        if self.recorded_filepath:
            auto_tone = self.chk_auto_tone.isChecked()
            self.recording_finished.emit(self.recorded_filepath, auto_tone)
            self.accept()

    def closeEvent(self, event) -> None:
        if hasattr(self, "_device_refresh_timer"):
            self._device_refresh_timer.stop()
        if self.monitor_thread is not None and self.monitor_thread.isRunning():
            self.monitor_thread.request_stop()
            self.monitor_thread.wait(1500)
        if self.recorder_thread is not None and self.recorder_thread.isRunning():
            self.recorder_thread.request_stop()
            self.recorder_thread.wait(1500)
        super().closeEvent(event)


# Alias para compatibilidade com importações em diferentes versões da interface.
DialogRecord = RecordDialog
