import sys
import os
import logging
import traceback

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox
)

from PyQt6.QtCore import (
    QThread,
    pyqtSignal,
    QUrl
)

from PyQt6.QtGui import (
    QPixmap,
    QImage
)

from PyQt6.QtMultimedia import (
    QMediaPlayer,
    QAudioOutput
)

from tinytag import TinyTag

from gui.ui_mainwindow import Ui_Dialog
from core.separator import AudioSeparator
from core.analyzer import AudioAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s -> %(message)s"
)

logger = logging.getLogger(__name__)

# DEMUCS
class DemucsWorker(QThread):

    finished = pyqtSignal(str, str)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, separator, audio_path):

        super().__init__()

        self.separator = separator
        self.audio_path = audio_path

    def run(self):

        try:

            logger.info(
                f"Iniciando separação: {self.audio_path}"
            )

            self.status.emit(
                "Iniciando IA (Demucs)..."
            )

            guitar_path = self.separator.extract_guitar(
                self.audio_path
            )

            if guitar_path:

                stems_dir = os.path.dirname(
                    guitar_path
                )

                logger.info(
                    "Separação concluída."
                )

                self.finished.emit(
                    guitar_path,
                    stems_dir
                )

            else:

                raise RuntimeError(
                    "Falha ao gerar stem de guitarra."
                )

        except Exception:

            erro = traceback.format_exc()

            logger.exception(
                "Erro durante separação."
            )

            self.error.emit(erro)

# LIBROSA
class AnalysisWorker(QThread):

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, guitar_path):

        super().__init__()

        self.guitar_path = guitar_path

    def run(self):

        try:

            logger.info(
                f"Iniciando análise: {self.guitar_path}"
            )

            self.status.emit(
                "Extraindo parâmetros matemáticos..."
            )

            analyzer = AudioAnalyzer()

            params = analyzer.analyze_guitar(
                self.guitar_path
            )

            logger.info(
                "Análise concluída."
            )

            self.finished.emit(params)

        except Exception:

            erro = traceback.format_exc()

            logger.exception(
                "Erro durante análise."
            )

            self.error.emit(erro)

# JANELA
class MainWindow(QDialog, Ui_Dialog):

    def __init__(self):

        super().__init__()

        self.setupUi(self)

        logger.info("Inicializando aplicação...")

        self.path_original = ""
        self.path_guitarra = ""
        self.path_stems_dir = ""

        self.separator = AudioSeparator()

        self.audio_out_orig = QAudioOutput()

        self.audio_out_orig.setVolume(
            self.slider_vol_orig.value() / 100.0
        )

        self.player_orig = QMediaPlayer()

        self.player_orig.setAudioOutput(
            self.audio_out_orig
        )

        self.audio_out_stem = QAudioOutput()

        self.audio_out_stem.setVolume(
            self.slider_vol_stem.value() / 100.0
        )

        self.player_stem = QMediaPlayer()

        self.player_stem.setAudioOutput(
            self.audio_out_stem
        )

        self.btn_load.clicked.connect(
            self.load_audio_file
        )

        self.btn_run_demucs.clicked.connect(
            self.start_demucs
        )

        self.btn_run_analysis.clicked.connect(
            self.start_analysis
        )

        self.slider_vol_orig.valueChanged.connect(
            lambda v: self.audio_out_orig.setVolume(
                v / 100.0
            )
        )

        self.btn_play_orig.clicked.connect(
            self.play_original
        )

        self.btn_stop_orig.clicked.connect(
            self.stop_original
        )

        self.slider_vol_stem.valueChanged.connect(
            lambda v: self.audio_out_stem.setVolume(
                v / 100.0
            )
        )

        self.btn_play_guitar.clicked.connect(
            self.play_stem
        )

        self.btn_stop_guitar.clicked.connect(
            self.stop_stem
        )

        self.player_orig.durationChanged.connect(
            lambda d: self.slider_seek_orig.setMaximum(d)
        )

        self.player_orig.positionChanged.connect(
            lambda p: self.slider_seek_orig.setValue(p)
        )

        self.slider_seek_orig.sliderMoved.connect(
            lambda p: self.player_orig.setPosition(p)
        )

        self.player_stem.durationChanged.connect(
            lambda d: self.slider_seek_stem.setMaximum(d)
        )

        self.player_stem.positionChanged.connect(
            lambda p: self.slider_seek_stem.setValue(p)
        )

        self.slider_seek_stem.sliderMoved.connect(
            lambda p: self.player_stem.setPosition(p)
        )

        logger.info("Aplicação inicializada.")

    def load_audio_file(self):

        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Selecione a Música",
            "",
            "Audio Files (*.mp3 *.wav *.flac)"
        )

        if not file_name:
            return

        logger.info(
            f"Arquivo carregado: {file_name}"
        )

        self.path_original = file_name

        self.lbl_filepath.setText(
            f"Arquivo: {os.path.basename(file_name)}"
        )

        try:

            tag = TinyTag.get(
                file_name,
                image=True
            )

            titulo = tag.title or "Desconhecido"
            artista = tag.artist or "Desconhecido"
            album = tag.album or "Desconhecido"

            self.lbl_metadata.setText(
                f"Música: {titulo}\n"
                f"Artista: {artista}\n"
                f"Álbum: {album}"
            )

            img_data = tag.get_image()

            if img_data:

                img = QImage()

                img.loadFromData(img_data)

                self.lbl_cover.setPixmap(
                    QPixmap(img)
                )

            else:

                self.lbl_cover.setText(
                    "Capa não disponível"
                )

        except Exception:

            logger.exception(
                "Falha ao ler metadados."
            )

            self.lbl_metadata.setText(
                "Sem metadados."
            )

            self.lbl_cover.setText(
                "Sem capa."
            )

        self.btn_play_orig.setEnabled(True)
        self.btn_stop_orig.setEnabled(True)

        self.btn_run_demucs.setEnabled(True)

        self.btn_run_analysis.setEnabled(False)

        self.btn_play_guitar.setEnabled(False)
        self.btn_stop_guitar.setEnabled(False)

        self.combo_stems.setEnabled(False)

        self.lbl_status.setText(
            "Status: Música carregada."
        )

        self.progress_bar.setValue(0)

    def start_demucs(self):

        logger.info(
            "Iniciando workflow Demucs."
        )

        self.btn_run_demucs.setEnabled(False)
        self.btn_load.setEnabled(False)

        self.progress_bar.setRange(0, 0)

        self.demucs_thread = DemucsWorker(
            self.separator,
            self.path_original
        )

        self.demucs_thread.status.connect(
            self.update_status
        )

        self.demucs_thread.finished.connect(
            self.on_demucs_finished
        )

        self.demucs_thread.error.connect(
            self.on_error
        )

        self.demucs_thread.start()

    def on_demucs_finished(
        self,
        guitar_path,
        stems_dir
    ):

        logger.info(
            "Workflow Demucs finalizado."
        )

        self.path_guitarra = guitar_path
        self.path_stems_dir = stems_dir

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        self.lbl_status.setText(
            "Status: Faixas separadas!"
        )

        self.btn_load.setEnabled(True)

        self.btn_play_guitar.setEnabled(True)
        self.btn_stop_guitar.setEnabled(True)

        self.combo_stems.setEnabled(True)

        self.btn_run_analysis.setEnabled(True)

    def start_analysis(self):

        logger.info(
            "Iniciando workflow análise."
        )

        self.btn_run_analysis.setEnabled(False)
        self.btn_load.setEnabled(False)

        self.progress_bar.setRange(0, 0)

        self.analysis_thread = AnalysisWorker(
            self.path_guitarra
        )

        self.analysis_thread.status.connect(
            self.update_status
        )

        self.analysis_thread.finished.connect(
            self.on_analysis_finished
        )

        self.analysis_thread.error.connect(
            self.on_error
        )

        self.analysis_thread.start()

    def on_analysis_finished(self, params):

        logger.info(
            "Workflow análise finalizado."
        )

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        self.lbl_status.setText(
            "Status: Parâmetros calculados!"
        )

        self.btn_load.setEnabled(True)

        gate = params.get(
            "noise_gate_threshold_db",
            "--"
        )

        eq = params.get("eq", {})

        self.lbl_gate.setText(
            f"Threshold: {gate} dB"
        )

        self.lbl_eq.setText(
            f"EQ: "
            f"B({eq.get('bass')}) | "
            f"M({eq.get('mid')}) | "
            f"T({eq.get('treble')})"
        )

    def update_status(self, msg):

        logger.info(msg)

        self.lbl_status.setText(
            f"Status: {msg}"
        )

    def on_error(self, err_msg):

        logger.error(
            "Erro recebido pela UI."
        )

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.lbl_status.setText(
            "Status: Erro no processamento."
        )

        self.btn_load.setEnabled(True)
        self.btn_run_demucs.setEnabled(True)

        QMessageBox.critical(
            self,
            "Erro",
            err_msg
        )

    def play_original(self):

        if not self.path_original:
            return

        logger.info(
            "Reproduzindo música original."
        )

        self.player_orig.stop()

        self.player_orig.setSource(
            QUrl.fromLocalFile(
                self.path_original
            )
        )

        self.player_orig.play()

    def stop_original(self):

        logger.info(
            "Parando música original."
        )

        self.player_orig.stop()

    def play_stem(self):

        if not self.path_stems_dir:
            return

        faixa = self.combo_stems.currentText()

        stem_file = os.path.join(
            self.path_stems_dir,
            f"{faixa}.wav"
        )

        if not os.path.exists(stem_file):

            QMessageBox.warning(
                self,
                "Aviso",
                f"A faixa {faixa}.wav não foi encontrada."
            )

            return

        logger.info(
            f"Reproduzindo stem: {stem_file}"
        )

        self.player_stem.stop()

        self.player_stem.setSource(
            QUrl.fromLocalFile(stem_file)
        )

        self.player_stem.play()

    def stop_stem(self):

        logger.info(
            "Parando stem."
        )

        self.player_stem.stop()

if __name__ == "__main__":

    logger.info("Inicializando QApplication...")

    app = QApplication(sys.argv)

    window = MainWindow()

    window.show()

    sys.exit(app.exec())