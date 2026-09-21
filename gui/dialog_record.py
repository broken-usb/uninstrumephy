import os
import tempfile
import wave
from pathlib import Path

from PyQt6.QtWidgets import QDialog, QMessageBox
from PyQt6.QtCore import pyqtSignal, QTimer, QTime

try:
    import sounddevice as sd
except ImportError:
    sd = None

from gui.ui_dialog_record import Ui_DialogRecord


class DialogRecord(QDialog, Ui_DialogRecord):
    # Sinal esperado pelo main_gui para receber o caminho do áudio gravado
    recording_finished = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.is_recording = False
        self.recorded_frames = []
        self.output_filepath = ""
        self.stream = None

        self.time = QTime(0, 0, 0)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_timer)

        self._populate_audio_devices()
        self._setup_signals()

    def _setup_signals(self):
        self.btnRecord.clicked.connect(self._start_recording)
        self.btnStop.clicked.connect(self._stop_recording)
        self.btnSave.clicked.connect(self._save_and_close)

        self.btnStop.setEnabled(False)
        self.btnSave.setEnabled(False)

    def _populate_audio_devices(self):
        self.comboDevice.clear()
        if sd is None:
            self.comboDevice.addItem("sounddevice não instalado")
            return

        try:
            devices = sd.query_devices()
            input_devices = [
                (idx, d["name"])
                for idx, d in enumerate(devices)
                if d.get("max_input_channels", 0) > 0
            ]
            if not input_devices:
                self.comboDevice.addItem("Nenhum microfone encontrado")
                return

            for dev_idx, dev_name in input_devices:
                self.comboDevice.addItem(f"[{dev_idx}] {dev_name}", userData=dev_idx)
        except Exception:
            self.comboDevice.addItem("Erro ao listar dispositivos")

        if hasattr(self, "comboSampleRate"):
            self.comboSampleRate.clear()
            self.comboSampleRate.addItems(["44100", "48000"])

    def _audio_callback(self, indata, frames, time_info, status):
        if self.is_recording:
            self.recorded_frames.append(indata.copy())

    def _start_recording(self):
        if sd is None:
            QMessageBox.critical(self, "Erro", "Biblioteca 'sounddevice' não instalada.")
            return

        device_idx = self.comboDevice.currentData()
        sample_rate = int(self.comboSampleRate.currentText()) if hasattr(self, "comboSampleRate") and self.comboSampleRate.currentText() else 44100

        try:
            self.recorded_frames = []
            self.stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                device=device_idx,
                callback=self._audio_callback,
            )
            self.stream.start()
            self.is_recording = True

            self.time = QTime(0, 0, 0)
            self.labelTimer.setText("00:00.00")
            self.timer.start(1000)

            self.btnRecord.setEnabled(False)
            self.btnStop.setEnabled(True)
            self.btnSave.setEnabled(False)
        except Exception as exc:
            QMessageBox.critical(self, "Falha na Gravação", f"Não foi possível abrir o dispositivo de áudio:\n{exc}")

    def _stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        self.timer.stop()

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        self.btnRecord.setEnabled(True)
        self.btnStop.setEnabled(False)
        self.btnSave.setEnabled(len(self.recorded_frames) > 0)

    def _update_timer(self):
        self.time = self.time.addSecs(1)
        self.labelTimer.setText(self.time.toString("mm:ss.00"))

    def _save_and_close(self):
        if not self.recorded_frames:
            self.reject()
            return

        try:
            import numpy as np

            audio_data = np.concatenate(self.recorded_frames, axis=0)
            temp_dir = tempfile.gettempdir()
            self.output_filepath = os.path.join(temp_dir, "guitar_direct_input.wav")
            sample_rate = int(self.comboSampleRate.currentText()) if hasattr(self, "comboSampleRate") and self.comboSampleRate.currentText() else 44100

            with wave.open(self.output_filepath, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit PCM
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data.tobytes())

            # Notifica o main_gui com o arquivo salvo
            self.recording_finished.emit(self.output_filepath)
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao Salvar", f"Não foi possível gravar o arquivo WAV:\n{exc}")

    def closeEvent(self, event):
        self._stop_recording()
        event.accept()


# Alias para retrocompatibilidade de importação
RecordDialog = DialogRecord