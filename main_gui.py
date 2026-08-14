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
from PyQt6.QtCore import QThread, pyqtSignal, QUrl, Qt
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from tinytag import TinyTag

from gui.ui_mainwindow import Ui_Dialog
from gui.tab_demucs import TabDemucs
from gui.tab_tonematching import TabToneMatching
from gui.tab_hardware import TabHardware

# Logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s -> %(message)s",
)
logger = logging.getLogger(__name__)


# Metadata worker
#
# Único worker que continua morando na casca raiz: metadados (título,
# artista, capa) são um dado compartilhado entre todas as abas, não algo
# específico de Demucs, Tone Matching ou Hardware.

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


# Main window

class MainWindow(QDialog, Ui_Dialog):
    """
    Janela principal — atua como orquestradora "fina" entre as três abas
    de funcionalidade (Demucs, Tone Matching, Hardware) e o estado
    compartilhado entre elas: arquivo carregado, metadados, players de
    áudio (original e stem) e a seleção atual de stem no combo.

    Cada aba é um QWidget independente (gui/tab_*.py) que só se comunica
    com esta janela via sinais Qt — a janela nunca acessa widgets internos
    de uma aba diretamente, só a API pública que cada aba expõe
    (set_audio_path, set_selected_stem, set_params, reset, etc.).
    """

    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        logger.info("Inicializando aplicação…")

        # Estado compartilhado entre abas
        self.path_original:  str = ""
        self.path_guitarra:  str = ""
        self.path_stems_dir: str = ""

        # Players e saídas — compartilhados e sempre visíveis,
        # independente de qual aba está selecionada
        self.audio_out_orig = QAudioOutput()
        self.player_orig    = QMediaPlayer()
        self.player_orig.setAudioOutput(self.audio_out_orig)

        self.audio_out_stem = QAudioOutput()
        self.player_stem    = QMediaPlayer()
        self.player_stem.setAudioOutput(self.audio_out_stem)

        # Ícone de bandeja usado para exibir notificações nativas do SO
        # ao iniciar/concluir processamentos longos. Não exibe um ícone
        # visível na bandeja por padrão em todos os SOs — serve só como
        # emissor de notificação.
        self.tray_icon = QSystemTrayIcon(self)
        app_icon = self.style().standardIcon(
            self.style().StandardPixmap.SP_MediaPlay
        )
        self.tray_icon.setIcon(app_icon)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

        # Threads
        self.metadata_thread: MetadataWorker | None = None

        # Monta as três abas de funcionalidade dentro do QTabWidget raiz
        self.tab_demucs = TabDemucs()
        self.tab_tonematching = TabToneMatching()
        self.tab_hardware = TabHardware()

        self.tabsMain.addTab(self.tab_demucs, "🎚  Separação (Demucs)")
        self.tabsMain.addTab(self.tab_tonematching, "📊  Tone Matching")
        self.tabsMain.addTab(self.tab_hardware, "🔌  Pedal (ESP32-S3)")

        # Conecta sinais
        self._connect_signals()

        # Volume inicial
        self._apply_master_volume()

        logger.info("Aplicação inicializada.")

    # Conexão de sinais

    def _connect_signals(self) -> None:
        self.btn_load.clicked.connect(self.load_audio_file)

        # Atualiza volumes
        self.slider_vol_orig.valueChanged.connect(self._apply_master_volume)
        self.slider_vol_stem.valueChanged.connect(self._apply_master_volume)

        # Playback original
        self.btn_play_orig.clicked.connect(self.toggle_original)
        self.btn_stop_orig.clicked.connect(self.stop_original)

        # Playback stem
        self.btn_play_guitar.clicked.connect(self.toggle_stem)
        self.btn_stop_guitar.clicked.connect(self.stop_stem)

        # Mudança de faixa no combo → para stem atual e propaga seleção
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

        # Sinais das abas → orquestração compartilhada (status, notificações,
        # progresso, e propagação de resultados entre abas)
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
        if self.metadata_thread is not None:
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

        # Invalida resultados anteriores de stems/análise em todas as abas
        self.path_guitarra  = ""
        self.path_stems_dir = ""
        self.btn_play_guitar.setEnabled(False)
        self.btn_stop_guitar.setEnabled(False)
        self.combo_stems.clear()
        self.combo_stems.setEnabled(False)
        self.lbl_gate.setText("Noise Gate: -- dB")
        self.lbl_eq.setText("EQ — Bass: --  |  Mid: --  |  Treble: --")

        self.tab_demucs.reset()
        self.tab_demucs.set_audio_path(file_name)
        self.tab_tonematching.reset()
        self.tab_hardware.reset()

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
        self._set_status("Música carregada.")

    def _on_metadata_error(self, err_msg: str) -> None:
        logger.error("Falha ao carregar metadados.")
        self.lbl_info.setText(f"{Path(self.path_original).stem}  |  --:--")
        self.lbl_metadata.setText("Sem metadados.")
        self.lbl_cover.clear()
        self.lbl_cover.setText("♪")
        self.btn_play_orig.setEnabled(True)
        self.btn_stop_orig.setEnabled(False)
        self._set_status("Música carregada.")

    # Orquestração: aba Demucs

    def _on_demucs_started(self) -> None:
        self.btn_load.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self._notify(
            "Separação de faixas iniciada",
            f"Processando '{Path(self.path_original).name}' com o Demucs…",
        )

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

        # Propaga a seleção inicial para a aba de Tone Matching
        self._propagate_stem_selection(stem_names[default_index])

    def _propagate_stem_selection(self, stem_name: str) -> None:
        """Informa à aba de Tone Matching qual stem está selecionado agora."""
        stem_path = ""
        if stem_name and self.path_stems_dir:
            candidate = Path(self.path_stems_dir) / f"{stem_name}.wav"
            if candidate.exists():
                stem_path = str(candidate)
        self.tab_tonematching.set_selected_stem(stem_name, stem_path)

    # Orquestração: aba Tone Matching

    def _on_analysis_started(self) -> None:
        self.btn_load.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        stem_name = self.combo_stems.currentText()
        self._notify(
            "Tone Matching iniciado",
            f"Analisando a faixa '{stem_name}'…",
        )

    def _on_analysis_finished(self, params: dict, analyzed_stem: str) -> None:
        logger.info("Workflow análise finalizado.")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.btn_load.setEnabled(True)

        gate = params.get("noise_gate_threshold_db", "--")
        eq   = params.get("eq", {})
        is_silent = params.get("is_silent", False)

        self.lbl_gate.setText(f"Noise Gate: {gate} dB")
        self.lbl_eq.setText(
            f"EQ — Bass: {eq.get('bass', '--')}  |  "
            f"Mid: {eq.get('mid', '--')}  |  "
            f"Treble: {eq.get('treble', '--')}"
        )

        # Propaga os parâmetros calculados para a aba de Hardware, que é
        # quem efetivamente envia esses dados para a ESP32-S3
        self.tab_hardware.set_params(params)

        if is_silent:
            self._set_status(
                "Aviso: a faixa analisada está silenciosa ou vazia."
            )
            self._notify(
                "Tone Matching concluído (com aviso)",
                f"A faixa '{analyzed_stem}' está silenciosa ou vazia — "
                f"os parâmetros calculados podem não ser confiáveis.",
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
                f"Parâmetros calculados com sucesso para '{analyzed_stem}'.",
            )

    # Orquestração: aba Hardware

    def _on_hardware_send_started(self) -> None:
        self.btn_load.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self._notify(
            "Envio para o pedal iniciado",
            "Enviando os parâmetros calculados para a ESP32-S3…",
        )

    def _on_hardware_send_finished(self, was_mock: bool) -> None:
        logger.info("Workflow de envio para hardware finalizado.")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.btn_load.setEnabled(True)

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
        else:
            self._set_status("Parâmetros enviados para o pedal!")
            self._notify(
                "Envio concluído",
                "Os parâmetros foram enviados com sucesso para a ESP32-S3.",
            )

    def _on_hardware_send_error(self, err_msg: str) -> None:
        logger.error(f"Erro ao enviar para a ESP32-S3:\n{err_msg}")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.btn_load.setEnabled(True)

        self._set_status("Erro ao enviar para o pedal.")
        self._notify(
            "Falha no envio para o pedal",
            self._friendly_error_summary(err_msg),
            icon=QSystemTrayIcon.MessageIcon.Critical,
        )

    # Erros genéricos (Demucs / Tone Matching)

    def _on_worker_error(self, err_msg: str) -> None:
        logger.error(f"Erro recebido de uma aba:\n{err_msg}")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.btn_load.setEnabled(True)

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
        Para o stem atual quando o usuário troca de faixa no combo, e
        propaga a nova seleção para a aba de Tone Matching — que, por sua
        vez, invalida os resultados exibidos se o novo stem for diferente
        do que gerou os últimos parâmetros calculados.

        Também limpa o resumo de gate/EQ na barra de status e desabilita
        o envio para hardware, já que os parâmetros deixam de corresponder
        à faixa atualmente selecionada.
        """
        self.player_stem.stop()

        self._propagate_stem_selection(new_stem)

        if new_stem and new_stem != self.tab_tonematching.last_analyzed_stem:
            self.lbl_gate.setText("Noise Gate: -- dB")
            self.lbl_eq.setText("EQ — Bass: --  |  Mid: --  |  Treble: --")
            self.tab_hardware.set_params({})

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

    # Cleanup

    def closeEvent(self, event) -> None:
        """Para players e aguarda threads das abas antes de fechar a janela."""
        logger.info("Encerrando aplicação — finalizando threads e players…")
        try:
            self.player_orig.stop()
        except RuntimeError:
            pass

        try:
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
