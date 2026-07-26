from __future__ import annotations

import logging
from pathlib import Path

import librosa
import numpy as np

from librosa.util import normalize

logger = logging.getLogger(__name__)

# Amplitude mínima considerada "silêncio" (evita log(0) = -inf)
MIN_AMPLITUDE = 1e-6


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

    # Offset ACIMA do noise floor para dar margem de segurança ao gate
    # (o gate deve abrir um pouco acima do ruído de fundo, não no meio do
    # sinal útil — por isso o offset agora é positivo).
    GATE_OFFSET_DB: float = 6.0

    # Percentil usado como referência de RMS para estimar o "noise floor"
    # (piso de ruído) da faixa. Um percentil baixo (ex.: 10) captura os
    # trechos mais silenciosos — que representam o ruído de fundo — em vez
    # dos trechos mais altos, que representariam o próprio sinal musical.
    GATE_RMS_PERCENTILE: float = 10.0

    def analyze_stem(self, filepath: str) -> dict:
        """
        Carrega o arquivo de áudio e extrai:
          - noise_gate_threshold_db: threshold sugerido para o noise gate
          - eq: dicionário com energias relativas de bass, mid e treble (0–10)
          - is_silent: True se o stem não contém sinal audível relevante

        Args:
            filepath: Caminho para o arquivo de áudio (qualquer stem mono).

        Returns:
            {
                "noise_gate_threshold_db": float,
                "eq": {"bass": float, "mid": float, "treble": float},
                "is_silent": bool
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

        # Carregamento com taxa reduzida para menor custo
        y, sr = librosa.load(
            str(filepath),
            sr=self.SR_TARGET,
            mono=True,
            dtype=np.float32,
        )
        duration_s = len(y) / sr if sr else 0.0
        logger.debug(
            f"Áudio carregado: {len(y)} amostras, sr={sr} Hz, "
            f"duração≈{duration_s:.2f}s"
        )

        if y.size == 0 or np.max(np.abs(y)) < MIN_AMPLITUDE:
            logger.warning(f"Stem silencioso ou vazio: {filepath}")
            return {
                "noise_gate_threshold_db": -80.0,
                "eq": {"bass": 0.0, "mid": 0.0, "treble": 0.0},
                "is_silent": True,
            }

        # Normaliza a onda para reduzir variações extremas de amplitude
        y = normalize(y)

        # Noise floor / gate — usa percentil baixo do RMS para estimar o
        # ruído de fundo da faixa, em vez de média (mais robusto contra
        # trechos de silêncio digital absoluto, que já foram filtrados).
        rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=512)[0]
        rms = rms[rms > MIN_AMPLITUDE]

        if rms.size == 0:
            reference_rms = MIN_AMPLITUDE
            logger.debug("Nenhum frame de RMS acima do limiar mínimo; usando fallback.")
        else:
            reference_rms = float(np.percentile(rms, self.GATE_RMS_PERCENTILE))

        logger.debug(
            f"Noise floor estimado (percentil {self.GATE_RMS_PERCENTILE} do RMS): "
            f"{reference_rms:.6f}"
        )

        noise_floor_db = float(
            librosa.amplitude_to_db(
                np.array([reference_rms], dtype=np.float32),
                ref=1.0,
            )[0]
        )
        gate_target = max(-80.0, round(noise_floor_db + self.GATE_OFFSET_DB, 2))
        logger.debug(
            f"Noise floor: {noise_floor_db:.2f} dB | "
            f"Gate final (noise floor + {self.GATE_OFFSET_DB} dB de margem): "
            f"{gate_target} dB"
        )

        # FFT / bandas com resolução menor para reduzir custo
        stft = np.abs(
            librosa.stft(
                y,
                n_fft=1024,
                hop_length=512,
                win_length=1024,
            )
        )
        freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)

        def band_energy(low: int, high: int) -> float:
            idx = np.where((freqs >= low) & (freqs <= high))[0]
            if idx.size == 0:
                return 0.0
            return float(np.mean(stft[idx, :]))

        bass_e   = band_energy(*self.BAND_BASS)
        mid_e    = band_energy(*self.BAND_MID)
        treble_e = band_energy(*self.BAND_TREBLE)

        logger.debug(
            f"Energias brutas por banda — bass: {bass_e:.6f} | "
            f"mid: {mid_e:.6f} | treble: {treble_e:.6f}"
        )

        total = bass_e + mid_e + treble_e + 1e-6

        eq = {
            "bass":   round((bass_e   / total) * 10, 2),
            "mid":    round((mid_e    / total) * 10, 2),
            "treble": round((treble_e / total) * 10, 2),
        }

        params: dict = {
            "noise_gate_threshold_db": gate_target,
            "eq": eq,
            "is_silent": False,
        }

        logger.info(f"Análise concluída: {params}")

        return params

    # Mantém o nome antigo como alias para não quebrar chamadas existentes
    analyze_guitar = analyze_stem