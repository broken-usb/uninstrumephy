import sys
import os
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from tinytag import TinyTag

from gui.ui_mainwindow import Ui_Dialog
from core.separator import AudioSeparator
from core.analyzer import AudioAnalyzer

# ==========================================
# 1. O MOTOR ASSÍNCRONO (WORKER THREAD)
# ==========================================
class AIMirWorker(QThread):
    finished = pyqtSignal(dict, str) 
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, audio_path):
        super().__init__()
        self.audio_path = audio_path

    def run(self):
        try:
            self.status.emit("Iniciando IA (Demucs)... Isso pode demorar...")
            sep = AudioSeparator(output_dir="output")
            guitar_path = sep.extract_guitar(self.audio_path)

            if guitar_path:
                self.status.emit("Extraindo parâmetros matemáticos (Librosa)...")
                ana = AudioAnalyzer()
                params = ana.analyze_guitar(guitar_path)
                
                stems_dir = os.path.dirname(guitar_path)
                self.finished.emit(params, stems_dir)
            else:
                self.error.emit("Falha ao isolar as faixas.")
                
        except Exception as e:
            self.error.emit(f"Erro: {str(e)}")

# ==========================================
# 2. A JANELA PRINCIPAL (CONTROLADOR)
# ==========================================
class MainWindow(QDialog, Ui_Dialog):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.path_original = ""
        self.path_stems_dir = ""

        # =====================================
        # CONFIGURAÇÃO: DOIS MOTORES DE ÁUDIO
        # =====================================
        # Motor 1: Música Original
        self.audio_out_orig = QAudioOutput()
        self.audio_out_orig.setVolume(self.slider_vol_orig.value() / 100.0)
        self.player_orig = QMediaPlayer()
        self.player_orig.setAudioOutput(self.audio_out_orig)

        # Motor 2: Faixa Isolada (Stems)
        self.audio_out_stem = QAudioOutput()
        self.audio_out_stem.setVolume(self.slider_vol_stem.value() / 100.0)
        self.player_stem = QMediaPlayer()
        self.player_stem.setAudioOutput(self.audio_out_stem)

        # =====================================
        # CONEXÕES DA INTERFACE (SIGNALS & SLOTS)
        # =====================================
        self.btn_load.clicked.connect(self.load_audio_file)
        
        # Conexões de Volume
        self.slider_vol_orig.valueChanged.connect(lambda v: self.audio_out_orig.setVolume(v / 100.0))
        self.slider_vol_stem.valueChanged.connect(lambda v: self.audio_out_stem.setVolume(v / 100.0))
        
        # Conexões de Play/Stop
        self.btn_play_orig.clicked.connect(self.play_original)
        self.btn_stop_orig.clicked.connect(lambda: self.player_orig.stop())
        self.btn_play_guitar.clicked.connect(self.play_stem)
        self.btn_stop_guitar.clicked.connect(lambda: self.player_stem.stop())

        # Conexões das Barras de Tempo (Seekbars) - Original
        self.player_orig.durationChanged.connect(lambda d: self.slider_seek_orig.setMaximum(d))
        self.player_orig.positionChanged.connect(lambda p: self.slider_seek_orig.setValue(p))
        self.slider_seek_orig.sliderMoved.connect(lambda p: self.player_orig.setPosition(p))

        # Conexões das Barras de Tempo (Seekbars) - Stems
        self.player_stem.durationChanged.connect(lambda d: self.slider_seek_stem.setMaximum(d))
        self.player_stem.positionChanged.connect(lambda p: self.slider_seek_stem.setValue(p))
        self.slider_seek_stem.sliderMoved.connect(lambda p: self.player_stem.setPosition(p))

    def load_audio_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Selecione a Música", "", "Audio Files (*.mp3 *.wav *.flac)"
        )
        
        if file_name:
            self.path_original = file_name
            self.lbl_filepath.setText(f"Arquivo: {os.path.basename(file_name)}")
            
            # --- EXTRAÇÃO DE METADADOS E CAPA ---
            try:
                tag = TinyTag.get(file_name, image=True)
                titulo = tag.title if tag.title else "Desconhecido"
                artista = tag.artist if tag.artist else "Desconhecido"
                album = tag.album if tag.album else "Desconhecido"
                
                self.lbl_metadata.setText(f"Música: {titulo}\nArtista: {artista}\nÁlbum: {album}")
                
                # Extrai a capa
                img_data = tag.get_image()
                if img_data:
                    img = QImage()
                    img.loadFromData(img_data)
                    self.lbl_cover.setPixmap(QPixmap(img))
                else:
                    self.lbl_cover.setText("Capa não disponível")
            except Exception as e:
                self.lbl_metadata.setText("Sem metadados.")
                self.lbl_cover.setText("Sem Capa")
            
            # Prepara a UI para análise
            self.btn_play_orig.setEnabled(True)
            self.btn_stop_orig.setEnabled(True)
            self.btn_play_guitar.setEnabled(False)
            self.btn_stop_guitar.setEnabled(False)
            self.combo_stems.setEnabled(False)
            
            self.start_analysis(file_name)

    def start_analysis(self, file_path):
        self.btn_load.setEnabled(False) 
        self.progress_bar.setRange(0, 0)

        self.worker = AIMirWorker(file_path)
        self.worker.status.connect(self.update_status)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.start()

    def update_status(self, msg):
        self.lbl_status.setText(f"Status: {msg}")

    def on_analysis_finished(self, params, stems_dir):
        self.path_stems_dir = stems_dir
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Status: Concluído com sucesso!")
        self.btn_load.setEnabled(True)

        self.btn_play_guitar.setEnabled(True)
        self.btn_stop_guitar.setEnabled(True)
        self.combo_stems.setEnabled(True)

        gate = params.get("noise_gate_threshold_db", "--")
        eq = params.get("eq", {})
        self.lbl_gate.setText(f"Threshold: {gate} dB")
        self.lbl_eq.setText(f"EQ: B({eq.get('bass')}) | M({eq.get('mid')}) | T({eq.get('treble')})")

    def on_analysis_error(self, err_msg):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Status: Erro no processamento.")
        self.btn_load.setEnabled(True)
        QMessageBox.critical(self, "Erro", err_msg)

    # --- FUNÇÕES DE PLAYBACK INDEPENDENTES ---
    def play_original(self):
        if self.path_original:
            self.player_orig.setSource(QUrl.fromLocalFile(self.path_original))
            self.player_orig.play()

    def play_stem(self):
        if self.path_stems_dir:
            faixa = self.combo_stems.currentText()
            stem_file = os.path.join(self.path_stems_dir, f"{faixa}.wav")
            
            if os.path.exists(stem_file):
                self.player_stem.setSource(QUrl.fromLocalFile(stem_file))
                self.player_stem.play()
            else:
                QMessageBox.warning(self, "Aviso", f"A faixa {faixa}.wav não foi encontrada.")

# ==========================================
# 3. PONTO DE ENTRADA
# ==========================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())