import sys
import logging
import traceback
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox,
    QSystemTrayIcon,
)
from PyQt6.QtCore import QThread, pyqtSignal, QUrl, Qt, QTimer
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from tinytag import TinyTag

from gui.ui_mainwindow import Ui_Dialog
from gui.tab_demucs import TabDemucs
from gui.tab_tonematching import TabToneMatching
from gui.tab_hardware import TabHardware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s -> %(message)s",
)
logger = logging.getLogger(__name__)


class MetadataWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self.file_path = file_path

    def run(self) -> None:
        try:
            logger.debug(f"Lendo metadados de: {self.file_path}")
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


class MainWindow(QDialog, Ui_Dialog):
    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        logger.info("Inicializando aplicação…")

        self.path_original: str = ""
        self.path_guitarra: str = ""
        self.path_stems_dir: str = ""

        self.audio_out_orig = QAudioOutput()
        self.player_orig = QMediaPlayer()
        self.player_orig.setAudioOutput(self.audio_out_orig)

        self.audio_out_stem = QAudioOutput()
        self.player_stem = QMediaPlayer()
        self.player_stem.setAudioOutput(self.audio_out_stem)

        self.tray_icon = QSystemTrayIcon(self)
        app_icon = self.style().standardIcon(self.style().StandardPixmap.SP_MediaPlay)
        self.tray_icon.setIcon(app_icon)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

        self.metadata_thread: MetadataWorker | None = None

        self.tab_demucs = TabDemucs()
        self.tab_tonematching = TabToneMatching()
        self.tab_hardware = TabHardware()

        self.tabsMain.addTab(self.tab_demucs, "🎚  Separação (Demucs)")
        self.tabsMain.addTab(self.tab_tonematching, "📊  Tone Matching")
        self.tabsMain.addTab(self.tab_hardware, "🔌  Pedal (ESP32-S3)")

        self._connect_signals()
        self._apply_master_volume()
        logger.info("Aplicação inicializada.")

    def _connect_signals(self) -> None:
        self.btn_load.clicked.connect(self.load_audio_file)
        self.btn_record.clicked.connect(self.open_record_dialog)

        self.slider_vol_orig.valueChanged.connect(self._apply_master_volume)
        self.slider_vol_stem.valueChanged.connect(self._apply_master_volume)

        self.btn_play_orig.clicked.connect(self.toggle_original)
        self.btn_stop_orig.clicked.connect(self.stop_original)

        self.btn_play_guitar.clicked.connect(self.toggle_stem)
        self.btn_stop_guitar.clicked.connect(self.stop_stem)

        self.combo_stems.currentTextChanged.connect(self._on_stem_selection_changed)

        self.player_orig.durationChanged.connect(self._on_orig_duration_changed)
        self.player_orig.positionChanged.connect(self._on_orig_position_changed)
        self.slider_seek_orig.sliderMoved.connect(self.player_orig.setPosition)

        self.player_stem.durationChanged.connect(lambda d: self.slider_seek_stem.setMaximum(d))
        self.player_stem.positionChanged.connect(self._on_stem_position_changed)
        self.slider_seek_stem.sliderMoved.connect(self.player_stem.setPosition)

        self.player_orig.playbackStateChanged.connect(self._on_orig_state_changed)
        self.player_stem.playbackStateChanged.connect(self._on_stem_state_changed)

        self.tab_demucs.separation_started.connect(self._on_demucs_started)
        self.tab_demucs.separation_finished.connect(self._on_demucs_finished)
        self.tab_demucs.separation_error.connect(self._on_worker_error)
        self.tab_demucs.status_message.connect(self._set_status)

        self.tab_tonematching.analysis_started.connect(self._on_analysis_started)
        self.tab_tonematching.analysis_finished.connect(self._on_analysis_finished)
        self.tab_tonematching.analysis_error.connect(self._on_worker_error)
        self.tab_tonematching.status_message.connect(self._set_status)

        self.tab_hardware.send_started.connect(self._on_hardware_send_started)
        self.tab_hardware.send_finished.connect(self._on_hardware_send_finished)
        self.tab_hardware.send_error.connect(self._on_hardware_send_error)
        self.tab_hardware.status_message.connect(self._set_status)

    def _apply_master_volume(self) -> None:
        self.audio_out_orig.setVolume(self.slider_vol_orig.value() / 100.0)
        self.audio_out_stem.setVolume(self.slider_vol_stem.value() / 100.0)

    def open_record_dialog(self) -> None:
        """Abre o diálogo para capturar áudio direto da ESP32-S3 ou microfone."""
        from gui.dialog_record import RecordDialog
        dlg = RecordDialog(self)
        dlg.recording_finished.connect(self.load_direct_audio)
        dlg.exec()

    def load_direct_audio(self, filepath: str, auto_run_tonematching: bool = False) -> None:
        """
        Carrega a gravação direta da guitarra, ignorando o Demucs e
        preparando a aba de Tone Matching de forma imediata.
        """
        logger.info(f"Carregando áudio de entrada direta: {filepath}")
        self.path_original = filepath
        self.path_guitarra = filepath
        self.path_stems_dir = str(Path(filepath).parent)

        try:
            self.player_orig.stop()
        except RuntimeError:
            pass
        try:
            self.player_stem.stop()
        except RuntimeError:
            pass

        self.lbl_filepath.setText(f"{Path(filepath).name} [Entrada Direta]")
        self.lbl_info.setText("Guitarra Direta (ESP32 / Mic) | --:--")
        self.lbl_metadata.setText(
            f"Origem: Entrada Direta (ESP32-S3 / Microfone)\n"
            f"Faixa: Guitarra Isolada\n"
            f"Arquivo: {Path(filepath).name}\n"
            f"Demucs: Ignorado (Faixa já isolada)"
        )
        self.lbl_cover.clear()
        self.lbl_cover.setText("🎸")

        self.btn_play_orig.setEnabled(True)
        self.btn_stop_orig.setEnabled(False)
        self.btn_play_guitar.setEnabled(True)
        self.btn_stop_guitar.setEnabled(False)

        self.combo_stems.blockSignals(True)
        self.combo_stems.clear()
        self.combo_stems.addItem("guitar")
        self.combo_stems.setCurrentIndex(0)
        self.combo_stems.setEnabled(True)
        self.combo_stems.blockSignals(False)

        self.tab_demucs.reset()
        self.tab_demucs.set_audio_path(filepath)

        self.tab_tonematching.reset()
        self.tab_tonematching.set_selected_stem("guitar", filepath)

        # Alterna para a aba de Tone Matching
        self.tabsMain.setCurrentWidget(self.tab_tonematching)

        self._set_status("Gravação da ESP32/Microfone carregada com sucesso! Demucs ignorado.")
        self._notify("Entrada Direta Carregada", "Áudio pronto para análise na aba Tone Matching.")

        if auto_run_tonematching:
            QTimer.singleShot(300, self.tab_tonematching.start_analysis)

    def load_audio_file(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Selecione a Música",
            "",
            "Audio Files (*.mp3 *.wav *.flac *.ogg *.aac)",
        )
        if not file_name:
            return

        file_path_obj = Path(file_name)
        try:
            file_size_bytes = file_path_obj.stat().st_size
        except OSError as exc:
            QMessageBox.critical(self, "Arquivo inacessível", str(exc))
            return

        if file_size_bytes == 0:
            QMessageBox.warning(self, "Arquivo vazio", "O arquivo selecionado possui 0 bytes.")
            return

        self.path_original = file_name

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

        if self.metadata_thread is not None:
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

        self.btn_play_orig.setEnabled(False)
        self.btn_stop_orig.setEnabled(False)

        self.path_guitarra = ""
        self.path_stems_dir = ""
        self.btn_play_guitar.setEnabled(False)
        self.btn_stop_guitar.setEnabled(False)
        self.combo_stems.clear()
        self.combo_stems.setEnabled(False)
        self.lbl_gate.setText("Noise Gate: -- dB")
        self.lbl_eq.setText("EQ: Low: -- | M1: -- | M2: -- | High: --")

        self.tab_demucs.reset()
        self.tab_demucs.set_audio_path(file_name)
        self.tab_tonematching.reset()
        self.tab_hardware.reset()

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
        self.lbl_metadata.setText(f"Música:  {title}\nArtista: {artista}\nÁlbum:   {album}  ({ano})")

        image_data = params.get("image_data")
        if image_data:
            try:
                img = QImage()
                if img.loadFromData(image_data):
                    pixmap = QPixmap.fromImage(img)
                    self.lbl_cover.setPixmap(
                        pixmap.scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    )
                    self.lbl_cover.setText("")
                else:
                    self.lbl_cover.setText("♪")
            except Exception:
                self.lbl_cover.setText("♪")
        else:
            self.lbl_cover.setText("♪")

        self.btn_play_orig.setEnabled(True)
        self.btn_stop_orig.setEnabled(False)
        self._set_status("Música carregada.")

    def _on_metadata_error(self, err_msg: str) -> None:
        self.lbl_info.setText(f"{Path(self.path_original).stem}  |  --:--")
        self.lbl_metadata.setText("Sem metadados.")
        self.lbl_cover.setText("♪")
        self.btn_play_orig.setEnabled(True)
        self.btn_stop_orig.setEnabled(False)
        self._set_status("Música carregada.")

    def _on_demucs_started(self) -> None:
        self.btn_load.setEnabled(False)
        self.btn_record.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self._notify("Separação de faixas iniciada", f"Processando '{Path(self.path_original).name}' com o Demucs…")

    def _on_demucs_finished(self, guitar_path: str, stems_dir: str) -> None:
        self.path_guitarra = guitar_path
        self.path_stems_dir = stems_dir

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.btn_load.setEnabled(True)
        self.btn_record.setEnabled(True)
        self.btn_play_guitar.setEnabled(True)
        self.btn_stop_guitar.setEnabled(False)

        self._populate_stems_combo(stems_dir)
        self._notify("Separação concluída", "As faixas foram separadas e já estão disponíveis.")
        self._set_status("Faixas separadas com sucesso!")

    def _populate_stems_combo(self, stems_dir: str) -> None:
        stem_files = sorted(Path(stems_dir).glob("*.wav"))
        stem_names = [f.stem for f in stem_files]

        self.combo_stems.blockSignals(True)
        self.combo_stems.clear()
        if not stem_names:
            self.combo_stems.setEnabled(False)
            self.btn_play_guitar.setEnabled(False)
            self.combo_stems.blockSignals(False)
            return

        self.combo_stems.addItems(stem_names)
        self.combo_stems.setEnabled(True)
        default_index = stem_names.index("guitar") if "guitar" in stem_names else 0
        self.combo_stems.setCurrentIndex(default_index)
        self.combo_stems.blockSignals(False)
        self._propagate_stem_selection(stem_names[default_index])

    def _propagate_stem_selection(self, stem_name: str) -> None:
        stem_path = ""
        if stem_name and self.path_stems_dir:
            candidate = Path(self.path_stems_dir) / f"{stem_name}.wav"
            if candidate.exists():
                stem_path = str(candidate)
        elif stem_name and self.path_guitarra:
            stem_path = self.path_guitarra
        self.tab_tonematching.set_selected_stem(stem_name, stem_path)

    def _on_analysis_started(self) -> None:
        self.btn_load.setEnabled(False)
        self.btn_record.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        stem_name = self.combo_stems.currentText()
        self._notify("Tone Matching iniciado", f"Analisando a faixa '{stem_name}'…")

    def _on_analysis_finished(self, params: dict, analyzed_stem: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.btn_load.setEnabled(True)
        self.btn_record.setEnabled(True)

        gate = params.get("noise_gate_threshold_db", "--")
        eq4 = params.get("eq_4bands", {})
        is_silent = params.get("is_silent", False)

        self.lbl_gate.setText(f"Noise Gate: {gate} dB")
        self.lbl_eq.setText(
            f"EQ — Low: {eq4.get('low_db', 0):+d}dB | M1: {eq4.get('mid1_db', 0):+d}dB | "
            f"M2: {eq4.get('mid2_db', 0):+d}dB | High: {eq4.get('high_db', 0):+d}dB"
        )

        self.tab_hardware.set_params(params)

        if is_silent:
            self._set_status("Aviso: o áudio analisado está em silêncio absoluto.")
        else:
            self._set_status("Tone Matching concluído: parâmetros adaptativos calculados!")
            self._notify("Tone Matching concluído", f"Parâmetros calculados para '{analyzed_stem}'.")

    def _on_hardware_send_started(self) -> None:
        self.btn_load.setEnabled(False)
        self.btn_record.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self._notify("Envio iniciado", "Transmitindo estado completo (140B) para a ESP32-S3…")

    def _on_hardware_send_finished(self, was_mock: bool) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.btn_load.setEnabled(True)
        self.btn_record.setEnabled(True)
        if was_mock:
            self._set_status("Simulação concluída (modo MOCK).")
        else:
            self._set_status("Parâmetros transmitidos com sucesso para a ESP32-S3!")
            self._notify("Envio concluído", "Os parâmetros foram aplicados na pedaleira.")

    def _on_hardware_send_error(self, err_msg: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.btn_load.setEnabled(True)
        self.btn_record.setEnabled(True)
        self._set_status("Erro ao enviar para a pedaleira.")
        self._notify("Falha no envio", self._friendly_error_summary(err_msg), icon=QSystemTrayIcon.MessageIcon.Critical)

    def _on_worker_error(self, err_msg: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.btn_load.setEnabled(True)
        self.btn_record.setEnabled(True)
        self._set_status("Erro no processamento.")
        QMessageBox.critical(self, "Erro", self._friendly_error_summary(err_msg))

    @staticmethod
    def _friendly_error_summary(err_msg: str) -> str:
        lines = [line.strip() for line in err_msg.strip().splitlines() if line.strip()]
        return lines[-1] if lines else "Ocorreu um erro inesperado."

    def toggle_original(self) -> None:
        if not self.path_original:
            return
        state = self.player_orig.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player_orig.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.player_orig.play()
        else:
            self.player_orig.setSource(QUrl.fromLocalFile(self.path_original))
            self.player_orig.play()

    def stop_original(self) -> None:
        self.player_orig.stop()

    def _on_orig_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        paused = state == QMediaPlayer.PlaybackState.PausedState
        self.btn_play_orig.setText("⏸" if playing else "▶")
        self.btn_stop_orig.setEnabled(playing or paused)

    def toggle_stem(self) -> None:
        if not self.path_stems_dir and not self.path_guitarra:
            return
        state = self.player_stem.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player_stem.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.player_stem.play()
        else:
            faixa = self.combo_stems.currentText()
            stem_file = Path(self.path_stems_dir) / f"{faixa}.wav" if self.path_stems_dir else Path(self.path_guitarra)
            if not stem_file.exists():
                if self.path_guitarra and Path(self.path_guitarra).exists():
                    stem_file = Path(self.path_guitarra)
                else:
                    QMessageBox.warning(self, "Arquivo não encontrado", f"A faixa '{faixa}.wav' não foi encontrada.")
                    return
            self.player_stem.setSource(QUrl.fromLocalFile(str(stem_file)))
            self.player_stem.play()

    def stop_stem(self) -> None:
        self.player_stem.stop()

    def _on_stem_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        paused = state == QMediaPlayer.PlaybackState.PausedState
        self.btn_play_guitar.setText("⏸" if playing else "▶")
        self.btn_stop_guitar.setEnabled(playing or paused)

    def _on_stem_selection_changed(self, new_stem: str) -> None:
        self.player_stem.stop()
        self._propagate_stem_selection(new_stem)
        if new_stem and new_stem != self.tab_tonematching.last_analyzed_stem:
            self.lbl_gate.setText("Noise Gate: -- dB")
            self.lbl_eq.setText("EQ: Low: -- | M1: -- | M2: -- | High: --")
            self.tab_hardware.set_params({})

    def _on_orig_duration_changed(self, duration_ms: int) -> None:
        self.slider_seek_orig.setMaximum(duration_ms)
        secs = duration_ms // 1000
        title = self.lbl_info.text().split("|")[0].strip()
        self.lbl_info.setText(f"{title}  |  {self._format_duration(secs)}")

    def _on_orig_position_changed(self, pos: int) -> None:
        if not self.slider_seek_orig.isSliderDown():
            self.slider_seek_orig.setValue(pos)

    def _on_stem_position_changed(self, pos: int) -> None:
        if not self.slider_seek_stem.isSliderDown():
            self.slider_seek_stem.setValue(pos)

    def _set_status(self, msg: str) -> None:
        logger.info(msg)
        self.lbl_status.setText(f"● {msg}")

    def _notify(self, title: str, message: str, icon=QSystemTrayIcon.MessageIcon.Information) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.showMessage(title, message, icon, 4000)

    @staticmethod
    def _format_duration(total_secs: int) -> str:
        mins, secs = divmod(total_secs, 60)
        return f"{mins:02d}:{secs:02d}"

    def closeEvent(self, event) -> None:
        try:
            self.player_orig.stop()
            self.player_stem.stop()
        except RuntimeError:
            pass

        if self.metadata_thread is not None:
            try:
                self.metadata_thread.quit()
                self.metadata_thread.wait(2000)
            except RuntimeError:
                pass

        self.tab_demucs.stop_thread()
        self.tab_tonematching.stop_thread()
        self.tab_hardware.stop_threads()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())