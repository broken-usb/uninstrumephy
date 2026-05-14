import sys
import os
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

# Importa o visual gerado (Classe Ui_Dialog conforme seu arquivo)
from gui.ui_mainwindow import Ui_Dialog

# Importa os motores de IA
from core.separator import AudioSeparator
from core.analyzer import AudioAnalyzer

# ==========================================
# 1. O MOTOR ASSÍNCRONO (WORKER THREAD)
# ==========================================
class AIMirWorker(QThread):
    finished = pyqtSignal(dict, str) # Enviamos os parâmetros E o caminho da guitarra
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, audio_path):
        super().__init__()
        self.audio_path = audio_path

    def run(self):
        try:
            self.status.emit("Iniciando IA (Demucs)... Isolando guitarra...")
            
            sep = AudioSeparator(output_dir="output")
            guitar_path = sep.extract_guitar(self.audio_path)

            if guitar_path:
                self.status.emit("Extraindo parâmetros matemáticos (Librosa)...")
                ana = AudioAnalyzer()
                params = ana.analyze_guitar(guitar_path)
                
                # Sucesso: envia os dados e o caminho do arquivo para o player
                self.finished.emit(params, guitar_path)
            else:
                self.error.emit("Falha ao isolar a guitarra.")
                
        except Exception as e:
            self.error.emit(f"Erro: {str(e)}")


# ==========================================
# 2. A JANELA PRINCIPAL (CONTROLADOR)
# ==========================================
class MainWindow(QDialog, Ui_Dialog):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # Variáveis para armazenar os caminhos dos áudios
        self.path_original = ""
        self.path_guitarra = ""

        # Configuração do Motor de Áudio
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(0.7)
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)

        # Conexões dos Botões de Interface
        self.btn_load.clicked.connect(self.load_audio_file)
        
        # Conexões dos Novos Botões de Áudio
        self.btn_play_orig.clicked.connect(self.play_original)
        self.btn_stop_orig.clicked.connect(self.stop_audio)
        
        self.btn_play_guitar.clicked.connect(self.play_guitarra)
        self.btn_stop_guitar.clicked.connect(self.stop_audio)

    def load_audio_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Selecione a Música", "", "Audio Files (*.mp3 *.wav *.flac)"
        )
        
        if file_name:
            self.path_original = file_name
            self.lbl_filepath.setText(f"Arquivo: {os.path.basename(file_name)}")
            
            # Ativa os botões do áudio original
            self.btn_play_orig.setEnabled(True)
            self.btn_stop_orig.setEnabled(True)
            
            # Resetamos os da guitarra (caso o usuário carregue uma nova música)
            self.btn_play_guitar.setEnabled(False)
            self.btn_stop_guitar.setEnabled(False)
            
            self.start_analysis(file_name)

    def start_analysis(self, file_path):
        self.btn_load.setEnabled(False) 
        self.progress_bar.setRange(0, 0) # Modo carregando

        self.worker = AIMirWorker(file_path)
        self.worker.status.connect(self.update_status)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.start()

    def update_status(self, msg):
        self.lbl_status.setText(f"Status: {msg}")

    def on_analysis_finished(self, params, guitar_path):
        self.path_guitarra = guitar_path
        
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Status: Concluído!")
        self.btn_load.setEnabled(True)

        # Ativa os botões de áudio da guitarra
        self.btn_play_guitar.setEnabled(True)
        self.btn_stop_guitar.setEnabled(True)

        # Atualiza labels de resultados
        gate = params.get("noise_gate_threshold_db", "--")
        eq = params.get("eq", {})
        self.lbl_gate.setText(f"Threshold do Noise Gate: {gate} dB")
        self.lbl_eq.setText(f"Curva de EQ: B({eq.get('bass')}) | M({eq.get('mid')}) | T({eq.get('treble')})")

    def on_analysis_error(self, err_msg):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Status: Erro.")
        self.btn_load.setEnabled(True)
        QMessageBox.critical(self, "Erro", err_msg)

    # --- FUNÇÕES DE REPRODUÇÃO ---
    
    def play_original(self):
        if self.path_original:
            self.stop_audio() # Garante que não toca dois áudios ao mesmo tempo
            self.player.setSource(QUrl.fromLocalFile(self.path_original))
            self.player.play()

    def play_guitarra(self):
        if self.path_guitarra:
            self.stop_audio()
            self.player.setSource(QUrl.fromLocalFile(self.path_guitarra))
            self.player.play()

    def stop_audio(self):
        self.player.stop()

# ==========================================
# 3. EXECUÇÃO
# ==========================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())