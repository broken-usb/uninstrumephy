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
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, stem_path: str) -> None:
        super().__init__()
        self.stem_path = stem_path

    def run(self) -> None:
        start_time = time.monotonic()
        try:
            logger.info(f"Iniciando análise avançada: {self.stem_path}")
            self.status.emit("Extraindo espectro, harmônicos e dinâmica com Librosa…")

            params = AudioAnalyzer().analyze_stem(self.stem_path)
            elapsed = time.monotonic() - start_time

            eq4 = params.get("eq_4bands", {})
            logger.info(
                f"Análise concluída em {elapsed:.2f}s. "
                f"Gate: {params.get('noise_gate_threshold_db')} dB | "
                f"EQ 4B: {eq4} | Centroid: {params.get('spectral_centroid_hz')} Hz"
            )
            self.finished.emit(params)

        except Exception:
            logger.exception("Erro durante análise de Tone Matching.")
            self.error.emit(traceback.format_exc())


class TabToneMatching(QWidget, Ui_TabToneMatching):
    analysis_started = pyqtSignal()
    analysis_finished = pyqtSignal(dict, str)
    analysis_error = pyqtSignal(str)
    status_message = pyqtSignal(str)

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

    def set_selected_stem(self, stem_name: str, stem_path: str) -> None:
        self.stem_name = stem_name
        self.stem_path = stem_path
        self.btn_run_analysis.setEnabled(bool(stem_path))

        if stem_name and stem_name != self.last_analyzed_stem and self.last_analyzed_stem:
            logger.debug(
                f"Stem selecionado ('{stem_name}') difere do último analisado ('{self.last_analyzed_stem}'). Limpando."
            )
            self.clear_results()
            self.status_message.emit(
                f"Faixa alterada para '{stem_name}' — execute o Tone Matching para atualizar os parâmetros."
            )

    def reset(self) -> None:
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

    def start_analysis(self) -> None:
        if not self.stem_path:
            logger.warning("Tentativa de iniciar análise sem stem selecionado.")
            return

        logger.info(f"Disparando análise de Tone Matching: {self.stem_name}")
        self.set_busy(True)
        self.analysis_started.emit()

        self._analyzing_stem = self.stem_name
        self.analysis_thread = AnalysisWorker(self.stem_path)
        self.analysis_thread.status.connect(self.status_message.emit)
        self.analysis_thread.finished.connect(self._on_finished)
        self.analysis_thread.error.connect(self._on_error)
        self.analysis_thread.start()

    def _on_finished(self, params: dict) -> None:
        logger.info("Análise Librosa finalizada com sucesso.")
        self.last_analyzed_stem = getattr(self, "_analyzing_stem", "")
        self.set_busy(False)

        gate = params.get("noise_gate_threshold_db", "--")
        eq4 = params.get("eq_4bands", {})
        eq_curve = params.get("eq_curve", [])
        waveform = params.get("waveform", {})
        centroid_hz = params.get("spectral_centroid_hz", 0.0)
        centroid_curve = params.get("spectral_centroid_curve", [])
        overdrive = params.get("overdrive", {})
        comp = params.get("compressor", {})

        # Resumo legível na interface contendo múltiplos dados calculados
        summary_text = (
            f"Faixa: '{self.last_analyzed_stem}' | "
            f"Gate: {gate} dB | "
            f"EQ: [100Hz: {eq4.get('low_db', 0):+d}dB, 500Hz: {eq4.get('mid1_db', 0):+d}dB, "
            f"1.5kHz: {eq4.get('mid2_db', 0):+d}dB, 4.5kHz: {eq4.get('high_db', 0):+d}dB] | "
            f"Brilho (Tone): {overdrive.get('tone_pct', 50)}% ({centroid_hz:.0f} Hz) | "
            f"Perfil: {'Saturado/Overdrive' if overdrive.get('suggested_active') else 'Limpo/Dinâmico'}"
        )
        self.lbl_analyzed_stem.setText(summary_text)

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
        if self.analysis_thread is not None and self.analysis_thread.isRunning():
            self.analysis_thread.quit()
            self.analysis_thread.wait(2000)