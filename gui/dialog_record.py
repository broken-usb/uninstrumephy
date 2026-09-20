from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QProgressBar, QCheckBox, QGroupBox, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.audio_recorder import (
    list_input_devices,
    get_default_input_device_index,
    AudioRecorderThread
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
        self.resize(500, 330)
        self.output_dir = Path(default_output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.recorded_filepath: Optional[str] = None
        self.recorder_thread: Optional[AudioRecorderThread] = None

        self._init_ui()
        self._refresh_device_list()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 1. Seleção do Dispositivo
        grp_dev = QGroupBox("Dispositivo de Entrada de Áudio")
        l_dev = QHBoxLayout(grp_dev)
        self.combo_devices = QComboBox()
        self.btn_refresh = QPushButton("🔄 Atualizar")
        self.btn_refresh.setFixedWidth(90)
        self.btn_refresh.clicked.connect(self._refresh_device_list)
        l_dev.addWidget(self.combo_devices, 1)
        l_dev.addWidget(self.btn_refresh)
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
        devices = list_input_devices()
        default_idx = get_default_input_device_index()
        selected_combo_idx = 0

        for idx, d in enumerate(devices):
            prefix = "🎸 ESP32-S3: " if d["is_esp32"] else "🎙 "
            self.combo_devices.addItem(f"{prefix}{d['name']}", d["index"])
            if d["index"] == default_idx:
                selected_combo_idx = idx

        if self.combo_devices.count() > 0:
            self.combo_devices.setCurrentIndex(selected_combo_idx)
            self.btn_record_toggle.setEnabled(True)
        else:
            self.combo_devices.addItem("Nenhum dispositivo de entrada encontrado", None)
            self.btn_record_toggle.setEnabled(False)

    def _toggle_recording(self) -> None:
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
        self.recorder_thread.level_meter.connect(self.meter_bar.setValue)
        self.recorder_thread.finished_recording.connect(self._on_record_finished)
        self.recorder_thread.error.connect(self._on_record_error)

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
        if self.recorder_thread is not None and self.recorder_thread.isRunning():
            self.recorder_thread.request_stop()
            self.recorder_thread.wait(1500)
        super().closeEvent(event)