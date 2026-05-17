import sys
import logging
import traceback
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from tinytag import TinyTag

from gui.ui_mainwindow import Ui_Dialog
from core.separator import AudioSeparator
from core.analyzer import AudioAnalyzer

# Logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s -> %(message)s",
)
logger = logging.getLogger(__name__)


# Demucs worker

class DemucsWorker(QThread):

    finished = pyqtSignal(str, str)   # guitar_path, stems_dir
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)

    def __init__(self, separator: AudioSeparator, audio_path: str) -> None:
        super().__init__()
        self.separator  = separator
        self.audio_path = audio_path

    def run(self) -> None:
        try:
            logger.info(f"Iniciando separação: {self.audio_path}")

            # Usa status.emit como callback de progresso
            guitar_path = self.separator.extract_guitar(
                self.audio_path,
                progress_cb=self.status.emit,
            )

            if not guitar_path:
                raise RuntimeError("Falha ao gerar stem de guitarra.")

            stems_dir = str(Path(guitar_path).parent)
            logger.info("Separação concluída.")
            self.finished.emit(guitar_path, stems_dir)

        except Exception:
            logger.exception("Erro durante separação.")
            self.error.emit(traceback.format_exc())


# Analysis worker

class AnalysisWorker(QThread):

    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)

    def __init__(self, guitar_path: str) -> None:
        super().__init__()
        self.guitar_path = guitar_path

    def run(self) -> None:
        try:
            logger.info(f"Iniciando análise: {self.guitar_path}")
            self.status.emit("Extraindo parâmetros matemáticos…")

            params = AudioAnalyzer().analyze_stem(self.guitar_path)

            logger.info("Análise concluída.")
            self.finished.emit(params)

        except Exception:
            logger.exception("Erro durante análise.")
            self.error.emit(traceback.format_exc())


# Main window

class MainWindow(QDialog, Ui_Dialog):

    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        logger.info("Inicializando aplicação…")

        # Paths
        self.path_original:  str = ""
        self.path_guitarra:  str = ""
        self.path_stems_dir: str = ""

        # Separador (cache do modelo)
        self.separator = AudioSeparator()

        # Players e saídas
        self.audio_out_orig = QAudioOutput()
        self.player_orig    = QMediaPlayer()
        self.player_orig.setAudioOutput(self.audio_out_orig)

        self.audio_out_stem = QAudioOutput()
        self.player_stem    = QMediaPlayer()
        self.player_stem.setAudioOutput(self.audio_out_stem)

        # Conecta sinais
        self._connect_signals()

        # Volume inicial
        self._apply_master_volume()

        logger.info("Aplicação inicializada.")

    # Conexão de sinais

    def _connect_signals(self) -> None:
        self.btn_load.clicked.connect(self.load_audio_file)
        self.btn_run_demucs.clicked.connect(self.start_demucs)
        self.btn_run_analysis.clicked.connect(self.start_analysis)

        # Atualiza volumes
        self.slider_volume.valueChanged.connect(self._apply_master_volume)
        self.slider_vol_orig.valueChanged.connect(self._apply_master_volume)
        self.slider_vol_stem.valueChanged.connect(self._apply_master_volume)

        # Playback original
        self.btn_play_orig.clicked.connect(self.toggle_original)
        self.btn_stop_orig.clicked.connect(self.stop_original)

        # Playback stem
        self.btn_play_guitar.clicked.connect(self.toggle_stem)
        self.btn_stop_guitar.clicked.connect(self.stop_stem)

        # Mudança de faixa no combo → para stem atual
        self.combo_stems.currentTextChanged.connect(
            self._on_stem_selection_changed
        )

        # Seek original — só atualiza slider quando o usuário NÃO está arrastando
        self.player_orig.durationChanged.connect(self._on_orig_duration_changed)
        self.player_orig.positionChanged.connect(self._on_orig_position_changed)
        self.slider_seek_orig.sliderMoved.connect(self.player_orig.setPosition)

        # Seek stem
        self.player_stem.durationChanged.connect(
            lambda d: self.slider_seek_stem.setMaximum(d)
        )
        self.player_stem.positionChanged.connect(self._on_stem_position_changed)
        self.slider_seek_stem.sliderMoved.connect(self.player_stem.setPosition)

        # Estado de playback → atualiza ícone dos botões e habilita stop
        self.player_orig.playbackStateChanged.connect(self._on_orig_state_changed)
        self.player_stem.playbackStateChanged.connect(self._on_stem_state_changed)

    # Volume master

    def _apply_master_volume(self) -> None:
        master = self.slider_volume.value() / 110.0
        self.audio_out_orig.setVolume(
            master * (self.slider_vol_orig.value() / 100.0)
        )
        self.audio_out_stem.setVolume(
            master * (self.slider_vol_stem.value() / 100.0)
        )

    # Carregar arquivo

    def load_audio_file(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Selecione a Música",
            "",
            "Audio Files (*.mp3 *.wav *.flac *.ogg *.aac)",
        )
        if not file_name:
            return

        logger.info(f"Arquivo carregado: {file_name}")
        self.path_original = file_name

        # Para qualquer reprodução anterior
        self.player_orig.stop()
        self.player_stem.stop()

        self.lbl_filepath.setText(Path(file_name).name)

        # Metadados
        title = Path(file_name).stem   # fallback sem metadados
        try:
            tag = TinyTag.get(file_name, image=True)

            title   = tag.title  or title
            artista = tag.artist or "Desconhecido"
            album   = tag.album  or "Desconhecido"
            ano     = str(tag.year) if tag.year else "—"

            duration_str = self._format_duration(int(tag.duration or 0))

            self.lbl_info.setText(f"{title}  |  {duration_str}")
            self.lbl_metadata.setText(
                f"Música:  {title}\n"
                f"Artista: {artista}\n"
                f"Álbum:   {album}  ({ano})"
            )

            img_data = tag.get_image()
            if img_data:
                img = QImage()
                img.loadFromData(img_data)
                self.lbl_cover.setPixmap(QPixmap(img))
                self.lbl_cover.setText("")
            else:
                self.lbl_cover.clear()
                self.lbl_cover.setText("♪")

        except Exception:
            logger.exception("Falha ao ler metadados.")
            self.lbl_info.setText(f"{title}  |  --:--")
            self.lbl_metadata.setText("Sem metadados.")
            self.lbl_cover.clear()
            self.lbl_cover.setText("♪")

        # Estado da UI
        self.btn_play_orig.setEnabled(True)
        self.btn_stop_orig.setEnabled(False)
        self.btn_run_demucs.setEnabled(True)

        # Invalida resultados anteriores de stems/análise
        self.path_guitarra  = ""
        self.path_stems_dir = ""
        self.btn_play_guitar.setEnabled(False)
        self.btn_stop_guitar.setEnabled(False)
        self.combo_stems.setEnabled(False)
        self.btn_run_analysis.setEnabled(False)

        self.progress_bar.setValue(0)
        self._set_status("Música carregada.")

    # Demucs

    def start_demucs(self) -> None:
        logger.info("Iniciando workflow Demucs.")
        self.btn_run_demucs.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.progress_bar.setRange(0, 0)

        self.demucs_thread = DemucsWorker(self.separator, self.path_original)
        self.demucs_thread.status.connect(self._set_status)
        self.demucs_thread.finished.connect(self._on_demucs_finished)
        self.demucs_thread.error.connect(self._on_error)
        self.demucs_thread.finished.connect(self.demucs_thread.deleteLater)
        self.demucs_thread.start()

    def _on_demucs_finished(self, guitar_path: str, stems_dir: str) -> None:
        logger.info("Workflow Demucs finalizado.")
        self.path_guitarra  = guitar_path
        self.path_stems_dir = stems_dir

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        self.btn_load.setEnabled(True)
        self.btn_play_guitar.setEnabled(True)
        self.btn_stop_guitar.setEnabled(False)
        self.combo_stems.setEnabled(True)
        self.btn_run_analysis.setEnabled(True)

        self._set_status("Faixas separadas com sucesso!")

    # Análise

    def start_analysis(self) -> None:
        logger.info("Iniciando workflow análise.")
        self.btn_run_analysis.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.progress_bar.setRange(0, 0)

        self.analysis_thread = AnalysisWorker(self.path_guitarra)
        self.analysis_thread.status.connect(self._set_status)
        self.analysis_thread.finished.connect(self._on_analysis_finished)
        self.analysis_thread.error.connect(self._on_error)
        self.analysis_thread.finished.connect(self.analysis_thread.deleteLater)
        self.analysis_thread.start()

    def _on_analysis_finished(self, params: dict) -> None:
        logger.info("Workflow análise finalizado.")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        self.btn_load.setEnabled(True)
        self.btn_run_analysis.setEnabled(True)

        gate = params.get("noise_gate_threshold_db", "--")
        eq   = params.get("eq", {})

        self.lbl_gate.setText(f"Noise Gate: {gate} dB")
        self.lbl_eq.setText(
            f"EQ — Bass: {eq.get('bass', '--')}  |  "
            f"Mid: {eq.get('mid', '--')}  |  "
            f"Treble: {eq.get('treble', '--')}"
        )
        self._set_status("Parâmetros calculados com sucesso!")

    # Playback original

    def toggle_original(self) -> None:
        if not self.path_original:
            return

        state = self.player_orig.playbackState()

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player_orig.pause()

        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.player_orig.play()

        else:   # StoppedState — carrega e inicia
            self.player_orig.setSource(
                QUrl.fromLocalFile(self.path_original)
            )
            self.player_orig.play()

    def stop_original(self) -> None:
        self.player_orig.stop()

    def _on_orig_state_changed(
        self, state: QMediaPlayer.PlaybackState
    ) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        paused  = state == QMediaPlayer.PlaybackState.PausedState
        self.btn_play_orig.setText("⏸" if playing else "▶")
        self.btn_stop_orig.setEnabled(playing or paused)

    # Playback stem

    def toggle_stem(self) -> None:
        if not self.path_stems_dir:
            return

        state = self.player_stem.playbackState()

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player_stem.pause()

        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.player_stem.play()

        else:   # StoppedState — carrega stem selecionado
            faixa     = self.combo_stems.currentText()
            stem_file = Path(self.path_stems_dir) / f"{faixa}.wav"

            if not stem_file.exists():
                QMessageBox.warning(
                    self,
                    "Aviso",
                    f"A faixa '{faixa}.wav' não foi encontrada.\n{stem_file}",
                )
                return

            logger.info(f"Reproduzindo stem: {stem_file}")
            self.player_stem.setSource(QUrl.fromLocalFile(str(stem_file)))
            self.player_stem.play()

    def stop_stem(self) -> None:
        self.player_stem.stop()

    def _on_stem_state_changed(
        self, state: QMediaPlayer.PlaybackState
    ) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        paused  = state == QMediaPlayer.PlaybackState.PausedState
        self.btn_play_guitar.setText("⏸" if playing else "▶")
        self.btn_stop_guitar.setEnabled(playing or paused)

    def _on_stem_selection_changed(self, _: str) -> None:
        """Para o stem atual quando o usuário troca de faixa no combo."""
        self.player_stem.stop()

    # Seek

    def _on_orig_duration_changed(self, duration_ms: int) -> None:
        self.slider_seek_orig.setMaximum(duration_ms)
        # Atualiza duração no lbl_info com o valor real vindo do player
        secs  = duration_ms // 1000
        title = self.lbl_info.text().split("|")[0].strip()
        self.lbl_info.setText(f"{title}  |  {self._format_duration(secs)}")

    def _on_orig_position_changed(self, pos: int) -> None:
        if not self.slider_seek_orig.isSliderDown():
            self.slider_seek_orig.setValue(pos)

    def _on_stem_position_changed(self, pos: int) -> None:
        if not self.slider_seek_stem.isSliderDown():
            self.slider_seek_stem.setValue(pos)

    # Erro

    def _on_error(self, err_msg: str) -> None:
        logger.error("Erro recebido pela UI.")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.btn_load.setEnabled(True)

        # Reabilita apenas os botões que fazem sentido no estado atual
        self.btn_run_demucs.setEnabled(bool(self.path_original))
        self.btn_run_analysis.setEnabled(bool(self.path_guitarra))

        self._set_status("Erro no processamento.")
        QMessageBox.critical(self, "Erro", err_msg)

    # Utilitários

    def _set_status(self, msg: str) -> None:
        logger.info(msg)
        self.lbl_status.setText(f"● {msg}")

    @staticmethod
    def _format_duration(total_secs: int) -> str:
        mins, secs = divmod(total_secs, 60)
        return f"{mins:02d}:{secs:02d}"

    # Cleanup

    def closeEvent(self, event) -> None:
        """Para players e aguarda threads antes de fechar a janela."""
        self.player_orig.stop()
        self.player_stem.stop()

        for attr in ("demucs_thread", "analysis_thread"):
            thread = getattr(self, attr, None)
            if thread is not None and thread.isRunning():
                logger.info(f"Aguardando {attr} encerrar…")
                thread.quit()
                thread.wait(3000)

        event.accept()


# Entry point

if __name__ == "__main__":
    logger.info("Inicializando QApplication…")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())