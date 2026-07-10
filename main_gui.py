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
from PyQt6.QtCore import QThread, pyqtSignal, QUrl, Qt
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


# Metadata worker

class MetadataWorker(QThread):

    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self.file_path = file_path

    def run(self) -> None:
        try:
            tag = TinyTag.get(self.file_path, image=True)

            image_data = None
            images = getattr(tag, "images", None)
            if images:
                if isinstance(images, list) and images:
                    image_data = images[0]
                else:
                    try:
                        image_data = images.any()
                    except Exception:
                        image_data = None
            elif hasattr(tag, "get_image"):
                try:
                    image_data = tag.get_image()
                except Exception:
                    image_data = None

            params = {
                "file_path": self.file_path,
                "title": tag.title or Path(self.file_path).stem,
                "artist": tag.artist or "Desconhecido",
                "album": tag.album or "Desconhecido",
                "year": str(tag.year) if tag.year else "—",
                "duration": int(tag.duration or 0),
                "image_data": image_data,
            }
            self.finished.emit(params)

        except Exception:
            logger.exception("Erro ao carregar metadados.")
            self.error.emit(traceback.format_exc())


# Demucs worker

class DemucsWorker(QThread):

    finished = pyqtSignal(str, str)   # guitar_path, stems_dir
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)

    def __init__(self, audio_path: str) -> None:
        super().__init__()
        self.audio_path = audio_path

    def run(self) -> None:
        try:
            logger.info(f"Iniciando separação: {self.audio_path}")

            separator = AudioSeparator()
            guitar_path = separator.extract_guitar(
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
        try:
            self.player_orig.stop()
        except RuntimeError:
            pass
        try:
            self.player_stem.stop()
        except RuntimeError:
            pass

        self.lbl_filepath.setText(Path(file_name).name)
        self.lbl_info.setText("Carregando metadados…")
        self.lbl_metadata.setText("Carregando metadados…")
        self.lbl_cover.clear()
        self.lbl_cover.setText("♪")

        # Cancela thread antiga de metadados, se houver
        if getattr(self, "metadata_thread", None) is not None:
            try:
                self.metadata_thread.quit()
                self.metadata_thread.wait(1000)
            except RuntimeError:
                pass
            finally:
                self.metadata_thread = None

        self.metadata_thread = MetadataWorker(file_name)
        self.metadata_thread.finished.connect(self._on_metadata_finished)
        self.metadata_thread.error.connect(self._on_metadata_error)
        self.metadata_thread.start()

        # Estado da UI enquanto a leitura ocorre
        self.btn_play_orig.setEnabled(False)
        self.btn_stop_orig.setEnabled(False)
        self.btn_run_demucs.setEnabled(False)

        # Invalida resultados anteriores de stems/análise
        self.path_guitarra  = ""
        self.path_stems_dir = ""
        self.btn_play_guitar.setEnabled(False)
        self.btn_stop_guitar.setEnabled(False)
        self.combo_stems.setEnabled(False)
        self.btn_run_analysis.setEnabled(False)

        self.progress_bar.setValue(0)
        self._set_status("Carregando metadados…")

    def _on_metadata_finished(self, params: dict) -> None:
        if params.get("file_path") != self.path_original:
            return

        title = params.get("title", Path(self.path_original).stem)
        artista = params.get("artist", "Desconhecido")
        album = params.get("album", "Desconhecido")
        ano = params.get("year", "—")
        duration_raw = int(params.get("duration", 0) or 0)
        duration_str = self._format_duration(duration_raw)

        self.lbl_info.setText(f"{title}  |  {duration_str}")
        self.lbl_metadata.setText(
            f"Música:  {title}\n"
            f"Artista: {artista}\n"
            f"Álbum:   {album}  ({ano})"
        )

        image_data = params.get("image_data")
        if image_data:
            try:
                img = QImage()
                if img.loadFromData(image_data):
                    pixmap = QPixmap.fromImage(img)
                    self.lbl_cover.setPixmap(
                        pixmap.scaled(
                            180,
                            180,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    self.lbl_cover.setText("")
                else:
                    raise ValueError("Imagem inválida")
            except Exception:
                self.lbl_cover.clear()
                self.lbl_cover.setText("♪")
        else:
            self.lbl_cover.clear()
            self.lbl_cover.setText("♪")

        self.btn_play_orig.setEnabled(True)
        self.btn_stop_orig.setEnabled(False)
        self.btn_run_demucs.setEnabled(True)
        self._set_status("Música carregada.")

    def _on_metadata_error(self, err_msg: str) -> None:
        logger.error("Falha ao carregar metadados.")
        self.lbl_info.setText(f"{Path(self.path_original).stem}  |  --:--")
        self.lbl_metadata.setText("Sem metadados.")
        self.lbl_cover.clear()
        self.lbl_cover.setText("♪")
        self.btn_play_orig.setEnabled(True)
        self.btn_stop_orig.setEnabled(False)
        self.btn_run_demucs.setEnabled(True)
        self._set_status("Música carregada.")

    # Demucs

    def start_demucs(self) -> None:
        logger.info("Iniciando workflow Demucs.")
        self.btn_run_demucs.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.progress_bar.setRange(0, 0)

        self.demucs_thread = DemucsWorker(self.path_original)
        self.demucs_thread.status.connect(self._set_status)
        self.demucs_thread.finished.connect(self._on_demucs_finished)
        self.demucs_thread.error.connect(self._on_error)
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
        self.analysis_thread.start()

    def _on_analysis_finished(self, params: dict) -> None:
        logger.info("Workflow análise finalizado.")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        self.btn_load.setEnabled(True)
        self.btn_run_analysis.setEnabled(True)

        gate = params.get("noise_gate_threshold_db", "--")
        eq   = params.get("eq", {})
        is_silent = params.get("is_silent", False)

        self.lbl_gate.setText(f"Noise Gate: {gate} dB")
        self.lbl_eq.setText(
            f"EQ — Bass: {eq.get('bass', '--')}  |  "
            f"Mid: {eq.get('mid', '--')}  |  "
            f"Treble: {eq.get('treble', '--')}"
        )

        if is_silent:
            self._set_status(
                "Aviso: a faixa analisada está silenciosa ou vazia."
            )
            QMessageBox.warning(
                self,
                "Faixa silenciosa",
                "O stem selecionado não contém sinal audível relevante.\n"
                "Isso costuma acontecer quando o instrumento escolhido não "
                "está presente na música original. Os parâmetros calculados "
                "não são confiáveis nesse caso."
            )
        else:
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

    def _stop_thread(self, attr: str) -> None:
        thread = getattr(self, attr, None)
        if thread is None:
            return

        try:
            if not thread.isRunning():
                setattr(self, attr, None)
                return
        except RuntimeError:
            logger.info(f"{attr} já foi descartado pela Qt.")
            setattr(self, attr, None)
            return

        logger.info(f"Parando {attr}…")
        try:
            thread.quit()
            if not thread.wait(3000):
                logger.warning(
                    f"{attr} não encerrou em 3s; forçando término."
                )
                thread.terminate()
                thread.wait(1000)
        except RuntimeError:
            logger.info(f"{attr} foi descartado durante o shutdown.")
        finally:
            setattr(self, attr, None)

    # Cleanup

    def closeEvent(self, event) -> None:
        """Para players e aguarda threads antes de fechar a janela."""
        try:
            self.player_orig.stop()
        except RuntimeError:
            pass

        try:
            self.player_stem.stop()
        except RuntimeError:
            pass

        for attr in (
            "demucs_thread",
            "analysis_thread",
            "metadata_thread",
        ):
            self._stop_thread(attr)

        try:
            event.accept()
        except RuntimeError:
            pass


# Entry point

if __name__ == "__main__":
    logger.info("Inicializando QApplication…")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())