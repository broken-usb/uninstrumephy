from __future__ import annotations

import logging
import traceback

from PyQt6.QtWidgets import QWidget, QMessageBox, QInputDialog
from PyQt6.QtCore import QThread, pyqtSignal

from gui.ui_tab_hardware import Ui_TabHardware
from gui.effect_widget import EffectWidget
from core.effects_spec import EFFECT_SPECS
from core.hardware import ESP32Link, HardwareLinkError, PedalState
from core.presets import (
    save_preset,
    load_preset,
    list_presets,
    delete_preset,
    PresetError,
)

logger = logging.getLogger(__name__)


class HardwareWorker(QThread):
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, state: PedalState, port: str | None = None) -> None:
        super().__init__()
        self.state = state
        self.port = port

    def run(self) -> None:
        try:
            logger.info(f"Iniciando envio para a ESP32-S3: {self.state!r}")

            link = ESP32Link(port=self.port)
            was_mock = link.is_mock

            if was_mock:
                self.status.emit("Nenhuma placa física detectada — simulando envio (modo MOCK)…")
            else:
                self.status.emit(f"Conectando à porta {link.port}…")

            link.send_state(self.state, progress_cb=self.status.emit)
            link.close()

            logger.info("Envio para a ESP32-S3 concluído.")
            self.finished.emit(was_mock)

        except HardwareLinkError as exc:
            logger.exception("Erro de comunicação com a ESP32-S3.")
            self.error.emit(str(exc))

        except Exception:
            logger.exception("Erro inesperado durante o envio para hardware.")
            self.error.emit(traceback.format_exc())


class TabHardware(QWidget, Ui_TabHardware):
    send_started = pyqtSignal()
    send_finished = pyqtSignal(bool)
    send_error = pyqtSignal(str)
    status_message = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        self.hardware_thread: HardwareWorker | None = None

        # Constrói dinamicamente os 12 EffectWidgets dentro do container com rolagem
        self.effect_widgets: dict[str, EffectWidget] = {}
        for spec in EFFECT_SPECS:
            widget = EffectWidget(spec)
            self.effectsContainerLayout.addWidget(widget)
            self.effect_widgets[spec.key] = widget

        self.btn_send_hardware.clicked.connect(self.start_send_hardware)
        self.btn_save_preset.clicked.connect(self._on_save_preset_clicked)
        self.btn_load_preset.clicked.connect(self._on_load_preset_clicked)
        self.btn_delete_preset.clicked.connect(self._on_delete_preset_clicked)
        self._refresh_presets_combo()

        # Monitora ajustes manuais para atualizar aviso de origem
        for key in ("gate", "eq", "overdrive", "comp"):
            w = self.effect_widgets.get(key)
            if w is not None:
                w.changed.connect(self._on_effect_manually_changed)

    def _on_effect_manually_changed(self) -> None:
        if not getattr(self, "_applying_tone_matching", False):
            self.lbl_gate_source.setText("(ajustado manualmente pelo usuário)")

    def _refresh_presets_combo(self) -> None:
        current = self.combo_presets.currentText()
        self.combo_presets.blockSignals(True)
        self.combo_presets.clear()
        self.combo_presets.addItems(list_presets())
        index = self.combo_presets.findText(current)
        if index >= 0:
            self.combo_presets.setCurrentIndex(index)
        self.combo_presets.blockSignals(False)

    def _on_save_preset_clicked(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "Salvar preset",
            "Nome do preset:",
            text=self.combo_presets.currentText(),
        )
        if not ok or not name.strip():
            return

        try:
            path = save_preset(name, self.effect_widgets)
        except PresetError as exc:
            QMessageBox.critical(self, "Erro ao salvar preset", str(exc))
            return

        logger.info(f"Preset salvo: {path}")
        self._refresh_presets_combo()
        index = self.combo_presets.findText(name.strip())
        if index >= 0:
            self.combo_presets.setCurrentIndex(index)
        self.status_message.emit(f"Preset '{name.strip()}' salvo.")

    def _on_load_preset_clicked(self) -> None:
        name = self.combo_presets.currentText()
        if not name:
            QMessageBox.warning(self, "Aviso", "Selecione um preset para carregar.")
            return

        try:
            warnings = load_preset(name, self.effect_widgets)
        except PresetError as exc:
            QMessageBox.critical(self, "Erro ao carregar preset", str(exc))
            return

        self.lbl_gate_source.setText("(carregado do preset local)")
        if warnings:
            QMessageBox.warning(
                self,
                "Preset carregado com ressalvas",
                "Alguns parâmetros foram ignorados:\n\n" + "\n".join(f"• {w}" for w in warnings),
            )
        self.status_message.emit(f"Preset '{name}' carregado.")

    def _on_delete_preset_clicked(self) -> None:
        name = self.combo_presets.currentText()
        if not name:
            return

        confirm = QMessageBox.question(
            self,
            "Excluir preset",
            f"Deseja excluir o preset '{name}' permanentemente?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        delete_preset(name)
        self._refresh_presets_combo()
        self.status_message.emit(f"Preset '{name}' excluído.")

    def set_params(self, params: dict) -> None:
        """
        Preenche múltiplos efeitos a partir dos dados extraídos pelo Tone Matching:
          1. Noise Gate (Threshold dB)
          2. Equalizador de 4 Bandas (Ganhos em 100Hz, 500Hz, 1.5kHz, 4.5kHz)
          3. Overdrive (Tone ajustado ao Spectral Centroid e Drive sugerido)
          4. Compressor (Threshold e Ratio sugeridos se houver faixa dinâmica ampla)
        """
        if not params:
            return

        self._applying_tone_matching = True
        updated_modules = []

        try:
            # 1. Noise Gate
            gate_db = params.get("noise_gate_threshold_db")
            gate_widget = self.effect_widgets.get("gate")
            if gate_db is not None and gate_widget is not None:
                gate_widget.set_param_value("gate_threshold", round(gate_db))
                gate_widget.set_active(True)
                updated_modules.append("Noise Gate")

            # 2. Equalizador 4 Bandas
            eq_4b = params.get("eq_4bands", {})
            eq_widget = self.effect_widgets.get("eq")
            if eq_4b and eq_widget is not None:
                eq_widget.set_param_value("eq_low_gain", eq_4b.get("low_db", 0))
                eq_widget.set_param_value("eq_mid1_gain", eq_4b.get("mid1_db", 0))
                eq_widget.set_param_value("eq_mid2_gain", eq_4b.get("mid2_db", 0))
                eq_widget.set_param_value("eq_high_gain", eq_4b.get("high_db", 0))
                eq_widget.set_active(True)
                updated_modules.append("EQ (4 Bandas)")

            # 3. Overdrive (Tone e Saturação)
            od_data = params.get("overdrive", {})
            od_widget = self.effect_widgets.get("overdrive")
            if od_data and od_widget is not None:
                tone_val = od_data.get("tone_pct", 50)
                od_widget.set_param_value("dist_tone", tone_val)
                if od_data.get("suggested_active", False):
                    od_widget.set_param_value("dist_drive", od_data.get("drive_pct", 35))
                    od_widget.set_active(True)
                    updated_modules.append("Overdrive (Ativo)")
                else:
                    updated_modules.append("Overdrive (Tone)")

            # 4. Compressor
            comp_data = params.get("compressor", {})
            comp_widget = self.effect_widgets.get("comp")
            if comp_data and comp_widget is not None:
                comp_widget.set_param_value("comp_threshold", comp_data.get("threshold_pct", 40))
                ratio_val = round(comp_data.get("ratio", 3.0) * 10.0)
                comp_widget.set_param_value("comp_ratio", ratio_val)
                if comp_data.get("suggested_active", False):
                    comp_widget.set_active(True)
                    updated_modules.append("Compressor")

            if updated_modules:
                self.lbl_gate_source.setText(
                    f"● Módulos configurados pelo Tone Matching: {', '.join(updated_modules)}."
                )
        finally:
            self._applying_tone_matching = False

    def reset(self) -> None:
        self.lbl_gate_source.setText("")

    def _build_pedal_state(self) -> PedalState:
        fields: dict = {}
        for widget in self.effect_widgets.values():
            fields.update(widget.to_struct_fields())
        return PedalState(**fields)

    def start_send_hardware(self) -> None:
        state = self._build_pedal_state()
        logger.info(f"Disparando transmissão completa do PedalState: {state!r}")
        self.btn_send_hardware.setEnabled(False)
        self.send_started.emit()

        self.hardware_thread = HardwareWorker(state, port=None)
        self.hardware_thread.status.connect(self.status_message.emit)
        self.hardware_thread.finished.connect(self._on_send_finished)
        self.hardware_thread.error.connect(self._on_send_error)
        self.hardware_thread.start()

    def _on_send_finished(self, was_mock: bool) -> None:
        self.btn_send_hardware.setEnabled(True)
        if was_mock:
            QMessageBox.information(
                self,
                "Envio simulado (Modo MOCK)",
                "Nenhuma ESP32-S3 física detectada na porta serial.\n\n"
                "O pacote binário consolidado (140 bytes via COBS) foi codificado e simulado com sucesso.",
            )
        self.send_finished.emit(was_mock)

    def _on_send_error(self, err_msg: str) -> None:
        self.btn_send_hardware.setEnabled(True)
        QMessageBox.critical(
            self,
            "Erro de Comunicação",
            f"Não foi possível enviar o pacote para a ESP32-S3:\n\n{err_msg}",
        )
        self.send_error.emit(err_msg)

    def stop_threads(self) -> None:
        if self.hardware_thread is not None and self.hardware_thread.isRunning():
            self.hardware_thread.quit()
            self.hardware_thread.wait(2000)