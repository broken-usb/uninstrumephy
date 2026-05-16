'''
Código legado para a interface de linha de comando (CLI) do projeto.
Ele utiliza as classes AudioSeparator e AudioAnalyzer para processar um arquivo de áudio,
isolando a faixa da guitarra e analisando-a para extrair os parâmetros necessários para o pedal ESP32(Tone Match).
O resultado é exibido no console em formato JSON.
'''

'''
from core.separator import AudioSeparator
from core.analyzer import AudioAnalyzer
import json

def main():
    separator = AudioSeparator(output_dir="output")
    analyzer = AudioAnalyzer()
    
    musica_teste = "teste.mp3" 
    
    caminho_guitarra = separator.extract_guitar(musica_teste)
    
    if caminho_guitarra:
        print(f"\n[Sucesso] A faixa da guitarra foi isolada em:\n{caminho_guitarra}")
        
        parametros_pedal = analyzer.analyze_guitar(caminho_guitarra)
        
        print("\n==================================================")
        print(" PARÂMETROS CALCULADOS PARA A ESP32 (Tone Match)  ")
        print("==================================================")
        print(json.dumps(parametros_pedal, indent=4))
        print("==================================================")

if __name__ == "__main__":
    main()
'''