from pathlib import Path
import logging

import librosa
import numpy as np

logger = logging.getLogger(__name__)

class AudioAnalyzer:

    def __init__(self):

        self.sr_target = 22050

    def analyze_guitar(self, filepath):

        filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {filepath}"
            )

        logger.info(
            f"Analisando guitarra: {filepath}"
        )

        y, sr = librosa.load(
            str(filepath),
            sr=self.sr_target,
            mono=True
        )

        rms = librosa.feature.rms(y=y)[0]

        mean_rms = np.mean(rms)

        threshold_db = librosa.amplitude_to_db(
            np.array([mean_rms]),
            ref=1.0
        )[0]

        gate_target = float(
            round(threshold_db - 12.0, 2)
        )

        stft = np.abs(librosa.stft(y))

        freqs = librosa.fft_frequencies(sr=sr)

        bass_idx = np.where(
            (freqs >= 60) & (freqs <= 250)
        )[0]

        mid_idx = np.where(
            (freqs > 250) & (freqs <= 2000)
        )[0]

        treb_idx = np.where(
            (freqs > 2000) & (freqs <= 6000)
        )[0]

        bass_energy = (
            np.mean(stft[bass_idx, :])
            if len(bass_idx)
            else 0
        )

        mid_energy = (
            np.mean(stft[mid_idx, :])
            if len(mid_idx)
            else 0
        )

        treb_energy = (
            np.mean(stft[treb_idx, :])
            if len(treb_idx)
            else 0
        )

        total = (
            bass_energy
            + mid_energy
            + treb_energy
            + 1e-6
        )

        eq = {
            "bass": float(
                round((bass_energy / total) * 10, 2)
            ),
            "mid": float(
                round((mid_energy / total) * 10, 2)
            ),
            "treble": float(
                round((treb_energy / total) * 10, 2)
            )
        }

        params = {
            "noise_gate_threshold_db": gate_target,
            "eq": eq
        }

        logger.info("Análise concluída.")

        return params