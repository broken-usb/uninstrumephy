from __future__ import annotations

import logging
from pathlib import Path

import librosa
import numpy as np

logger = logging.getLogger(__name__)


class AudioAnalyzer:
    """
    Analisa um stem de áudio mono e extrai parâmetros de tone-matching:
    threshold do noise gate (dB) e curva de EQ simplificada (bass/mid/treble).
    """

    # Taxa de amostragem alvo para análise (22050 Hz é suficiente para EQ)
    SR_TARGET: int = 22_050

    # Bandas de frequência em Hz
    BAND_BASS:   tuple[int, int] = (60,   250)
    BAND_MID:    tuple[int, int] = (250, 2_000)
    BAND_TREBLE: tuple[int, int] = (2_000, 6_000)

    # Offset abaixo do RMS médio para calcular o threshold do gate
    GATE_OFFSET_DB: float = -12.0

    def analyze_stem(self, filepath: str) -> dict:
        """
        Carrega o arquivo de áudio e extrai:
          - noise_gate_threshold_db: threshold sugerido para o noise gate
          - eq: dicionário com energias relativas de bass, mid e treble (0–10)

        Args:
            filepath: Caminho para o arquivo de áudio (qualquer stem mono).

        Returns:
            {
                "noise_gate_threshold_db": float,
                "eq": {"bass": float, "mid": float, "treble": float}
            }

        Raises:
            FileNotFoundError: Se o arquivo não existir.
        """
        filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {filepath}"
            )

        logger.info(f"Analisando stem: {filepath}")

        # Carregamento
        y, sr = librosa.load(
            str(filepath),
            sr=self.SR_TARGET,
            mono=True,
        )

        # RMS / gate
        rms      = librosa.feature.rms(y=y)[0]
        mean_rms = float(np.mean(rms))

        threshold_db = float(
            librosa.amplitude_to_db(
                np.array([mean_rms]), ref=1.0
            )[0]
        )
        gate_target = round(threshold_db + self.GATE_OFFSET_DB, 2)

        # FFT / bandas
        stft  = np.abs(librosa.stft(y))
        freqs = librosa.fft_frequencies(sr=sr)

        def band_energy(low: int, high: int) -> float:
            idx = np.where((freqs >= low) & (freqs <= high))[0]
            return float(np.mean(stft[idx, :])) if len(idx) else 0.0

        bass_e   = band_energy(*self.BAND_BASS)
        mid_e    = band_energy(*self.BAND_MID)
        treble_e = band_energy(*self.BAND_TREBLE)

        total = bass_e + mid_e + treble_e + 1e-6   # evita divisão por zero

        eq = {
            "bass":   round((bass_e   / total) * 10, 2),
            "mid":    round((mid_e    / total) * 10, 2),
            "treble": round((treble_e / total) * 10, 2),
        }

        params: dict = {
            "noise_gate_threshold_db": gate_target,
            "eq": eq,
        }

        logger.info(f"Análise concluída: {params}")

        return params

    # Mantém o nome antigo como alias para não quebrar chamadas existentes
    analyze_guitar = analyze_stem