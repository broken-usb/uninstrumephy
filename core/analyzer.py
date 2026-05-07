import librosa
import numpy as np

class AudioAnalyzer:
    def __init__(self):
        # Frequência de amostragem padrão para análise
        self.sr_target = 22050 

    def analyze_guitar(self, filepath):
        """
        Extrai as características do áudio da guitarra (MIR) e calcula os
        parâmetros físicos que serão enviados para a ESP32.
        """
        print(f"\n[Análise] Carregando áudio para extração de MIR: {filepath}")
        
        # Carrega o áudio. O Librosa converte para mono automaticamente, o que é ideal.
        y, sr = librosa.load(filepath, sr=self.sr_target)

        print("[Análise] Calculando RMS e Threshold do Noise Gate...")
        # Calcula a energia Root Mean Square (RMS)
        rms = librosa.feature.rms(y=y)[0]
        mean_rms = np.mean(rms)
        
        # Converte a amplitude RMS para Decibéis (dB), que é a unidade padrão de um Noise Gate
        threshold_db = librosa.amplitude_to_db(np.array([mean_rms]), ref=1.0)[0]
        # Ajuste de compensação: O gate deve atuar abaixo da média, então subtraímos um fator de segurança
        gate_target = threshold_db - 12.0 
        
        print("[Análise] Calculando resposta de frequência (EQ) via STFT...")
        # Aplica a Transformada Rápida de Fourier de Curto Termo
        S = np.abs(librosa.stft(y))
        freqs = librosa.fft_frequencies(sr=sr)
        
        # Define as bandas de frequência da Guitarra
        bass_idx = np.where((freqs >= 60) & (freqs <= 250))[0]
        mid_idx = np.where((freqs > 250) & (freqs <= 2000))[0]
        treb_idx = np.where((freqs > 2000) & (freqs <= 6000))[0]

        # Calcula a energia média em cada banda
        bass_energy = np.mean(S[bass_idx, :]) if len(bass_idx) > 0 else 0
        mid_energy = np.mean(S[mid_idx, :]) if len(mid_idx) > 0 else 0
        treb_energy = np.mean(S[treb_idx, :]) if len(treb_idx) > 0 else 0

        # Normaliza as energias e GARANTE que sejam floats nativos do Python (Evita erro no JSON)
        total_energy = bass_energy + mid_energy + treb_energy + 1e-6
        eq_bass = float(round((bass_energy / total_energy) * 10, 2))
        eq_mid = float(round((mid_energy / total_energy) * 10, 2))
        eq_treb = float(round((treb_energy / total_energy) * 10, 2))
        
        gate_target_float = float(round(gate_target, 2))

        # Monta o "Payload" JSON-Safe que será enviado à ESP32 no futuro
        params = {
            "noise_gate_threshold_db": gate_target_float,
            "eq": {
                "bass": eq_bass,
                "mid": eq_mid,
                "treble": eq_treb
            }
        }
        
        print("[Análise] Extração de características concluída com sucesso!")
        return params