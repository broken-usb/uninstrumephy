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
from PyQt6.QtCore import (
    QLibraryInfo, QLocale, QRectF, QSize, QThread, QTranslator, pyqtSignal, QUrl, Qt, QTimer,
)
from PyQt6.QtGui import QIcon, QPixmap, QImage, QImageReader, QPainter, QPainterPath
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from tinytag import TinyTag

from core.logger import setup_logging
from gui.ui_loader import load_ui_file
from gui.tab_demucs import TabDemucs
from gui.tab_tonematching import TabToneMatching
from gui.tab_hardware import TabHardware
from gui import icons, theme
from gui.errors import show_error

# Inicialização do Logging (console + output/logs/latest-log.txt)
setup_logging()
logger = logging.getLogger(__name__)


def global_exception_hook(exctype, value, tb):
    """Intercepta exceções não tratadas em slots do Qt para evitar core dump."""
    err_str = "".join(traceback.format_exception(exctype, value, tb))
    logger.critical(f"Exceção não tratada capturada:\n{err_str}")

    if QApplication.instance():
        show_error(
            QApplication.activeWindow(),
            "Erro Crítico",
            err_str,
            headline="Ocorreu um erro interno na aplicação.",
        )


sys.excepthook = global_exception_hook


def _install_qt_translations(app: QApplication) -> None:
    """Traduz os textos internos do Qt (OK/Cancelar, "Mostrar detalhes"…).

    O PyQt6 já inclui as traduções; sem carregá-las, os botões padrão das
    caixas de diálogo aparecem em inglês no meio da interface em português.
    """
    translator = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil), "qtbase", "_", path):
        app.installTranslator(translator)
    else:
        logger.debug("Traduções do Qt não encontradas em %s; botões padrão ficarão em inglês.", path)


class MetadataWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self.file_path = file_path

    @staticmethod
    def _extract_cover(tag: TinyTag) -> bytes | None:
        """Bytes da capa embutida no arquivo (JPEG/PNG), ou None se não houver.

        Na tinytag 2.x, `tag.images.any` é uma PROPRIEDADE que devolve um
        objeto `Image` (os bytes ficam em `.data`), dando preferência à capa
        frontal. A versão antiga deste código chamava `images.any()` e
        engolia o erro, por isso nenhuma capa era exibida.
        """
        image = tag.images.any
        if image is None or not image.data:
            logger.info("Capa: nenhuma imagem embutida no arquivo.")
            return None
        logger.info(
            "Capa: imagem embutida encontrada (%r, %d bytes, tipo '%s').",
            image.mime_type or "formato não informado", len(image.data), image.name,
        )
        return MetadataWorker._strip_to_image(bytes(image.data))

    # Assinaturas que um arquivo de imagem tem nos primeiros bytes.
    _IMAGE_SIGNATURES = (
        b"\xff\xd8\xff",          # JPEG
        b"\x89PNG\r\n\x1a\n",     # PNG
        b"GIF87a", b"GIF89a",     # GIF
    )
    _IMAGE_SEARCH_WINDOW = 1024   # quadro APIC: tipo + descrição ficam bem antes disso

    @staticmethod
    def _strip_to_image(data: bytes) -> bytes:
        """Corrige capas lidas com bytes extras no início.

        A tinytag ignora o flag "data length indicator" dos quadros ID3 v2.4
        (usado por alguns programas que embutem capas, como em arquivos
        baixados com yt-dlp). Ela então lê os 4 bytes de tamanho como se
        fossem o tipo da imagem, e tudo fica deslocado: o resultado começa
        pela descrição ("\\x03Album cover\\x00") e só depois vem a imagem.
        Aqui localizamos a assinatura da imagem e descartamos o que vem antes.
        """
        def is_image_at(pos: int) -> bool:
            if any(data.startswith(sig, pos) for sig in MetadataWorker._IMAGE_SIGNATURES):
                return True
            return data.startswith(b"RIFF", pos) and data.startswith(b"WEBP", pos + 8)

        if is_image_at(0):
            return data
        window = data[:MetadataWorker._IMAGE_SEARCH_WINDOW]
        candidates = [pos for pos in range(1, len(window)) if is_image_at(pos)]
        if not candidates:
            return data  # formato desconhecido: deixa o Qt tentar e registrar a falha
        offset = candidates[0]
        logger.warning(
            "Capa: os dados lidos começavam %d bytes antes da imagem real "
            "(quadro ID3 interpretado incorretamente pela tinytag); corrigido.",
            offset,
        )
        return data[offset:]

    def run(self) -> None:
        try:
            logger.debug(f"Lendo metadados de: {self.file_path}")
            tag = TinyTag.get(self.file_path, image=True)
            # Uma capa defeituosa não deve impedir a exibição do título,
            # artista e duração: o erro fica só no log.
            try:
                image_data = self._extract_cover(tag)
            except Exception:
                logger.exception("Capa: falha ao extrair a imagem embutida.")
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


def _load_app_icon() -> QIcon:
    """
    Ícone do aplicativo (janela, barra de tarefas e bandeja).
    Usa gui/icons/app.svg (escalável) e gui/icons/app.png; se nenhum existir,
    cai para um ícone de pedal gerado pelo tema.
    """
    icon_dir = Path(__file__).resolve().parent / "gui" / "icons"
    icon = QIcon()
    for name in ("app.svg", "app.png"):
        file = icon_dir / name
        if file.exists():
            icon.addFile(str(file))
    if icon.isNull():
        icon = QIcon(icons.pixmap("pedal", 64, theme.tokens().accent))
    return icon


class MainWindow(QDialog):
    def __init__(self) -> None:
        super().__init__()
        load_ui_file("mainwindow.ui", self)
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
        app_icon = _load_app_icon()
        self.setWindowIcon(app_icon)
        self.tray_icon.setIcon(app_icon)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

        self.metadata_thread: MetadataWorker | None = None

        self.tab_demucs = TabDemucs()
        self.tab_tonematching = TabToneMatching()
        self.tab_hardware = TabHardware()

        self.tabsMain.addTab(self.tab_demucs, "Separação (Demucs)")
        self.tabsMain.addTab(self.tab_tonematching, "Tone Matching")
        self.tabsMain.addTab(self.tab_hardware, "Pedal (ESP32-S3)")
        self.tabsMain.setIconSize(QSize(18, 18))
        for index, name in enumerate(("equalizer", "waveform", "pedal")):
            icons.bind(lambda ic, i=index: self.tabsMain.setTabIcon(i, ic), name)

        self._setup_appearance()
        self._connect_signals()
        self._apply_master_volume()
        logger.info("Aplicação inicializada.")

    def _setup_appearance(self) -> None:
        """Papéis visuais (ver gui/theme.py) e dicas de acessibilidade."""
        self.btn_load.setProperty("role", "suggested")  # ação principal da janela

        # Ícones (gui/icons/*.svg) no lugar dos símbolos de texto.
        self.btn_load.setText(self.btn_load.text().lstrip("＋ ").strip())
        icons.bind(self.btn_load.setIcon, "folder-open", "accent")
        self.btn_record.setText(self.btn_record.text().lstrip("🎙 ").strip())
        icons.bind(self.btn_record.setIcon, "microphone")
        for btn in (self.btn_load, self.btn_record):
            btn.setIconSize(QSize(18, 18))
        for btn in (self.btn_stop_orig, self.btn_stop_guitar):
            btn.setText("")
            self._set_transport_icon(btn, "stop")
        for btn in (self.btn_play_orig, self.btn_play_guitar):
            btn.setText("")
            self._set_transport_icon(btn, "play")
        theme.on_change(self._refresh_transport_icons)
        self._show_cover_placeholder("music-note")
        for btn, tip in (
            (self.btn_play_orig, "Reproduzir ou pausar a música original"),
            (self.btn_stop_orig, "Parar a música original"),
            (self.btn_play_guitar, "Reproduzir ou pausar a faixa isolada"),
            (self.btn_stop_guitar, "Parar a faixa isolada"),
        ):
            btn.setProperty("role", "circular")
            btn.setIconSize(QSize(16, 16))
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)
        self.tabsMain.setDocumentMode(True)

        # --- Correções de layout: nada de alturas/larguras fixas que cortem conteúdo ---
        unlimited = 16777215
        for frame in (self.frameHeader, self.framePlayback):
            frame.setMinimumHeight(0)
            frame.setMaximumHeight(unlimited)  # a altura passa a seguir o conteúdo
        self.btn_load.setMaximumWidth(unlimited)
        self.btn_record.setMaximumWidth(unlimited)
        self.setMinimumSize(860, 680)

        # Alinha os dois blocos de reprodução: o da direita tem o seletor de faixa
        # ao lado do título, então o da esquerda ganha a mesma altura de linha.
        self.lbl_section_orig.setMinimumHeight(self.combo_stems.sizeHint().height())
        self.combo_stems.setMinimumWidth(130)

        # O quadrado da capa tem tamanho fixo (mainwindow.ui); a imagem é
        # reduzida para caber nele em _show_cover.
        self.lbl_cover.setWordWrap(True)

    def _set_transport_icon(self, button, name: str) -> None:
        button.setProperty("icon_name", name)
        button.setIcon(icons.icon(name))

    def _refresh_transport_icons(self) -> None:
        """Recolore os ícones de reprodução quando o tema muda."""
        for btn in (self.btn_play_orig, self.btn_stop_orig, self.btn_play_guitar, self.btn_stop_guitar):
            name = btn.property("icon_name")
            if name:
                btn.setIcon(icons.icon(name))

    def _show_cover(self, image_data: bytes | None) -> None:
        """Exibe a capa do álbum, ou o ícone padrão se não houver/for inválida."""
        if not image_data:
            self._show_cover_placeholder("music-note")
            return

        image = QImage.fromData(image_data)
        if image.isNull():
            logger.warning(
                "Capa: o Qt não conseguiu decodificar a imagem (%d bytes, início %s). "
                "Formatos de imagem disponíveis: %s",
                len(image_data), bytes(image_data[:12]).hex(" "),
                ", ".join(bytes(f).decode() for f in QImageReader.supportedImageFormats()),
            )
            self._show_cover_placeholder("music-note")
            return

        pixmap = self._fit_cover(image)

        # Sem setText("") depois: no QLabel, definir texto apaga a imagem.
        icons.clear_label_icon(self.lbl_cover)
        self.lbl_cover.setPixmap(pixmap)
        logger.info(
            "Capa: exibida (%dx%d original, %dx%d na tela, escala %.2f).",
            image.width(), image.height(), pixmap.width(), pixmap.height(),
            pixmap.devicePixelRatio(),
        )

    def _fit_cover(self, image: QImage) -> QPixmap:
        """Reduz a capa para caber DENTRO do quadrado fixo, sem alterá-lo.

        Mantém a proporção (uma capa 16:9 fica com faixas vazias em cima e
        embaixo) e arredonda os cantos para acompanhar a borda do quadrado.
        """
        # Área útil do quadrado, já descontada a borda do tema (gui/theme.py).
        self.lbl_cover.ensurePolished()  # garante que a borda do estilo já conta
        area = self.lbl_cover.contentsRect().size()
        # Em telas HiDPI (escala 125%, 200%…) a imagem é reduzida para a
        # resolução física, senão a capa fica borrada.
        dpr = self.lbl_cover.devicePixelRatioF()
        scaled = image.scaled(
            round(area.width() * dpr), round(area.height() * dpr),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        rounded = QPixmap(scaled.size())
        rounded.fill(Qt.GlobalColor.transparent)
        path = QPainterPath()
        radius = (theme.RADIUS_CARD - 1) * dpr  # 1 px de borda
        path.addRoundedRect(QRectF(rounded.rect()), radius, radius)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipPath(path)
        painter.drawImage(0, 0, scaled)
        painter.end()
        rounded.setDevicePixelRatio(dpr)
        return rounded

    def _show_cover_placeholder(self, name: str) -> None:
        """Ícone no lugar da capa quando não há imagem."""
        self.lbl_cover.clear()
        icons.bind_pixmap(self.lbl_cover, name, 72)

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
        try:
            from gui.dialog_record import DialogRecord as RecordDialog
        except ImportError:
            from gui.dialog_record import RecordDialog

        dlg = RecordDialog(self)
        if hasattr(dlg, "recording_finished"):
            dlg.recording_finished.connect(self.load_direct_audio)
        dlg.exec()
        # Sem isto, cada abertura deixaria o diálogo (filho desta janela) e
        # seu ouvinte de troca de tema vivos até o fim do programa. O ouvinte
        # é descartado por gui/theme.py quando o widget já foi destruído.
        if hasattr(dlg, "schedule_deletion"):
            dlg.schedule_deletion()
        else:
            dlg.deleteLater()

    def load_direct_audio(self, filepath: str, auto_run_tonematching: bool = False) -> None:
        """Carrega a gravação direta da guitarra, ignorando o Demucs."""
        if not filepath or not Path(filepath).exists():
            return

        logger.info(f"Carregando áudio de entrada direta: {filepath}")
        self.path_original = filepath
        self.path_guitarra = filepath
        self.path_stems_dir = str(Path(filepath).parent)

        try:
            self.player_orig.stop()
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
        self._show_cover_placeholder("plug")

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
            if file_path_obj.stat().st_size == 0:
                QMessageBox.warning(self, "Arquivo vazio", "O arquivo selecionado possui 0 bytes.")
                return
        except OSError as exc:
            QMessageBox.critical(self, "Arquivo inacessível", str(exc))
            return

        self.path_original = file_name

        try:
            self.player_orig.stop()
            self.player_stem.stop()
        except RuntimeError:
            pass

        self.lbl_filepath.setText(Path(file_name).name)
        self.lbl_info.setText("Carregando metadados…")
        self.lbl_metadata.setText("Carregando metadados…")
        self._show_cover_placeholder("music-note")

        if self.metadata_thread is not None:
            # Não bloqueamos a UI esperando a thread antiga terminar:
            # apenas a desconectamos dos slots (ela seguirá rodando em
            # segundo plano e se autodestrói via deleteLater ao concluir).
            # Os handlers `_on_metadata_finished`/`_on_metadata_error` já
            # ignoram sinais de threads que não são mais a atual.
            try:
                self.metadata_thread.finished.disconnect(self._on_metadata_finished)
                self.metadata_thread.error.disconnect(self._on_metadata_error)
            except (RuntimeError, TypeError):
                pass
            self.metadata_thread = None

        self.metadata_thread = MetadataWorker(file_name)
        self.metadata_thread.finished.connect(self._on_metadata_finished)
        self.metadata_thread.finished.connect(self.metadata_thread.deleteLater)
        self.metadata_thread.error.connect(self._on_metadata_error)
        self.metadata_thread.error.connect(self.metadata_thread.deleteLater)
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

        self._show_cover(params.get("image_data"))

        self.btn_play_orig.setEnabled(True)
        self.btn_stop_orig.setEnabled(False)
        self._set_status("Música carregada.")

    def _on_metadata_error(self, err_msg: str) -> None:
        # Guarda contra corrida: se o usuário trocou de arquivo enquanto
        # esta MetadataWorker ainda rodava, `self.metadata_thread` já
        # aponta para uma thread mais nova (ou None). Nesse caso, este
        # sinal de erro é de uma leitura obsoleta e não deve sobrescrever
        # os metadados corretos (já carregados ou em carregamento) do
        # arquivo atual.
        if self.sender() is not self.metadata_thread:
            logger.debug("Sinal de erro de metadados obsoleto ignorado (arquivo já trocado).")
            return

        self.lbl_info.setText(f"{Path(self.path_original).stem}  |  --:--")
        self.lbl_metadata.setText("Sem metadados.")
        self._show_cover_placeholder("music-note")
        self.btn_play_orig.setEnabled(True)
        self.btn_stop_orig.setEnabled(False)
        self._set_status("Música carregada.")

    def _on_demucs_started(self) -> None:
        self.btn_load.setEnabled(False)
        self.btn_record.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self._notify(
            "Separação de faixas iniciada",
            f"Processando '{Path(self.path_original).name}' com o Demucs…",
        )

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
        # Seleciona a faixa que a separação devolveu como guitarra: "guitar"
        # no htdemucs_6s, "other" nos modelos de 4 faixas.
        preferred = Path(self.path_guitarra).stem if self.path_guitarra else "guitar"
        default_index = stem_names.index(preferred) if preferred in stem_names else 0
        self.combo_stems.setCurrentIndex(default_index)
        self.combo_stems.blockSignals(False)
        self._propagate_stem_selection(stem_names[default_index])

    def _propagate_stem_selection(self, stem_name: str) -> None:
        stem_path = ""
        if stem_name and self.path_stems_dir:
            candidate = Path(self.path_stems_dir) / f"{stem_name}.wav"
            if candidate.exists():
                stem_path = str(candidate.resolve())
        elif stem_name and self.path_guitarra:
            stem_path = str(Path(self.path_guitarra).resolve())
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
        self._notify("Envio iniciado", "Enviando os parâmetros dos efeitos para a ESP32-S3…")

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
        # Antes só havia a notificação da bandeja, que não aparece em ambientes
        # sem bandeja (ex.: GNOME padrão): o usuário não via o motivo da falha.
        # A notificação continua útil quando a janela não está em foco.
        if not self.isActiveWindow():
            self._notify(
                "Falha no envio",
                "Não foi possível enviar os parâmetros para a pedaleira.",
                icon=QSystemTrayIcon.MessageIcon.Critical,
            )
        show_error(
            self,
            "Falha no envio para a pedaleira",
            err_msg,
            hint="Verifique o cabo USB e se a Placa A está ligada, depois tente de novo.",
        )

    def _on_worker_error(self, err_msg: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.btn_load.setEnabled(True)
        self.btn_record.setEnabled(True)
        self._set_status("Erro no processamento.")
        show_error(self, "Erro no processamento", err_msg)

    def toggle_original(self) -> None:
        if not self.path_original:
            return
        state = self.player_orig.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player_orig.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.player_orig.play()
        else:
            abs_path = str(Path(self.path_original).resolve())
            self.player_orig.setSource(QUrl.fromLocalFile(abs_path))
            self.player_orig.play()

    def stop_original(self) -> None:
        self.player_orig.stop()

    def _on_orig_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        paused = state == QMediaPlayer.PlaybackState.PausedState
        self._set_transport_icon(self.btn_play_orig, "pause" if playing else "play")
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
            stem_file = (
                Path(self.path_stems_dir) / f"{faixa}.wav"
                if self.path_stems_dir
                else Path(self.path_guitarra)
            )
            if not stem_file.exists():
                if self.path_guitarra and Path(self.path_guitarra).exists():
                    stem_file = Path(self.path_guitarra)
                else:
                    QMessageBox.warning(
                        self, "Arquivo não encontrado", f"A faixa '{faixa}.wav' não foi encontrada."
                    )
                    return
            self.player_stem.setSource(QUrl.fromLocalFile(str(stem_file.resolve())))
            self.player_stem.play()

    def stop_stem(self) -> None:
        self.player_stem.stop()

    def _on_stem_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        paused = state == QMediaPlayer.PlaybackState.PausedState
        self._set_transport_icon(self.btn_play_guitar, "pause" if playing else "play")
        self.btn_stop_guitar.setEnabled(playing or paused)

    def _on_stem_selection_changed(self, new_stem: str) -> None:
        self.player_stem.stop()
        self._propagate_stem_selection(new_stem)
        last_analyzed = getattr(self.tab_tonematching, "last_analyzed_stem", None)
        if new_stem and new_stem != last_analyzed:
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

    def _notify(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
    ) -> None:
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

        if hasattr(self.tab_demucs, "stop_thread"):
            self.tab_demucs.stop_thread()
        if hasattr(self.tab_tonematching, "stop_thread"):
            self.tab_tonematching.stop_thread()
        if hasattr(self.tab_hardware, "stop_threads"):
            self.tab_hardware.stop_threads()

        event.accept()


def _self_test() -> int:
    """Verifica, sem abrir janela, se todas as partes do programa carregam.

    Usado pelo build do AppImage (o release só é publicado se passar) e útil
    para diagnosticar uma instalação: `main.py --self-test`.
    """
    import os
    import platform
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    failures = 0

    def check(name: str, fn) -> None:
        nonlocal failures
        try:
            detail = fn()
            print(f"[OK]    {name}" + (f": {detail}" if detail else ""))
        except Exception as exc:
            failures += 1
            print(f"[FALHA] {name}: {type(exc).__name__}: {exc}")
            logger.exception("Autoteste: %s", name)

    print(f"Uninstrumephy — autoteste (Python {platform.python_version()}, {sys.executable})")

    def torch_check():
        import torch
        torch.ones(4) @ torch.ones(4)
        return f"torch {torch.__version__}, CUDA disponível: {torch.cuda.is_available()}"

    def demucs_check():
        from core.separator import AudioSeparator
        import demucs
        return f"demucs {getattr(demucs, '__version__', '?')}, modelos: {', '.join(AudioSeparator.AVAILABLE_MODELS)}"

    def analysis_check():
        import numpy as np
        import soundfile as sf
        from core.analyzer import AudioAnalyzer
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "tom.wav"
            t = np.arange(22050) / 22050.0
            sf.write(str(wav), 0.3 * np.sin(2 * np.pi * 220 * t), 22050)
            params = AudioAnalyzer().analyze_stem(str(wav))
        return f"gate {params['noise_gate_threshold_db']} dB, centroide {params['spectral_centroid_hz']} Hz"

    def audio_check():
        from core import audio_recorder
        sd = audio_recorder._import_sounddevice()
        return (f"{sd.get_portaudio_version()[1]} em {sd._libname}; "
                f"{len(audio_recorder.list_input_devices())} entrada(s)")

    def gui_check():
        app = QApplication.instance() or QApplication(sys.argv)
        _install_qt_translations(app)
        theme.install(app)
        window = MainWindow()
        player = QMediaPlayer()
        tabs = window.tabsMain.count()
        window.close()
        del player
        return f"Qt {app.platformName()}, {tabs} abas"

    def paths_check():
        from core import paths
        folder = paths.data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".autoteste"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return f"dados em {folder} (gravável), presets em {paths.presets_dir()}"

    def https_check():
        # Sem certificados, o download dos modelos do Demucs (feito na primeira
        # separação) falha. O Python do AppImage os recebe por SSL_CERT_FILE,
        # definido pelo wrapper do python-appimage. Verificado sem usar a rede.
        import ssl
        verify = ssl.get_default_verify_paths()
        loaded = ssl.create_default_context().cert_store_stats()["x509_ca"]
        capath = Path(verify.capath) if verify.capath else None
        if loaded == 0 and not (capath and capath.is_dir() and any(capath.iterdir())):
            raise RuntimeError(
                f"nenhum certificado encontrado (cafile={verify.cafile}, capath={verify.capath}); "
                "o download dos modelos do Demucs falharia"
            )
        return f"{loaded} certificados carregados" if loaded else f"certificados em {capath}"

    check("PyTorch", torch_check)
    check("Demucs", demucs_check)
    check("Certificados HTTPS", https_check)
    check("Análise (librosa)", analysis_check)
    check("Áudio (PortAudio)", audio_check)
    check("Interface (Qt)", gui_check)
    check("Pastas de dados", paths_check)
    print("Resultado:", "tudo certo" if not failures else f"{failures} falha(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())

    if sys.platform == "win32":
        # Faz a barra de tarefas do Windows usar o ícone do app (e não o do Python).
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("uninstrumephy.app")

    app = QApplication(sys.argv)
    _install_qt_translations(app)
    theme.install(app)  # claro/escuro seguindo o sistema
    app.setWindowIcon(_load_app_icon())  # também vale para os diálogos
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())