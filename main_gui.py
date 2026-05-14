import sys
import os
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

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
                
                # Vamos extrair o diretório onde todos os stems (.wav) estão salvos
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
        self.path_stems_dir = "" # Guardamos a pasta inteira, não só a guitarra

        # Configuração do Motor de Áudio
        self.audio_output = QAudioOutput()
        # Inicia com o valor do Slider (assumindo 0-100 no Qt Creator)
        self.audio_output.setVolume(self.slider_volume.value() / 100.0) 
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)

        # Conexões: Funcionalidades
        self.btn_load.clicked.connect(self.load_audio_file)
        self.slider_volume.valueChanged.connect(self.change_volume)
        
        # Conexões: Áudio Original
        self.btn_play_orig.clicked.connect(self.play_original)
        self.btn_stop_orig.clicked.connect(self.stop_audio)
        
        # Conexões: Áudio Isolado (Stems)
        self.btn_play_guitar.clicked.connect(self.play_stem)
        self.btn_stop_guitar.clicked.connect(self.stop_audio)

        # Conexão: Atualização de Duração do Áudio
        self.player.durationChanged.connect(self.update_duration)

    def load_audio_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Selecione a Música", "", "Audio Files (*.mp3 *.wav *.flac)"
        )
        
        if file_name:
            self.path_original = file_name
            nome_arquivo = os.path.basename(file_name)
            self.lbl_filepath.setText(f"Arquivo: {nome_arquivo}")
            self.lbl_info.setText(f"Música: {nome_arquivo} | Duração: Aguardando Player...")
            
            # Ativa e desativa botões de acordo com o estado
            self.btn_play_orig.setEnabled(True)
            self.btn_stop_orig.setEnabled(True)
            self.btn_play_guitar.setEnabled(False)
            self.btn_stop_guitar.setEnabled(False)
            self.combo_stems.setEnabled(False)
            
            self.start_analysis(file_name)

    def start_analysis(self, file_path):
        self.btn_load.setEnabled(False) 
        self.progress_bar.setRange(0, 0) # Modo "carregando infinito"

        self.worker = AIMirWorker(file_path)
        self.worker.status.connect(self.update_status)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.start()

    def update_status(self, msg):
        self.lbl_status.setText(f"Status: {msg}")

    def on_analysis_finished(self, params, stems_dir):
        self.path_stems_dir = stems_dir
        
        # Restaura a barra de progresso para o fim
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Status: Concluído com sucesso!")
        self.btn_load.setEnabled(True)

        # Ativa os botões do player das faixas separadas
        self.btn_play_guitar.setEnabled(True)
        self.btn_stop_guitar.setEnabled(True)
        self.combo_stems.setEnabled(True)

        # Extrai os dados calculados e atualiza a interface
        gate = params.get("noise_gate_threshold_db", "--")
        eq = params.get("eq", {})
        self.lbl_gate.setText(f"Threshold do Noise Gate: {gate} dB")
        self.lbl_eq.setText(f"Curva de EQ: B({eq.get('bass')}) | M({eq.get('mid')}) | T({eq.get('treble')})")

    def on_analysis_error(self, err_msg):
        # Em caso de erro, esvazia a barra e avisa o utilizador
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Status: Erro no processamento.")
        self.btn_load.setEnabled(True)
        QMessageBox.critical(self, "Erro de Execução", err_msg)

    # ==========================================
    # --- FUNÇÕES DE REPRODUÇÃO DE ÁUDIO ---
    # ==========================================
    
    def change_volume(self, value):
        # Converte a escala de 0-100 do Slider para 0.0-1.0 exigida pelo QAudioOutput
        self.audio_output.setVolume(value / 100.0)

    def update_duration(self, duration_ms):
        # A API do QtMultimedia retorna a duração em milissegundos
        if duration_ms > 0:
            seconds = int((duration_ms / 1000) % 60)
            minutes = int((duration_ms / (1000 * 60)) % 60)
            
            nome_arquivo = os.path.basename(self.path_original)
            self.lbl_info.setText(f"Música: {nome_arquivo} | Duração: {minutes:02d}:{seconds:02d}")

    def play_original(self):
        if self.path_original:
            self.stop_audio()
            self.player.setSource(QUrl.fromLocalFile(self.path_original))
            self.player.play()

    def play_stem(self):
        if self.path_stems_dir:
            # Pega o nome da faixa escolhida no menu e monta o caminho final
            faixa_escolhida = self.combo_stems.currentText()
            stem_file = os.path.join(self.path_stems_dir, f"{faixa_escolhida}.wav")
            
            if os.path.exists(stem_file):
                self.stop_audio()
                self.player.setSource(QUrl.fromLocalFile(stem_file))
                self.player.play()
            else:
                QMessageBox.warning(self, "Arquivo não encontrado", f"A faixa {faixa_escolhida}.wav não foi encontrada.")

    def stop_audio(self):
        self.player.stop()

# ==========================================
# 3. PONTO DE ENTRADA DO APLICATIVO
# ==========================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())