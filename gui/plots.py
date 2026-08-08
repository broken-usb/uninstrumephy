from __future__ import annotations

import logging

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

logger = logging.getLogger(__name__)


class WaveformPlot(FigureCanvasQTAgg):
    """
    Widget Qt que desenha o envelope (min/max) de uma forma de onda.

    Espera o formato retornado por AudioAnalyzer._compute_waveform_envelope:
        {"min": [...], "max": [...], "duration_s": float}
    """

    def __init__(self, parent=None) -> None:
        self.figure = Figure(figsize=(5, 1.6), tight_layout=True)
        super().__init__(self.figure)
        self.setParent(parent)
        self._ax = self.figure.add_subplot(111)
        self.clear_plot()

    def clear_plot(self) -> None:
        self._ax.clear()
        self._ax.set_ylim(-1.05, 1.05)
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._ax.text(
            0.5, 0.5, "Sem dados",
            ha="center", va="center",
            transform=self._ax.transAxes,
            fontsize=9, color="gray",
        )
        self.draw_idle()

    def plot_waveform(self, waveform: dict, label: str = "") -> None:
        mins = waveform.get("min", [])
        maxs = waveform.get("max", [])
        duration_s = waveform.get("duration_s", 0.0)

        if not mins or not maxs:
            self.clear_plot()
            return

        n = len(mins)
        x = np.linspace(0, duration_s, n)

        self._ax.clear()
        self._ax.fill_between(x, mins, maxs, color="#3a7bd5", linewidth=0)
        self._ax.set_xlim(0, duration_s if duration_s > 0 else 1)
        self._ax.set_ylim(-1.05, 1.05)
        self._ax.set_yticks([])
        self._ax.set_xlabel("Tempo (s)", fontsize=8)
        self._ax.tick_params(axis="x", labelsize=7)

        if label:
            self._ax.set_title(label, fontsize=9)

        self.draw_idle()


class EQCurvePlot(FigureCanvasQTAgg):
    """
    Widget Qt que desenha a curva espectral (RMS por banda em dB) de um
    stem analisado, em escala de frequência logarítmica.

    Espera o formato retornado por AudioAnalyzer._compute_eq_curve:
        [{"freq_hz": float, "db": float}, ...]
    """

    def __init__(self, parent=None) -> None:
        self.figure = Figure(figsize=(5, 1.8), tight_layout=True)
        super().__init__(self.figure)
        self.setParent(parent)
        self._ax = self.figure.add_subplot(111)
        self.clear_plot()

    def clear_plot(self) -> None:
        self._ax.clear()
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._ax.text(
            0.5, 0.5, "Sem dados",
            ha="center", va="center",
            transform=self._ax.transAxes,
            fontsize=9, color="gray",
        )
        self.draw_idle()

    def plot_eq_curve(self, eq_curve: list[dict], label: str = "") -> None:
        if not eq_curve:
            self.clear_plot()
            return

        freqs = [p["freq_hz"] for p in eq_curve]
        dbs   = [p["db"] for p in eq_curve]

        self._ax.clear()
        self._ax.plot(freqs, dbs, color="#e08a2c", linewidth=1.6)
        self._ax.fill_between(freqs, dbs, min(dbs) - 5, color="#e08a2c", alpha=0.15)

        self._ax.set_xscale("log")
        self._ax.set_xlabel("Frequência (Hz)", fontsize=8)
        self._ax.set_ylabel("dB", fontsize=8)
        self._ax.tick_params(axis="both", labelsize=7)
        self._ax.grid(True, which="both", linestyle=":", linewidth=0.5, alpha=0.5)

        # Linhas de referência nas fronteiras bass/mid/treble usadas no
        # cálculo enviado ao hardware, para o usuário relacionar a curva
        # visual com os 3 valores numéricos (bass/mid/treble) exibidos ao lado.
        for boundary in (250, 2_000):
            self._ax.axvline(boundary, color="gray", linestyle="--", linewidth=0.7, alpha=0.6)

        if label:
            self._ax.set_title(label, fontsize=9)

        self.draw_idle()