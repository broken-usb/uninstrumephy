import sys
import time
import logging
import traceback
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox,
    QSystemTrayIcon,
    QListWidgetItem,
)
from PyQt6.QtCore import QThread, pyqtSignal, QUrl, Qt
from PyQt6.QtGui import QPixmap, QImage, QIcon
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from tinytag import TinyTag

from gui.ui_mainwindow import Ui_Dialog
from gui.plots import WaveformPlot, EQCurvePlot
from core.separator import AudioSeparator
from core.analyzer import AudioAnalyzer
from core.hardware import ESP32Link, HardwareLinkError

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
            logger.debug(
                f"Metadados extraídos com sucesso (capa embutida: {bool(image_data)})."
            )
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
        start_time = time.monotonic()
        try:
            logger.info(f"Iniciando separação: {self.audio_path}")

            separator = AudioSeparator()
            logger.debug(f"Device de inferência: {separator.device}")

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


# Analysis worker

class AnalysisWorker(QThread):

    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)

    def __init__(self, guitar_path: str) -> None:
        super().__init__()
        self.guitar_path = guitar_path

    def run(self) -> None:
        start_time = time.monotonic()
        try:
            logger.info(f"Iniciando análise: {self.guitar_path}")
            self.status.emit("Extraindo parâmetros matemáticos…")

            params = AudioAnalyzer().analyze_stem(self.guitar_path)
            elapsed = time.monotonic() - start_time

            eq = params.get("eq", {})
            logger.info(
                f"Análise concluída em {elapsed:.2f}s. "
                f"Gate: {params.get('noise_gate_threshold_db')} dB | "
                f"EQ (bass/mid/treble): "
                f"{eq.get('bass')}/{eq.get('mid')}/{eq.get('treble')} | "
                f"Silencioso: {params.get('is_silent')}"
            )
            self.finished.emit(params)

        except Exception:
            logger.exception("Erro durante análise.")
            self.error.emit(traceback.format_exc())


# Hardware worker

class HardwareWorker(QThread):

    finished = pyqtSignal(bool)   # True se foi enviado em modo simulado (MOCK)
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)

    def __init__(self, params: dict, port: str | None = None) -> None:
        super().__init__()
        self.params = params
        self.port = port

    def run(self) -> None:
        try:
            logger.info("Iniciando envio para a ESP32-S3.")

            link = ESP32Link(port=self.port)
            was_mock = link.is_mock

            if was_mock:
                self.status.emit(
                    "Nenhuma placa detectada — simulando envio (modo MOCK)…"
                )
            else:
                self.status.emit(f"Conectando à porta {link.port}…")

            link.send_params(self.params, progress_cb=self.status.emit)
            link.close()

            logger.info("Envio para a ESP32-S3 concluído.")
            self.finished.emit(was_mock)

        except HardwareLinkError as exc:
            logger.exception("Erro de comunicação com a ESP32-S3.")
            self.error.emit(str(exc))

        except Exception:
            logger.exception("Erro inesperado durante o envio para hardware.")
            self.error.emit(traceback.format_exc())


# Filter query worker

class FilterQueryWorker(QThread):

    finished = pyqtSignal(list, bool)   # (filtros, was_mock)
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)

    def __init__(self, port: str | None = None) -> None:
        super().__init__()
        self.port = port

    def run(self) -> None:
        try:
            logger.info("Consultando filtros disponíveis na ESP32-S3.")

            link = ESP32Link(port=self.port)
            was_mock = link.is_mock

            if was_mock:
                self.status.emit(
                    "Nenhuma placa detectada — usando filtros de exemplo (modo MOCK)…"
                )
            else:
                self.status.emit(f"Conectando à porta {link.port}…")

            filters = link.list_filters(progress_cb=self.status.emit)
            link.close()

            logger.info(f"Consulta de filtros concluída: {len(filters)} filtro(s).")
            self.finished.emit(filters, was_mock)

        except HardwareLinkError as exc:
            logger.exception("Erro de comunicação ao consultar filtros na ESP32-S3.")
            self.error.emit(str(exc))

        except Exception:
            logger.exception("Erro inesperado durante a consulta de filtros.")
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

        # Últimos parâmetros calculados (necessários para o envio ao hardware)
        self.last_params: dict = {}
        # Nome do stem que gerou os últimos parâmetros calculados (para
        # detectar quando o combo é trocado e os dados ficam desatualizados)
        self.last_analyzed_stem: str = ""

        # Ícone de bandeja usado para exibir notificações nativas do SO
        # ao iniciar/concluir processamentos longos (Demucs, análise,
        # envio para hardware). Não exibe um ícone visível na bandeja
        # por padrão em todos os SOs — serve só como emissor de notificação.
        self.tray_icon = QSystemTrayIcon(self)
        app_icon = self.style().standardIcon(
            self.style().StandardPixmap.SP_MediaPlay
        )
        self.tray_icon.setIcon(app_icon)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

        # Gráficos de forma de onda e curva de EQ, injetados nos
        # containers vazios definidos no .ui
        self.waveform_plot = WaveformPlot()
        self.waveformContainerLayout.addWidget(self.waveform_plot)

        self.eq_curve_plot = EQCurvePlot()
        self.eqCurveContainerLayout.addWidget(self.eq_curve_plot)

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
        self.btn_send_hardware.clicked.connect(self.start_send_hardware)
        self.btn_query_filters.clicked.connect(self.start_query_filters)
        self.btn_apply_filters.clicked.connect(self.apply_selected_filters)
        self.list_filters.itemSelectionChanged.connect(
            self._on_filter_selection_changed
        )

        # Atualiza volumes
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

    # Volume

    def _apply_master_volume(self) -> None:
        self.audio_out_orig.setVolume(self.slider_vol_orig.value() / 100.0)
        self.audio_out_stem.setVolume(self.slider_vol_stem.value() / 100.0)

    # Carregar arquivo

    def load_audio_file(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Selecione a Música",
            "",
            "Audio Files (*.mp3 *.wav *.flac *.ogg *.aac)",
        )
        if not file_name:
            logger.info("Seleção de arquivo cancelada pelo usuário.")
            return

        file_path_obj = Path(file_name)

        try:
            file_size_bytes = file_path_obj.stat().st_size
        except OSError as exc:
            logger.error(f"Não foi possível acessar o arquivo selecionado: {exc}")
            QMessageBox.critical(
                self,
                "Arquivo inacessível",
                f"Não foi possível acessar o arquivo selecionado:\n{file_name}\n\n"
                f"Verifique se ele ainda existe e se você tem permissão de leitura.",
            )
            return

        if file_size_bytes == 0:
            logger.warning(f"Arquivo selecionado está vazio (0 bytes): {file_name}")
            QMessageBox.warning(
                self,
                "Arquivo vazio",
                f"O arquivo selecionado está vazio (0 bytes):\n{file_name}\n\n"
                f"Selecione um arquivo de áudio válido.",
            )
            return

        file_size_mb = file_size_bytes / (1024 * 1024)
        logger.info(f"Arquivo carregado: {file_name} ({file_size_mb:.2f} MB)")
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
            logger.debug("Cancelando thread de metadados anterior ainda em execução.")
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
        logger.info("Thread de leitura de metadados iniciada.")

        # Estado da UI enquanto a leitura ocorre
        self.btn_play_orig.setEnabled(False)
        self.btn_stop_orig.setEnabled(False)
        self.btn_run_demucs.setEnabled(False)

        # Invalida resultados anteriores de stems/análise
        self.path_guitarra  = ""
        self.path_stems_dir = ""
        self.last_params    = {}
        self.last_analyzed_stem = ""
        self.btn_play_guitar.setEnabled(False)
        self.btn_stop_guitar.setEnabled(False)
        self.combo_stems.clear()
        self.combo_stems.setEnabled(False)
        self.btn_run_analysis.setEnabled(False)
        self.btn_send_hardware.setEnabled(False)
        self.lbl_gate.setText("Noise Gate: -- dB")
        self.lbl_eq.setText("EQ — Bass: --  |  Mid: --  |  Treble: --")
        self.lbl_analyzed_stem.setText("")
        self.waveform_plot.clear_plot()
        self.eq_curve_plot.clear_plot()

        self.progress_bar.setValue(0)
        self._set_status("Carregando metadados…")

    def _on_metadata_finished(self, params: dict) -> None:
        if params.get("file_path") != self.path_original:
            logger.debug(
                "Metadados recebidos para um arquivo que não é mais o atual; descartando."
            )
            return

        title = params.get("title", Path(self.path_original).stem)
        artista = params.get("artist", "Desconhecido")
        album = params.get("album", "Desconhecido")
        ano = params.get("year", "—")
        duration_raw = int(params.get("duration", 0) or 0)
        duration_str = self._format_duration(duration_raw)

        logger.info(
            f"Metadados carregados — Título: {title} | Artista: {artista} | "
            f"Álbum: {album} ({ano}) | Duração: {duration_str}"
        )

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

        self._notify(
            "Separação de faixas iniciada",
            f"Processando '{Path(self.path_original).name}' com o Demucs…",
        )

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

        self._populate_stems_combo(stems_dir)

        self._notify(
            "Separação concluída",
            "As faixas foram separadas com sucesso e já estão disponíveis.",
        )

        self._set_status("Faixas separadas com sucesso!")

    def _populate_stems_combo(self, stems_dir: str) -> None:
        """
        Popula o combo_stems com os stems realmente encontrados em disco,
        em vez de assumir uma lista fixa — evita mostrar opções que não
        existem caso o modelo Demucs mude (ex.: 4 stems em vez de 6) ou
        algum arquivo não tenha sido gerado por algum motivo.
        """
        stem_files = sorted(Path(stems_dir).glob("*.wav"))
        stem_names = [f.stem for f in stem_files]

        logger.debug(f"Stems encontrados em disco: {stem_names}")

        self.combo_stems.blockSignals(True)
        self.combo_stems.clear()

        if not stem_names:
            logger.warning(
                f"Nenhum arquivo .wav encontrado em {stems_dir} após a separação."
            )
            self.combo_stems.setEnabled(False)
            self.btn_run_analysis.setEnabled(False)
            self.btn_play_guitar.setEnabled(False)
            self.combo_stems.blockSignals(False)
            QMessageBox.warning(
                self,
                "Nenhuma faixa encontrada",
                "A separação terminou, mas nenhum arquivo de áudio foi "
                "encontrado na pasta de saída. Verifique os logs para mais "
                "detalhes.",
            )
            return

        self.combo_stems.addItems(stem_names)
        self.combo_stems.setEnabled(True)

        # Prioriza 'guitar' como seleção inicial, se existir; senão, o primeiro
        default_index = stem_names.index("guitar") if "guitar" in stem_names else 0
        self.combo_stems.setCurrentIndex(default_index)

        self.combo_stems.blockSignals(False)
        self.btn_run_analysis.setEnabled(True)

    # Análise

    def start_analysis(self) -> None:
        stem_name = self.combo_stems.currentText()

        if not stem_name:
            QMessageBox.warning(
                self,
                "Nenhuma faixa selecionada",
                "Selecione uma faixa isolada antes de executar o Tone Matching.",
            )
            return

        stem_path = Path(self.path_stems_dir) / f"{stem_name}.wav"

        if not stem_path.exists():
            logger.warning(f"Stem selecionado não encontrado em disco: {stem_path}")
            QMessageBox.critical(
                self,
                "Arquivo não encontrado",
                f"A faixa '{stem_name}.wav' não foi encontrada em disco.\n"
                f"Tente executar a separação novamente.",
            )
            return

        logger.info(f"Iniciando workflow análise (faixa selecionada: {stem_name}).")
        self.btn_run_analysis.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.progress_bar.setRange(0, 0)

        self._notify(
            "Tone Matching iniciado",
            f"Analisando a faixa '{stem_name}'…",
        )

        # Guarda qual stem está sendo analisado — usado depois para saber
        # se o combo foi trocado após a análise (ver _on_stem_selection_changed)
        self._analyzing_stem = stem_name

        self.analysis_thread = AnalysisWorker(str(stem_path))
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

        self.last_params = params
        self.last_analyzed_stem = getattr(self, "_analyzing_stem", "")
        self.btn_send_hardware.setEnabled(True)

        gate = params.get("noise_gate_threshold_db", "--")
        eq   = params.get("eq", {})
        eq_curve = params.get("eq_curve", [])
        waveform = params.get("waveform", {})
        is_silent = params.get("is_silent", False)

        self.lbl_gate.setText(f"Noise Gate: {gate} dB")
        self.lbl_eq.setText(
            f"EQ — Bass: {eq.get('bass', '--')}  |  "
            f"Mid: {eq.get('mid', '--')}  |  "
            f"Treble: {eq.get('treble', '--')}"
        )
        self.lbl_analyzed_stem.setText(
            f"Parâmetros calculados a partir da faixa: '{self.last_analyzed_stem}'"
        )

        self.waveform_plot.plot_waveform(waveform, label=self.last_analyzed_stem)
        self.eq_curve_plot.plot_eq_curve(eq_curve, label=self.last_analyzed_stem)

        if is_silent:
            self._set_status(
                "Aviso: a faixa analisada está silenciosa ou vazia."
            )
            self._notify(
                "Tone Matching concluído (com aviso)",
                f"A faixa '{self.last_analyzed_stem}' está silenciosa ou "
                f"vazia — os parâmetros calculados podem não ser confiáveis.",
                icon=QSystemTrayIcon.MessageIcon.Warning,
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
            self._notify(
                "Tone Matching concluído",
                f"Parâmetros calculados com sucesso para '{self.last_analyzed_stem}'.",
            )

    # Envio para hardware (ESP32-S3)

    def start_send_hardware(self) -> None:
        if not self.last_params:
            QMessageBox.warning(
                self,
                "Nenhum parâmetro calculado",
                "Execute a análise antes de enviar os dados para o pedal.",
            )
            return

        logger.info("Iniciando envio para a ESP32-S3.")
        self.btn_send_hardware.setEnabled(False)
        self.btn_run_analysis.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.progress_bar.setRange(0, 0)

        self._notify(
            "Envio para o pedal iniciado",
            "Enviando os parâmetros calculados para a ESP32-S3…",
        )

        # port=None → tenta autodetectar a placa; cai em modo simulado
        # (MOCK) automaticamente se nenhuma porta compatível for encontrada.
        # Isso permite usar o botão normalmente mesmo sem a placa em mãos.
        self.hardware_thread = HardwareWorker(self.last_params, port=None)
        self.hardware_thread.status.connect(self._set_status)
        self.hardware_thread.finished.connect(self._on_hardware_finished)
        self.hardware_thread.error.connect(self._on_hardware_error)
        self.hardware_thread.start()

    def _on_hardware_finished(self, was_mock: bool) -> None:
        logger.info("Workflow de envio para hardware finalizado.")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        self.btn_load.setEnabled(True)
        self.btn_run_analysis.setEnabled(True)
        self.btn_send_hardware.setEnabled(True)

        if was_mock:
            self._set_status(
                "Simulação concluída — nenhuma placa foi encontrada."
            )
            self._notify(
                "Envio simulado (sem hardware)",
                "Nenhuma ESP32-S3 foi detectada — o envio foi apenas "
                "simulado (modo MOCK).",
                icon=QSystemTrayIcon.MessageIcon.Warning,
            )
            QMessageBox.information(
                self,
                "Envio simulado (sem hardware)",
                "Nenhuma ESP32-S3 foi detectada na porta USB.\n\n"
                "Os parâmetros NÃO foram enviados para uma placa real — "
                "apenas simulados (modo MOCK), para fins de teste.\n\n"
                "Conecte a placa via USB e tente novamente quando ela "
                "estiver disponível."
            )
        else:
            self._set_status("Parâmetros enviados para o pedal!")
            self._notify(
                "Envio concluído",
                "Os parâmetros foram enviados com sucesso para a ESP32-S3.",
            )

    def _on_hardware_error(self, err_msg: str) -> None:
        logger.error(f"Erro ao enviar para a ESP32-S3:\n{err_msg}")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.btn_load.setEnabled(True)
        self.btn_run_analysis.setEnabled(bool(self.path_guitarra))
        self.btn_send_hardware.setEnabled(bool(self.last_params))

        self._set_status("Erro ao enviar para o pedal.")
        self._notify(
            "Falha no envio para o pedal",
            self._friendly_error_summary(err_msg),
            icon=QSystemTrayIcon.MessageIcon.Critical,
        )
        QMessageBox.critical(
            self,
            "Erro de comunicação",
            f"Não foi possível enviar os parâmetros para a ESP32-S3:\n\n"
            f"{self._friendly_error_summary(err_msg)}\n\n"
            f"Detalhes completos foram registrados no terminal/log.",
        )

    # Seleção de filtros (ESP32-S3)

    def start_query_filters(self) -> None:
        """Consulta a ESP32-S3 para descobrir quais filtros ela conhece."""
        logger.info("Iniciando consulta de filtros disponíveis.")
        self.btn_query_filters.setEnabled(False)
        self.btn_apply_filters.setEnabled(False)
        self.list_filters.clear()
        self.lbl_filters_status.setText("Consultando…")

        self._notify(
            "Consulta de filtros iniciada",
            "Perguntando ao pedal quais filtros estão disponíveis…",
        )

        self.filter_query_thread = FilterQueryWorker(port=None)
        self.filter_query_thread.status.connect(self._set_status)
        self.filter_query_thread.finished.connect(self._on_filters_received)
        self.filter_query_thread.error.connect(self._on_filter_query_error)
        self.filter_query_thread.start()

    def _on_filters_received(self, filters: list, was_mock: bool) -> None:
        logger.info(f"Filtros recebidos: {filters}")
        self.btn_query_filters.setEnabled(True)

        # Guarda os metadados completos de cada filtro (id, params) para uso
        # posterior — a QListWidget só mostra o nome, então associamos o
        # dicionário original a cada item via UserRole.
        self._known_filters = {f["id"]: f for f in filters}

        self.list_filters.clear()
        for f in filters:
            item = QListWidgetItem(f.get("name", f["id"]))
            item.setData(Qt.ItemDataRole.UserRole, f["id"])
            self.list_filters.addItem(item)

        if was_mock:
            self.lbl_filters_status.setText(
                f"{len(filters)} filtro(s) de exemplo (modo simulado — sem placa conectada)."
            )
            self._notify(
                "Filtros de exemplo carregados",
                "Nenhuma ESP32-S3 detectada — exibindo filtros simulados para teste da interface.",
                icon=QSystemTrayIcon.MessageIcon.Warning,
            )
        else:
            self.lbl_filters_status.setText(
                f"{len(filters)} filtro(s) disponível(is) no pedal."
            )
            self._notify(
                "Filtros recebidos",
                f"O pedal informou {len(filters)} filtro(s) disponível(is).",
            )

        self._set_status("Consulta de filtros concluída.")

    def _on_filter_query_error(self, err_msg: str) -> None:
        logger.error(f"Erro ao consultar filtros na ESP32-S3:\n{err_msg}")
        self.btn_query_filters.setEnabled(True)
        self.lbl_filters_status.setText("Falha ao consultar filtros.")

        self._set_status("Erro ao consultar filtros do pedal.")
        self._notify(
            "Falha ao consultar filtros",
            self._friendly_error_summary(err_msg),
            icon=QSystemTrayIcon.MessageIcon.Critical,
        )
        QMessageBox.critical(
            self,
            "Erro de comunicação",
            f"Não foi possível consultar os filtros da ESP32-S3:\n\n"
            f"{self._friendly_error_summary(err_msg)}\n\n"
            f"Detalhes completos foram registrados no terminal/log.",
        )

    def _on_filter_selection_changed(self) -> None:
        self.btn_apply_filters.setEnabled(
            len(self.list_filters.selectedItems()) > 0
        )

    def apply_selected_filters(self) -> None:
        """
        Esqueleto inicial: por ora, apenas registra e notifica quais
        filtros foram selecionados pelo usuário. O envio efetivo da
        configuração de cada filtro (com seus parâmetros específicos,
        ex.: freq_hz/gain_db de um low_shelf) depende de definirmos,
        junto ao firmware, o formato exato de configuração por filtro —
        próxima etapa depois deste esqueleto.
        """
        selected_ids = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.list_filters.selectedItems()
        ]
        selected_names = [item.text() for item in self.list_filters.selectedItems()]

        logger.info(f"Filtros selecionados para aplicação: {selected_ids}")

        self._set_status(
            f"{len(selected_ids)} filtro(s) selecionado(s) — "
            f"envio de configuração ainda não implementado."
        )
        self._notify(
            "Filtros selecionados",
            "Selecionados: " + ", ".join(selected_names),
        )
        QMessageBox.information(
            self,
            "Seleção registrada",
            "Filtros selecionados:\n\n"
            + "\n".join(f"• {name}" for name in selected_names)
            + "\n\nO envio da configuração de cada filtro para o pedal "
            "ainda será implementado — por enquanto, esta tela apenas "
            "registra a seleção."
        )

    # Playback original

    def toggle_original(self) -> None:
        if not self.path_original:
            logger.debug("Toggle de reprodução ignorado: nenhum arquivo carregado.")
            return

        state = self.player_orig.playbackState()

        if state == QMediaPlayer.PlaybackState.PlayingState:
            logger.debug("Pausando reprodução do áudio original.")
            self.player_orig.pause()

        elif state == QMediaPlayer.PlaybackState.PausedState:
            logger.debug("Retomando reprodução do áudio original.")
            self.player_orig.play()

        else:   # StoppedState — carrega e inicia
            logger.info(f"Reproduzindo áudio original: {self.path_original}")
            self.player_orig.setSource(
                QUrl.fromLocalFile(self.path_original)
            )
            self.player_orig.play()

    def stop_original(self) -> None:
        logger.debug("Parando reprodução do áudio original.")
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
            logger.debug("Toggle de stem ignorado: nenhuma separação disponível.")
            return

        state = self.player_stem.playbackState()

        if state == QMediaPlayer.PlaybackState.PlayingState:
            logger.debug("Pausando reprodução do stem.")
            self.player_stem.pause()

        elif state == QMediaPlayer.PlaybackState.PausedState:
            logger.debug("Retomando reprodução do stem.")
            self.player_stem.play()

        else:   # StoppedState — carrega stem selecionado
            faixa     = self.combo_stems.currentText()
            stem_file = Path(self.path_stems_dir) / f"{faixa}.wav"

            if not stem_file.exists():
                logger.warning(f"Stem solicitado não encontrado: {stem_file}")
                QMessageBox.warning(
                    self,
                    "Arquivo não encontrado",
                    f"A faixa '{faixa}.wav' não foi encontrada em disco.\n\n"
                    f"Ela pode ter sido movida ou apagada após a separação. "
                    f"Tente executar a separação novamente.",
                )
                return

            logger.info(f"Reproduzindo stem: {stem_file}")
            self.player_stem.setSource(QUrl.fromLocalFile(str(stem_file)))
            self.player_stem.play()

    def stop_stem(self) -> None:
        logger.debug("Parando reprodução do stem.")
        self.player_stem.stop()

    def _on_stem_state_changed(
        self, state: QMediaPlayer.PlaybackState
    ) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        paused  = state == QMediaPlayer.PlaybackState.PausedState
        self.btn_play_guitar.setText("⏸" if playing else "▶")
        self.btn_stop_guitar.setEnabled(playing or paused)

    def _on_stem_selection_changed(self, new_stem: str) -> None:
        """
        Para o stem atual quando o usuário troca de faixa no combo.

        Além disso, se o stem selecionado for diferente do que gerou os
        últimos parâmetros de Tone Matching (last_params), invalida esses
        parâmetros e desabilita o envio para o hardware — evita que o
        usuário envie, sem perceber, valores calculados para um stem
        diferente do que está selecionado agora (ex.: analisou 'guitar',
        trocou para 'bass' no combo, e clicaria 'Enviar' pensando que os
        dados são do 'bass').
        """
        self.player_stem.stop()

        if new_stem and new_stem != self.last_analyzed_stem and self.last_params:
            logger.debug(
                f"Stem selecionado ('{new_stem}') difere do último "
                f"analisado ('{self.last_analyzed_stem}'); invalidando "
                f"parâmetros calculados."
            )
            self.last_params = {}
            self.btn_send_hardware.setEnabled(False)
            self.lbl_gate.setText("Noise Gate: -- dB")
            self.lbl_eq.setText("EQ — Bass: --  |  Mid: --  |  Treble: --")
            self.lbl_analyzed_stem.setText("")
            self.waveform_plot.clear_plot()
            self.eq_curve_plot.clear_plot()
            self._set_status(
                f"Faixa alterada para '{new_stem}' — execute o Tone "
                f"Matching novamente para esta faixa."
            )

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
        logger.error(f"Erro recebido pela UI:\n{err_msg}")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.btn_load.setEnabled(True)

        # Corrige o botão de análise após um erro de separação: sem stems
        # disponíveis, não há como o combo estar em um estado válido.
        if not self.path_guitarra:
            self.combo_stems.clear()
            self.combo_stems.setEnabled(False)

        # Reabilita apenas os botões que fazem sentido no estado atual
        self.btn_run_demucs.setEnabled(bool(self.path_original))
        self.btn_run_analysis.setEnabled(bool(self.path_guitarra))
        self.btn_send_hardware.setEnabled(bool(self.last_params))

        self._set_status("Erro no processamento.")
        self._notify(
            "Falha no processamento",
            self._friendly_error_summary(err_msg),
            icon=QSystemTrayIcon.MessageIcon.Critical,
        )
        QMessageBox.critical(
            self,
            "Erro",
            f"{self._friendly_error_summary(err_msg)}\n\n"
            f"Detalhes completos foram registrados no terminal/log.",
        )

    @staticmethod
    def _friendly_error_summary(err_msg: str) -> str:
        """
        Extrai a última linha útil de um traceback do Python para exibir
        um resumo legível na UI, em vez do stack trace completo.
        Se não for possível extrair, devolve o texto original.
        """
        lines = [line.strip() for line in err_msg.strip().splitlines() if line.strip()]
        if not lines:
            return "Ocorreu um erro inesperado."
        return lines[-1]

    # Utilitários

    def _set_status(self, msg: str) -> None:
        logger.info(msg)
        self.lbl_status.setText(f"● {msg}")

    def _notify(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        duration_ms: int = 4000,
    ) -> None:
        """
        Exibe uma notificação nativa do sistema operacional (balão/toast),
        usada para avisar o início e a conclusão de processamentos longos
        (Demucs, Tone Matching, envio para hardware) mesmo quando a janela
        do app não está em foco.

        Se o sistema de bandeja não estiver disponível no SO atual (raro,
        mas pode acontecer em alguns ambientes Linux sem área de
        notificação), a chamada é ignorada silenciosamente — o status na
        barra inferior (_set_status) continua funcionando normalmente
        como alternativa.
        """
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.debug(
                "Bandeja do sistema indisponível; notificação suprimida: "
                f"{title} — {message}"
            )
            return

        self.tray_icon.showMessage(title, message, icon, duration_ms)

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
        logger.info("Encerrando aplicação — finalizando threads e players…")
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
            "hardware_thread",
            "filter_query_thread",
        ):
            self._stop_thread(attr)

        try:
            event.accept()
        except RuntimeError:
            pass

        logger.info("Aplicação encerrada.")


# Entry point

if __name__ == "__main__":
    logger.info("Inicializando QApplication…")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())