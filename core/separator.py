import subprocess
import os

class AudioSeparator:
    def __init__(self, output_dir="output"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        # Forçamos o uso do modelo de 6 faixas que isola a guitarra perfeitamente
        self.model = "htdemucs_6s"

    def extract_guitar(self, audio_path):
        """
        Executa o Demucs via CLI para isolar as faixas do arquivo de áudio fornecido.
        Retorna o caminho absoluto do arquivo da guitarra isolada.
        """
        # VALIDAÇÃO DE ENTRADA: Verifica se o arquivo realmente existe
        if not os.path.exists(audio_path):
            print(f"[Erro] Arquivo não encontrado: '{audio_path}'. Verifique o caminho.")
            return None

        print(f"[Sistema] Iniciando separação de fontes para: {audio_path}")
        print(f"[Sistema] Utilizando o modelo Demucs: {self.model}")
        
        command = [
            "demucs", 
            "-n", self.model, 
            "-o", self.output_dir, 
            audio_path
        ]

        try:
            # Roda o comando e trava a execução até terminar
            subprocess.run(command, check=True)
            
            # Formata o caminho de saída esperado pelo Demucs
            base_name = os.path.splitext(os.path.basename(audio_path))[0]
            guitar_path = os.path.join(self.output_dir, self.model, base_name, "guitar.wav")
            
            # Transforma em caminho absoluto para facilitar o uso no Librosa depois
            guitar_path_absoluto = os.path.abspath(guitar_path)
            
            if os.path.exists(guitar_path_absoluto):
                print("[Sistema] Separação concluída com sucesso!")
                return guitar_path_absoluto
            else:
                print("[Erro] O Demucs rodou, mas não gerou o arquivo 'guitar.wav'.")
                return None

        except subprocess.CalledProcessError as e:
            print(f"[Erro] Falha catastrófica ao executar o Demucs: {e}")
            return None