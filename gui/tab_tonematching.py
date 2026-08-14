from __future__ import annotations

import logging
import time
import traceback

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import QThread, pyqtSignal

from gui.ui_tab_tonematching import Ui_TabToneMatching
from gui.plots import WaveformPlot, EQCurvePlot, SpectralCentroidPlot
from core.analyzer import AudioAnalyzer

logger = logging.getLogger(__name__)


class AnalysisWorker(QThread):
    """Executa o Tone Matching (análise Librosa) em uma thread separada da UI."""

    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)

    def __init__(self, stem_path: str) -> None:
        super().__init__()
        self.stem_path = stem_path

    def run(self) -> None:
        start_time = time.monotonic()
        try:
            logger.info(f"Iniciando análise: {self.stem_path}")
            self.status.emit("Extraindo parâmetros matemáticos…")

            params = AudioAnalyzer().analyze_stem(self.stem_path)
            elapsed = time.monotonic() - start_time

            eq = params.get("eq", {})
            logger.info(
                f"Análise concluída em {elapsed:.2f}s. "
                f"Gate: {params.get('noise_gate_threshold_db')} dB | "
                f"EQ (bass/mid/treble): "
                f"{eq.get('bass')}/{eq.get('mid')}/{eq.get('treble')} | "
                f"Silencioso: {params.get('is_silent')}"
            )
            self.finished.emit(params)

        except Exception:
            logger.exception("Erro durante análise.")
            self.error.emit(traceback.format_exc())


class TabToneMatching(QWidget, Ui_TabToneMatching):
    """
    Aba de Tone Matching: dispara a análise Librosa do stem selecionado
    e exibe os resultados (gate, EQ, gráficos de forma de onda, curva de
    EQ e brilho/spectral centroid).

    Sinais emitidos para o main_gui.py orquestrar o restante da aplicação:
        analysis_started()             — análise disparada
        analysis_finished(dict, str)   — (params, stem_name analisado)
        analysis_error(str)            — mensagem de erro
        status_message(str)            — texto para a barra de status
    """

    analysis_started  = pyqtSignal()
    analysis_finished = pyqtSignal(dict, str)
    analysis_error    = pyqtSignal(str)
    status_message     = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        self.waveform_plot = WaveformPlot()
        self.waveformContainerLayout.addWidget(self.waveform_plot)

        self.eq_curve_plot = EQCurvePlot()
        self.eqCurveContainerLayout.addWidget(self.eq_curve_plot)

        self.spectral_centroid_plot = SpectralCentroidPlot()
        self.spectralCentroidContainerLayout.addWidget(self.spectral_centroid_plot)

        self.stem_path: str = ""
        self.stem_name: str = ""
        self.last_analyzed_stem: str = ""
        self.analysis_thread: AnalysisWorker | None = None

        self.btn_run_analysis.clicked.connect(self.start_analysis)

    # API pública, chamada pelo main_gui.py

    def set_selected_stem(self, stem_name: str, stem_path: str) -> None:
        """
        Define qual stem está atualmente selecionado no combo compartilhado.

        Se o stem for diferente do último analisado, invalida os
        resultados exibidos (gráficos e labels), pois eles passam a se
        referir a uma faixa diferente da selecionada.
        """
        self.stem_name = stem_name
        self.stem_path = stem_path
        self.btn_run_analysis.setEnabled(bool(stem_path))

        if stem_name and stem_name != self.last_analyzed_stem and self.last_analyzed_stem:
            logger.debug(
                f"Stem selecionado ('{stem_name}') difere do último "
                f"analisado ('{self.last_analyzed_stem}'); limpando resultados."
            )
            self.clear_results()
            self.status_message.emit(
                f"Faixa alterada para '{stem_name}' — execute o Tone "
                f"Matching novamente para esta faixa."
            )

    def reset(self) -> None:
        """Reseta o estado da aba (ex.: ao carregar um novo arquivo)."""
        self.stem_path = ""
        self.stem_name = ""
        self.last_analyzed_stem = ""
        self.btn_run_analysis.setEnabled(False)
        self.clear_results()

    def clear_results(self) -> None:
        self.last_analyzed_stem = ""
        self.lbl_analyzed_stem.setText("")
        self.waveform_plot.clear_plot()
        self.eq_curve_plot.clear_plot()
        self.spectral_centroid_plot.clear_plot()

    def set_busy(self, busy: bool) -> None:
        self.btn_run_analysis.setEnabled(not busy and bool(self.stem_path))

    # Lógica interna

    def start_analysis(self) -> None:
        if not self.stem_path:
            logger.warning("Tentativa de iniciar análise sem stem selecionado.")
            return

        logger.info(f"Iniciando workflow análise (faixa selecionada: {self.stem_name}).")
        self.set_busy(True)
        self.analysis_started.emit()

        self._analyzing_stem = self.stem_name

        self.analysis_thread = AnalysisWorker(self.stem_path)
        self.analysis_thread.status.connect(self.status_message.emit)
        self.analysis_thread.finished.connect(self._on_finished)
        self.analysis_thread.error.connect(self._on_error)
        self.analysis_thread.start()

    def _on_finished(self, params: dict) -> None:
        logger.info("Workflow análise finalizado.")
        self.last_analyzed_stem = getattr(self, "_analyzing_stem", "")
        self.set_busy(False)

        gate = params.get("noise_gate_threshold_db", "--")
        eq   = params.get("eq", {})
        eq_curve = params.get("eq_curve", [])
        waveform = params.get("waveform", {})
        centroid_hz = params.get("spectral_centroid_hz", 0.0)
        centroid_curve = params.get("spectral_centroid_curve", [])

        self.lbl_analyzed_stem.setText(
            f"Parâmetros calculados a partir da faixa: '{self.last_analyzed_stem}'"
            + (f"  —  Brilho médio: {centroid_hz:.0f} Hz" if centroid_hz else "")
        )

        self.waveform_plot.plot_waveform(waveform, label=self.last_analyzed_stem)
        self.eq_curve_plot.plot_eq_curve(eq_curve, label=self.last_analyzed_stem)
        self.spectral_centroid_plot.plot_spectral_centroid(
            centroid_curve, mean_hz=centroid_hz, label=self.last_analyzed_stem
        )

        self.analysis_finished.emit(params, self.last_analyzed_stem)

    def _on_error(self, err_msg: str) -> None:
        logger.error(f"Erro na análise:\n{err_msg}")
        self.set_busy(False)
        self.analysis_error.emit(err_msg)

    def stop_thread(self) -> None:
        """Encerra a thread de análise, se estiver rodando (usado no closeEvent)."""
        if self.analysis_thread is not None and self.analysis_thread.isRunning():
            self.analysis_thread.quit()
            self.analysis_thread.wait(2000)
