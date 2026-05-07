from core.separator import AudioSeparator
from core.analyzer import AudioAnalyzer
import json

def main():
    separator = AudioSeparator(output_dir="output")
    analyzer = AudioAnalyzer()
    
    musica_teste = "teste.mp3" 
    
    # Etapa 1: Separação de Fontes (Machine Learning)
    caminho_guitarra = separator.extract_guitar(musica_teste)
    
    if caminho_guitarra:
        print(f"\n[Sucesso] A faixa da guitarra foi isolada em:\n{caminho_guitarra}")
        
        # Etapa 2: Recuperação de Informação Musical (Processamento Digital de Sinais)
        parametros_pedal = analyzer.analyze_guitar(caminho_guitarra)
        
        print("\n==================================================")
        print(" PARÂMETROS CALCULADOS PARA A ESP32 (Tone Match)  ")
        print("==================================================")
        print(json.dumps(parametros_pedal, indent=4))
        print("==================================================")

if __name__ == "__main__":
    main()