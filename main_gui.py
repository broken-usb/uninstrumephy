import sys
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal

# Importa o visual que você gerou no Qt Creator
from gui.ui_mainwindow import Ui_Dialog

# Importa os motores de IA que construímos
from core.separator import AudioSeparator
from core.analyzer import AudioAnalyzer


# ==========================================
# 1. O MOTOR ASSÍNCRONO (WORKER THREAD)
# ==========================================
class AIMirWorker(QThread):
    # Sinais para comunicar com a interface gráfica de forma segura
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, audio_path):
        super().__init__()
        self.audio_path = audio_path

    def run(self):
        try:
            self.status.emit("Iniciando IA (Demucs)... Isolando guitarra (pode demorar)...")
            
            # Instancia o Separador
            sep = AudioSeparator(output_dir="output")
            guitar_path = sep.extract_guitar(self.audio_path)

            if guitar_path:
                self.status.emit("Guitarra isolada! Extraindo parâmetros matemáticos (Librosa)...")
                # Instancia o Analisador
                ana = AudioAnalyzer()
                params = ana.analyze_guitar(guitar_path)
                
                # Avisa a interface que acabou e manda o JSON
                self.finished.emit(params)
            else:
                self.error.emit("Falha ao isolar a guitarra no Demucs.")
                
        except Exception as e:
            self.error.emit(f"Erro catastrófico: {str(e)}")


# ==========================================
# 2. A JANELA PRINCIPAL (CONTROLADOR)
# ==========================================
class MainWindow(QDialog, Ui_Dialog):
    def __init__(self):
        super().__init__()
        self.setupUi(self)  # Carrega o layout desenhado no Qt Creator

        # Liga o clique do botão à função de abrir arquivo
        self.btn_load.clicked.connect(self.load_audio_file)

    def load_audio_file(self):
        # Abre a caixa de diálogo nativa do sistema operacional
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Selecione a Música de Referência", "", "Audio Files (*.mp3 *.wav *.flac)"
        )
        
        if file_name:
            self.lbl_filepath.setText(f"Arquivo: {file_name}")
            self.start_analysis(file_name)

    def start_analysis(self, file_path):
        # Trava o botão para o usuário não clicar duas vezes e bugar a IA
        self.btn_load.setEnabled(False) 
        
        # Coloca a barra de progresso no modo "Carregando Infinito"
        self.progress_bar.setRange(0, 0) 

        # Cria a Thread de IA e liga os cabos de comunicação (Sinais -> Slots)
        self.worker = AIMirWorker(file_path)
        self.worker.status.connect(self.update_status)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.error.connect(self.on_analysis_error)
        
        # Dá a partida na Thread em segundo plano
        self.worker.start()

    def update_status(self, msg):
        self.lbl_status.setText(f"Status: {msg}")

    def on_analysis_finished(self, params):
        # Destrava a tela e preenche 100% da barra
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Status: Concluído com sucesso!")
        self.btn_load.setEnabled(True)

        # Atualiza os painéis com os dados calculados do seu JSON
        gate = params.get("noise_gate_threshold_db", "--")
        eq = params.get("eq", {})
        bass = eq.get("bass", "--")
        mid = eq.get("mid", "--")
        treble = eq.get("treble", "--")

        self.lbl_gate.setText(f"Threshold do Noise Gate: {gate} dB")
        self.lbl_eq.setText(f"Curva de EQ Calculada: Bass ({bass}) | Mid ({mid}) | Treble ({treble})")

    def on_analysis_error(self, err_msg):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Status: Erro no processamento.")
        self.btn_load.setEnabled(True)
        QMessageBox.critical(self, "Erro de Execução", err_msg)


# ==========================================
# 3. PONTO DE ENTRADA DO APLICATIVO
# ==========================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())