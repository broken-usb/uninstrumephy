from __future__ import annotations

import logging
import time
import traceback
from pathlib import Path

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import QThread, pyqtSignal

from gui.ui_tab_demucs import Ui_TabDemucs
from core.separator import AudioSeparator

logger = logging.getLogger(__name__)


class DemucsWorker(QThread):
    """Executa a separação de faixas em uma thread separada da UI."""

    finished = pyqtSignal(str, str)   # guitar_path, stems_dir
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)

    def __init__(
        self,
        audio_path: str,
        model_name: str,
        device: str,
        shifts: int,
        overlap: float,
    ) -> None:
        super().__init__()
        self.audio_path = audio_path
        self.model_name = model_name
        self.device = device
        self.shifts = shifts
        self.overlap = overlap

    def run(self) -> None:
        start_time = time.monotonic()
        try:
            logger.info(
                f"Iniciando separação: {self.audio_path} "
                f"(model={self.model_name}, device={self.device}, "
                f"shifts={self.shifts}, overlap={self.overlap})"
            )

            separator = AudioSeparator(
                model_name=self.model_name,
                device=self.device,
                shifts=self.shifts,
                overlap=self.overlap,
            )
            logger.debug(f"Device de inferência efetivo: {separator.device}")

            guitar_path = separator.extract_guitar(
                self.audio_path,
                progress_cb=self.status.emit,
            )

            if not guitar_path:
                raise RuntimeError("Falha ao gerar stem de guitarra.")

            stems_dir = str(Path(guitar_path).parent)
            elapsed = time.monotonic() - start_time

            stems_found = sorted(p.name for p in Path(stems_dir).glob("*.wav"))
            logger.info(
                f"Separação concluída em {elapsed:.1f}s. "
                f"Stems gerados: {stems_found}"
            )
            self.finished.emit(guitar_path, stems_dir)

        except Exception:
            logger.exception("Erro durante separação.")
            self.error.emit(traceback.format_exc())


class TabDemucs(QWidget, Ui_TabDemucs):
    """
    Aba de separação de faixas via Demucs.

    Sinais emitidos para o main_gui.py orquestrar o restante da aplicação:
        separation_started()               — separação disparada
        separation_finished(str, str)      — (guitar_path, stems_dir)
        separation_error(str)              — mensagem de erro
        status_message(str)                — texto para a barra de status
    """

    separation_started  = pyqtSignal()
    separation_finished = pyqtSignal(str, str)
    separation_error    = pyqtSignal(str)
    status_message       = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        self.combo_demucs_model.addItems(AudioSeparator.AVAILABLE_MODELS)
        self.combo_demucs_model.setCurrentText(AudioSeparator.MODEL_NAME)

        self.combo_demucs_device.addItems(["auto", "cpu", "cuda"])
        self.combo_demucs_device.setCurrentText("auto")

        self.path_original: str = ""
        self.demucs_thread: DemucsWorker | None = None

        self.btn_run_demucs.clicked.connect(self.start_demucs)

    # API pública, chamada pelo main_gui.py

    def set_audio_path(self, path: str) -> None:
        """Define o arquivo de áudio a ser separado e habilita o botão."""
        self.path_original = path
        self.btn_run_demucs.setEnabled(bool(path))

    def reset(self) -> None:
        """Reseta o estado da aba (ex.: ao carregar um novo arquivo)."""
        self.path_original = ""
        self.btn_run_demucs.setEnabled(False)

    def set_busy(self, busy: bool) -> None:
        """Habilita/desabilita os controles da aba durante processamento."""
        self.btn_run_demucs.setEnabled(not busy and bool(self.path_original))
        self.combo_demucs_model.setEnabled(not busy)
        self.combo_demucs_device.setEnabled(not busy)
        self.spin_demucs_shifts.setEnabled(not busy)
        self.spin_demucs_overlap.setEnabled(not busy)

    # Lógica interna

    def start_demucs(self) -> None:
        if not self.path_original:
            logger.warning("Tentativa de iniciar Demucs sem arquivo carregado.")
            return

        model_name = self.combo_demucs_model.currentText()
        device_choice = self.combo_demucs_device.currentText()
        device = None if device_choice == "auto" else device_choice
        shifts = self.spin_demucs_shifts.value()
        overlap = self.spin_demucs_overlap.value()

        logger.info(
            f"Iniciando workflow Demucs (model={model_name}, "
            f"device={device_choice}, shifts={shifts}, overlap={overlap})."
        )
        self.set_busy(True)
        self.separation_started.emit()

        self.demucs_thread = DemucsWorker(
            self.path_original,
            model_name=model_name,
            device=device,
            shifts=shifts,
            overlap=overlap,
        )
        self.demucs_thread.status.connect(self.status_message.emit)
        self.demucs_thread.finished.connect(self._on_finished)
        self.demucs_thread.error.connect(self._on_error)
        self.demucs_thread.start()

    def _on_finished(self, guitar_path: str, stems_dir: str) -> None:
        logger.info("Workflow Demucs finalizado.")
        self.set_busy(False)
        self.separation_finished.emit(guitar_path, stems_dir)

    def _on_error(self, err_msg: str) -> None:
        logger.error(f"Erro na separação:\n{err_msg}")
        self.set_busy(False)
        self.separation_error.emit(err_msg)

    def stop_thread(self) -> None:
        """Encerra a thread de separação, se estiver rodando (usado no closeEvent)."""
        if self.demucs_thread is not None and self.demucs_thread.isRunning():
            self.demucs_thread.quit()
            self.demucs_thread.wait(2000)
