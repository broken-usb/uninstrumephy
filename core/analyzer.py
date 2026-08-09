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
          - eq_curve: curva espectral detalhada para visualização gráfica
            (lista de pontos {freq_hz, db}), não enviada ao hardware —
            apenas para plotagem na UI
          - waveform: envelope simplificado da forma de onda (amplitude
            min/max por bloco), para visualização gráfica sem precisar
            recarregar o áudio inteiro na UI
          - spectral_centroid_hz: "centro de massa" médio do espectro em
            Hz — indica o quão "brilhante" (agudo) ou "escuro" (grave) o
            timbre da faixa soa de forma geral. Não é enviado ao hardware,
            é um dado auxiliar de diagnóstico/visualização.
          - spectral_centroid_curve: evolução do centroide espectral ao
            longo do tempo (lista de pontos {time_s, hz}), útil para
            visualizar como o brilho do som varia durante a faixa.
          - is_silent: True se o stem não contém sinal audível relevante

        Args:
            filepath: Caminho para o arquivo de áudio (qualquer stem mono).

        Returns:
            {
                "noise_gate_threshold_db": float,
                "eq": {"bass": float, "mid": float, "treble": float},
                "eq_curve": [{"freq_hz": float, "db": float}, ...],
                "waveform": {"min": [...], "max": [...], "duration_s": float},
                "spectral_centroid_hz": float,
                "spectral_centroid_curve": [{"time_s": float, "hz": float}, ...],
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
                "eq_curve": [],
                "waveform": {"min": [], "max": [], "duration_s": duration_s},
                "spectral_centroid_hz": 0.0,
                "spectral_centroid_curve": [],
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
            """
            Calcula o RMS (raiz quadrada da média dos quadrados) da
            magnitude espectral dentro da faixa de frequência informada.

            Usar RMS aqui — em vez de uma média simples da magnitude —
            mantém a métrica consistente com o cálculo do noise gate
            (que também usa RMS) e reflete melhor a energia percebida
            do sinal em cada banda, já que o RMS pondera picos de forma
            diferente da média aritmética simples.
            """
            idx = np.where((freqs >= low) & (freqs <= high))[0]
            if idx.size == 0:
                return 0.0
            return float(np.sqrt(np.mean(np.square(stft[idx, :]))))

        bass_e   = band_energy(*self.BAND_BASS)
        mid_e    = band_energy(*self.BAND_MID)
        treble_e = band_energy(*self.BAND_TREBLE)

        logger.debug(
            f"RMS por banda — bass: {bass_e:.6f} | "
            f"mid: {mid_e:.6f} | treble: {treble_e:.6f}"
        )

        total = bass_e + mid_e + treble_e + 1e-6

        eq = {
            "bass":   round((bass_e   / total) * 10, 2),
            "mid":    round((mid_e    / total) * 10, 2),
            "treble": round((treble_e / total) * 10, 2),
        }

        eq_curve = self._compute_eq_curve(stft, freqs)
        waveform = self._compute_waveform_envelope(y, sr)
        centroid_mean, centroid_curve = self._compute_spectral_centroid(y, sr)

        params: dict = {
            "noise_gate_threshold_db": gate_target,
            "eq": eq,
            "eq_curve": eq_curve,
            "waveform": waveform,
            "spectral_centroid_hz": centroid_mean,
            "spectral_centroid_curve": centroid_curve,
            "is_silent": False,
        }

        logger.info(
            f"Análise concluída: gate={gate_target}dB, eq={eq}, "
            f"eq_curve com {len(eq_curve)} pontos, "
            f"waveform com {len(waveform['min'])} blocos, "
            f"spectral_centroid médio={centroid_mean}Hz"
        )

        return params

    # Curva de EQ para visualização

    N_CURVE_POINTS: int = 40
    CURVE_FREQ_MIN_HZ: float = 40.0
    CURVE_FREQ_MAX_HZ: float = 10_000.0

    def _compute_eq_curve(
        self, stft: np.ndarray, freqs: np.ndarray
    ) -> list[dict]:
        """
        Calcula uma curva espectral suavizada (RMS por banda log-espaçada)
        para fins de visualização gráfica na UI. Diferente do `eq` de
        3 bandas usado no envio ao hardware, esta curva tem resolução
        maior (N_CURVE_POINTS pontos) e não é enviada à ESP32-S3 — serve
        apenas para o usuário visualizar o formato espectral do stem.
        """
        # Bordas log-espaçadas entre CURVE_FREQ_MIN_HZ e CURVE_FREQ_MAX_HZ
        edges = np.logspace(
            np.log10(self.CURVE_FREQ_MIN_HZ),
            np.log10(self.CURVE_FREQ_MAX_HZ),
            self.N_CURVE_POINTS + 1,
        )

        curve: list[dict] = []
        for low, high in zip(edges[:-1], edges[1:]):
            idx = np.where((freqs >= low) & (freqs < high))[0]
            center_freq = float(np.sqrt(low * high))  # centro geométrico

            if idx.size == 0:
                curve.append({"freq_hz": round(center_freq, 1), "db": -80.0})
                continue

            band_rms = float(np.sqrt(np.mean(np.square(stft[idx, :]))))
            band_db = float(
                librosa.amplitude_to_db(
                    np.array([band_rms + 1e-9], dtype=np.float32), ref=1.0
                )[0]
            )
            curve.append({"freq_hz": round(center_freq, 1), "db": round(band_db, 2)})

        return curve

    # Envelope de forma de onda para visualização

    WAVEFORM_TARGET_POINTS: int = 2000

    def _compute_waveform_envelope(
        self, y: np.ndarray, sr: int
    ) -> dict:
        """
        Reduz o sinal de áudio a um envelope compacto (mínimo e máximo por
        bloco), adequado para desenhar a forma de onda na UI sem precisar
        transferir/recarregar o sinal completo (que pode ter milhões de
        amostras) para a camada de interface.
        """
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

    # Spectral centroid (brilho do timbre)

    CENTROID_CURVE_TARGET_POINTS: int = 200

    def _compute_spectral_centroid(
        self, y: np.ndarray, sr: int
    ) -> tuple[float, list[dict]]:
        """
        Calcula o centroide espectral (spectral centroid) do sinal: o
        "centro de massa" do espectro de frequências, ponderado pela
        energia em cada frequência. Um valor mais alto indica um timbre
        mais "brilhante" (rico em agudos); um valor mais baixo indica um
        timbre mais "escuro" (concentrado em graves).

        Diferente do EQ de 3 bandas (que já captura a distribuição de
        energia por faixa), o centroide resume o timbre da faixa inteira
        em um único número interpretável, e sua evolução ao longo do
        tempo ajuda a identificar se o brilho do som varia muito durante
        a gravação (ex.: dedilhado mais brilhante no início, mais
        abafado no final).

        Returns:
            (centroid_mean_hz, centroid_curve) onde centroid_curve é uma
            lista de pontos {"time_s": float, "hz": float} — reduzida a
            CENTROID_CURVE_TARGET_POINTS pontos para não sobrecarregar a
            UI com dados desnecessariamente granulares.
        """
        centroid = librosa.feature.spectral_centroid(
            y=y, sr=sr, n_fft=1024, hop_length=512
        )[0]

        if centroid.size == 0:
            return 0.0, []

        centroid_mean = float(np.mean(centroid))

        times = librosa.frames_to_time(
            np.arange(len(centroid)), sr=sr, hop_length=512
        )

        # Reduz a curva a um número razoável de pontos para visualização,
        # sem perder a forma geral da evolução do brilho ao longo do tempo
        n_points = min(self.CENTROID_CURVE_TARGET_POINTS, len(centroid))
        indices = np.linspace(0, len(centroid) - 1, n_points).astype(int)

        curve = [
            {"time_s": round(float(times[i]), 3), "hz": round(float(centroid[i]), 1)}
            for i in indices
        ]

        return round(centroid_mean, 1), curve

    # Mantém o nome antigo como alias para não quebrar chamadas existentes
    analyze_guitar = analyze_stem