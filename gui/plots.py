from __future__ import annotations

import logging

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from gui import theme

logger = logging.getLogger(__name__)


def _style_axes(figure: Figure, ax) -> None:
    """Aplica as cores do tema atual à figura e aos eixos."""
    t = theme.tokens()
    figure.set_facecolor(t.window)
    ax.set_facecolor(t.surface)
    for spine in ax.spines.values():
        spine.set_color(t.border)
    ax.tick_params(colors=t.text_dim)
    ax.xaxis.label.set_color(t.text_dim)
    ax.yaxis.label.set_color(t.text_dim)
    ax.title.set_color(t.text)


class _ThemedCanvas(FigureCanvasQTAgg):
    """Base: refaz o desenho quando o esquema claro/escuro muda."""

    def _init_theme(self) -> None:
        theme.on_change(self._on_theme_changed)

    def _on_theme_changed(self) -> None:
        self._redraw()

    def _redraw(self) -> None:  # sobrescrito nas subclasses
        self.clear_plot()


class WaveformPlot(_ThemedCanvas):
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
        self._last = None
        self._init_theme()
        self.clear_plot()

    def _redraw(self) -> None:
        if self._last is None:
            self.clear_plot()
        else:
            self.plot_waveform(self._last[0], label=self._last[1])

    def clear_plot(self) -> None:
        self._last = None
        self._ax.clear()
        _style_axes(self.figure, self._ax)
        self._ax.set_ylim(-1.05, 1.05)
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._ax.text(
            0.5, 0.5, "Sem dados",
            ha="center", va="center",
            transform=self._ax.transAxes,
            fontsize=9, color=theme.tokens().text_dim,
        )
        self.draw_idle()

    def plot_waveform(self, waveform: dict, label: str = "") -> None:
        mins = waveform.get("min", [])
        maxs = waveform.get("max", [])
        duration_s = waveform.get("duration_s", 0.0)

        if not mins or not maxs:
            self.clear_plot()
            return

        self._last = (waveform, label)
        n = len(mins)
        x = np.linspace(0, duration_s, n)

        self._ax.clear()
        _style_axes(self.figure, self._ax)
        self._ax.fill_between(x, mins, maxs, color=theme.tokens().series_a, linewidth=0)
        self._ax.set_xlim(0, duration_s if duration_s > 0 else 1)
        self._ax.set_ylim(-1.05, 1.05)
        self._ax.set_yticks([])
        self._ax.set_xlabel("Tempo (s)", fontsize=8)
        self._ax.tick_params(axis="x", labelsize=7)

        if label:
            self._ax.set_title(label, fontsize=9)

        self.draw_idle()


class EQCurvePlot(_ThemedCanvas):
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
        self._last = None
        self._init_theme()
        self.clear_plot()

    def _redraw(self) -> None:
        if self._last is None:
            self.clear_plot()
        else:
            self.plot_eq_curve(self._last[0], label=self._last[1])

    def clear_plot(self) -> None:
        self._last = None
        self._ax.clear()
        _style_axes(self.figure, self._ax)
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._ax.text(
            0.5, 0.5, "Sem dados",
            ha="center", va="center",
            transform=self._ax.transAxes,
            fontsize=9, color=theme.tokens().text_dim,
        )
        self.draw_idle()

    def plot_eq_curve(self, eq_curve: list[dict], label: str = "") -> None:
        if not eq_curve:
            self.clear_plot()
            return

        self._last = (eq_curve, label)
        freqs = [p["freq_hz"] for p in eq_curve]
        dbs   = [p["db"] for p in eq_curve]

        self._ax.clear()
        _style_axes(self.figure, self._ax)
        self._ax.plot(freqs, dbs, color=theme.tokens().series_b, linewidth=1.6)
        self._ax.fill_between(freqs, dbs, min(dbs) - 5, color=theme.tokens().series_b, alpha=0.15)

        self._ax.set_xscale("log")
        self._ax.set_xlabel("Frequência (Hz)", fontsize=8)
        self._ax.set_ylabel("dB", fontsize=8)
        self._ax.tick_params(axis="both", labelsize=7)
        self._ax.grid(True, which="both", linestyle=":", linewidth=0.5, alpha=0.5)

        # Linhas de referência nas fronteiras bass/mid/treble usadas no
        # cálculo enviado ao hardware, para o usuário relacionar a curva
        # visual com os 3 valores numéricos (bass/mid/treble) exibidos ao lado.
        for boundary in (250, 2_000):
            self._ax.axvline(boundary, color=theme.tokens().text_dim, linestyle="--", linewidth=0.7, alpha=0.6)

        if label:
            self._ax.set_title(label, fontsize=9)

        self.draw_idle()


class SpectralCentroidPlot(_ThemedCanvas):
    """
    Widget Qt que desenha a evolução do centroide espectral (spectral
    centroid) de um stem ao longo do tempo — uma medida de "brilho" do
    timbre: valores mais altos indicam um som mais agudo/brilhante,
    valores mais baixos indicam um som mais grave/escuro.

    Espera o formato retornado por AudioAnalyzer._compute_spectral_centroid:
        curve: [{"time_s": float, "hz": float}, ...]
        mean_hz: float (centroide médio da faixa inteira)
    """

    def __init__(self, parent=None) -> None:
        self.figure = Figure(figsize=(5, 1.8), tight_layout=True)
        super().__init__(self.figure)
        self.setParent(parent)
        self._ax = self.figure.add_subplot(111)
        self._last = None
        self._init_theme()
        self.clear_plot()

    def _redraw(self) -> None:
        if self._last is None:
            self.clear_plot()
        else:
            self.plot_spectral_centroid(self._last[0], self._last[1], self._last[2])

    def clear_plot(self) -> None:
        self._last = None
        self._ax.clear()
        _style_axes(self.figure, self._ax)
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._ax.text(
            0.5, 0.5, "Sem dados",
            ha="center", va="center",
            transform=self._ax.transAxes,
            fontsize=9, color=theme.tokens().text_dim,
        )
        self.draw_idle()

    def plot_spectral_centroid(
        self,
        curve: list[dict],
        mean_hz: float = 0.0,
        label: str = "",
    ) -> None:
        if not curve:
            self.clear_plot()
            return

        self._last = (curve, mean_hz, label)
        times = [p["time_s"] for p in curve]
        hzs   = [p["hz"] for p in curve]

        self._ax.clear()
        _style_axes(self.figure, self._ax)
        self._ax.plot(times, hzs, color=theme.tokens().series_c, linewidth=1.4)
        self._ax.fill_between(times, hzs, 0, color=theme.tokens().series_c, alpha=0.12)

        if mean_hz > 0:
            self._ax.axhline(
                mean_hz, color=theme.tokens().text_dim, linestyle="--", linewidth=0.8, alpha=0.7
            )
            self._ax.text(
                times[-1], mean_hz, f" média: {mean_hz:.0f} Hz",
                fontsize=7, color=theme.tokens().text_dim, va="center",
            )

        self._ax.set_xlabel("Tempo (s)", fontsize=8)
        self._ax.set_ylabel("Hz", fontsize=8)
        self._ax.tick_params(axis="both", labelsize=7)
        self._ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.5)

        if label:
            self._ax.set_title(label, fontsize=9)

        self.draw_idle()
