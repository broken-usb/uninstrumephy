from __future__ import annotations

import logging
from pathlib import Path

import librosa
import numpy as np
from librosa.util import normalize

logger = logging.getLogger(__name__)

MIN_AMPLITUDE = 1e-6


class AudioAnalyzer:
    """
    Analisa o stem de guitarra isolado e extrai parâmetros acústicos e dinâmicos:
      - Threshold do Noise Gate (dB)
      - Curva de EQ Paramétrico de 4 Bandas (100 Hz, 500 Hz, 1.5 kHz, 4.5 kHz) em dB
      - Sugestão de Overdrive (Tone baseado no Spectral Centroid e Drive baseado no Crest Factor)
      - Sugestão de Compressão (Threshold e Ratio baseados na faixa dinâmica)
      - Curvas e envelopes para visualização gráfica
    """

    SR_TARGET: int = 22_050

    # Faixas de frequência centradas nas frequências dos biquads da Placa A
    BAND_LOW:   tuple[int, int] = (60, 250)      # Pico em ~100 Hz
    BAND_MID1:  tuple[int, int] = (250, 1_000)   # Pico em ~500 Hz
    BAND_MID2:  tuple[int, int] = (1_000, 2_500) # Pico em ~1.500 Hz
    BAND_HIGH:  tuple[int, int] = (2_500, 7_500) # Pico em ~4.500 Hz

    # Bandas legadas para compatibilidade de UI
    BAND_BASS:   tuple[int, int] = (60, 250)
    BAND_MID:    tuple[int, int] = (250, 2_000)
    BAND_TREBLE: tuple[int, int] = (2_000, 6_000)

    GATE_OFFSET_DB: float = 6.0
    GATE_RMS_PERCENTILE: float = 10.0

    def analyze_stem(self, filepath: str) -> dict:
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {filepath}")

        logger.info(f"Iniciando análise avançada de Tone Matching: {filepath}")

        y, sr = librosa.load(
            str(filepath),
            sr=self.SR_TARGET,
            mono=True,
            dtype=np.float32,
        )
        duration_s = len(y) / sr if sr else 0.0

        if y.size == 0 or np.max(np.abs(y)) < MIN_AMPLITUDE:
            logger.warning(f"Stem silencioso ou vazio: {filepath}")
            return {
                "noise_gate_threshold_db": -80.0,
                "eq": {"bass": 0.0, "mid": 0.0, "treble": 0.0},
                "eq_4bands": {"low_db": 0, "mid1_db": 0, "mid2_db": 0, "high_db": 0},
                "overdrive": {"suggested_active": False, "tone_pct": 50, "drive_pct": 20},
                "compressor": {"suggested_active": False, "threshold_pct": 40, "ratio": 3.0},
                "eq_curve": [],
                "waveform": {"min": [], "max": [], "duration_s": duration_s},
                "spectral_centroid_hz": 0.0,
                "spectral_centroid_curve": [],
                "dynamic_range_db": 0.0,
                "crest_factor_db": 0.0,
                "is_silent": True,
            }

        y = normalize(y)

        # 1. Noise Floor & Threshold do Gate
        rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=512)[0]
        rms_active = rms[rms > MIN_AMPLITUDE]

        if rms_active.size == 0:
            reference_rms = MIN_AMPLITUDE
        else:
            reference_rms = float(np.percentile(rms_active, self.GATE_RMS_PERCENTILE))

        noise_floor_db = float(
            librosa.amplitude_to_db(np.array([reference_rms], dtype=np.float32), ref=1.0)[0]
        )
        gate_target = max(-80.0, min(0.0, round(noise_floor_db + self.GATE_OFFSET_DB, 1)))

        # 2. Espectrograma e Análise de Equalização
        stft = np.abs(librosa.stft(y, n_fft=1024, hop_length=512, win_length=1024))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)

        def band_energy(low: int, high: int) -> float:
            # Intervalo semiaberto [low, high) — mesmo critério usado em
            # _compute_eq_curve — para que um bin de frequência exatamente
            # na fronteira entre duas bandas não seja contado em ambas.
            idx = np.where((freqs >= low) & (freqs < high))[0]
            if idx.size == 0:
                return 0.0
            return float(np.sqrt(np.mean(np.square(stft[idx, :]))))

        # 4 Bandas alinhadas com o firmware da ESP32-S3
        e_low = band_energy(*self.BAND_LOW)
        e_mid1 = band_energy(*self.BAND_MID1)
        e_mid2 = band_energy(*self.BAND_MID2)
        e_high = band_energy(*self.BAND_HIGH)

        energies_4b = np.array([e_low, e_mid1, e_mid2, e_high], dtype=np.float32)
        mean_energy_4b = float(np.mean(energies_4b)) + 1e-9

        # Perfil acústico médio de referência de guitarra eletroacústica/elétrica limpa
        baseline_db = np.array([-1.5, 2.0, 0.5, -2.5], dtype=np.float32)
        rel_db = 20.0 * np.log10(np.maximum(energies_4b / mean_energy_4b, 1e-4))
        diff_db = (rel_db - baseline_db) * 1.6

        eq_4bands = {
            "low_db": int(np.clip(round(diff_db[0]), -12, 12)),
            "mid1_db": int(np.clip(round(diff_db[1]), -12, 12)),
            "mid2_db": int(np.clip(round(diff_db[2]), -12, 12)),
            "high_db": int(np.clip(round(diff_db[3]), -12, 12)),
        }

        # 3 Bandas clássicas (mantidas para compatibilidade retroativa)
        bass_e = band_energy(*self.BAND_BASS)
        mid_e = band_energy(*self.BAND_MID)
        treble_e = band_energy(*self.BAND_TREBLE)
        total_3b = bass_e + mid_e + treble_e + 1e-6
        eq_3bands = {
            "bass": round((bass_e / total_3b) * 10, 2),
            "mid": round((mid_e / total_3b) * 10, 2),
            "treble": round((treble_e / total_3b) * 10, 2),
        }

        # 3. Spectral Centroid (Brilho do Som -> Mapeado para Overdrive Tone)
        centroid_mean, centroid_curve = self._compute_spectral_centroid(y, sr)
        # 800 Hz (abafado) a 3500 Hz (muito brilhante) mapeados em 0 a 100%
        tone_pct = int(np.clip(round((centroid_mean - 800.0) / 2700.0 * 100.0), 0, 100))

        # 4. Dinâmica e Fator de Crista (Crest Factor -> Mapeado para Drive e Compressor)
        peak_amp = float(np.max(np.abs(y)))
        overall_rms = float(np.sqrt(np.mean(np.square(y)))) + 1e-9
        crest_factor_db = float(20.0 * np.log10(max(1.0, peak_amp / overall_rms)))

        p90_rms = float(np.percentile(rms_active, 90)) if rms_active.size else 0.1
        p25_rms = float(np.percentile(rms_active, 25)) if rms_active.size else 0.01
        dynamic_range_db = float(20.0 * np.log10(max(1.0, p90_rms / (p25_rms + 1e-6))))

        # Se o fator de crista for baixo (< 11.5 dB), a guitarra já está saturada/comprimida
        suggested_drive = crest_factor_db < 12.0
        drive_pct = int(np.clip(round(25.0 + (12.0 - crest_factor_db) * 6.5), 15, 85))

        # Se houver grande variação dinâmica (> 18 dB), um compressor é indicado
        suggested_comp = dynamic_range_db > 16.0
        comp_thresh = int(np.clip(round(35.0 + (dynamic_range_db - 16.0) * 1.5), 20, 75))
        comp_ratio = round(float(np.clip(2.0 + (dynamic_range_db - 16.0) * 0.12, 1.5, 6.0)), 1)

        eq_curve = self._compute_eq_curve(stft, freqs)
        waveform = self._compute_waveform_envelope(y, sr)

        params: dict = {
            "noise_gate_threshold_db": gate_target,
            "eq": eq_3bands,
            "eq_4bands": eq_4bands,
            "overdrive": {
                "suggested_active": suggested_drive,
                "tone_pct": tone_pct,
                "drive_pct": drive_pct,
            },
            "compressor": {
                "suggested_active": suggested_comp,
                "threshold_pct": comp_thresh,
                "ratio": comp_ratio,
            },
            "eq_curve": eq_curve,
            "waveform": waveform,
            "spectral_centroid_hz": centroid_mean,
            "spectral_centroid_curve": centroid_curve,
            "dynamic_range_db": round(dynamic_range_db, 1),
            "crest_factor_db": round(crest_factor_db, 1),
            "is_silent": False,
        }

        logger.info(
            f"Tone Matching concluído: Gate={gate_target}dB | EQ_4B={eq_4bands} | "
            f"Tone={tone_pct}% | Drive Sugerido={drive_pct}% (Ativo={suggested_drive}) | "
            f"Comp Sugerido={comp_thresh}% @ {comp_ratio}:1 (Ativo={suggested_comp})"
        )
        return params

    N_CURVE_POINTS: int = 40
    CURVE_FREQ_MIN_HZ: float = 40.0
    CURVE_FREQ_MAX_HZ: float = 10_000.0

    def _compute_eq_curve(self, stft: np.ndarray, freqs: np.ndarray) -> list[dict]:
        edges = np.logspace(
            np.log10(self.CURVE_FREQ_MIN_HZ),
            np.log10(self.CURVE_FREQ_MAX_HZ),
            self.N_CURVE_POINTS + 1,
        )
        curve: list[dict] = []
        for low, high in zip(edges[:-1], edges[1:]):
            idx = np.where((freqs >= low) & (freqs < high))[0]
            center_freq = float(np.sqrt(low * high))
            if idx.size == 0:
                curve.append({"freq_hz": round(center_freq, 1), "db": -80.0})
                continue
            band_rms = float(np.sqrt(np.mean(np.square(stft[idx, :]))))
            band_db = float(
                librosa.amplitude_to_db(np.array([band_rms + 1e-9], dtype=np.float32), ref=1.0)[0]
            )
            curve.append({"freq_hz": round(center_freq, 1), "db": round(band_db, 2)})
        return curve

    WAVEFORM_TARGET_POINTS: int = 2000

    def _compute_waveform_envelope(self, y: np.ndarray, sr: int) -> dict:
        n_samples = len(y)
        if n_samples == 0:
            return {"min": [], "max": [], "duration_s": 0.0}
        block_size = max(1, n_samples // self.WAVEFORM_TARGET_POINTS)
        n_blocks = n_samples // block_size
        trimmed = y[: n_blocks * block_size]
        blocks = trimmed.reshape(n_blocks, block_size)
        mins = blocks.min(axis=1)
        maxs = blocks.max(axis=1)
        return {
            "min": [round(float(v), 4) for v in mins],
            "max": [round(float(v), 4) for v in maxs],
            "duration_s": round(n_samples / sr, 3) if sr else 0.0,
        }

    CENTROID_CURVE_TARGET_POINTS: int = 200

    def _compute_spectral_centroid(self, y: np.ndarray, sr: int) -> tuple[float, list[dict]]:
        centroid = librosa.feature.spectral_centroid(y=y, sr=sr, n_fft=1024, hop_length=512)[0]
        if centroid.size == 0:
            return 0.0, []
        centroid_mean = float(np.mean(centroid))
        times = librosa.frames_to_time(np.arange(len(centroid)), sr=sr, hop_length=512)
        n_points = min(self.CENTROID_CURVE_TARGET_POINTS, len(centroid))
        indices = np.linspace(0, len(centroid) - 1, n_points).astype(int)
        curve = [
            {"time_s": round(float(times[i]), 3), "hz": round(float(centroid[i]), 1)}
            for i in indices
        ]
        return round(centroid_mean, 1), curve

    analyze_guitar = analyze_stem