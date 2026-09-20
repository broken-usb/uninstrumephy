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

    TONE_MATCHING_GATE_KEY = "gate"
    TONE_MATCHING_GATE_PARAM = "gate_threshold"
    TONE_MATCHING_EQ_KEY = "eq"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        self.hardware_thread: HardwareWorker | None = None

        # Monta dinamicamente os 12 EffectWidgets dentro da scroll area
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

        # Limpa anotação de Tone Matching se houver ajuste manual
        gate_w = self.effect_widgets.get(self.TONE_MATCHING_GATE_KEY)
        if gate_w is not None:
            gate_w.changed.connect(self._clear_source_label)

        eq_w = self.effect_widgets.get(self.TONE_MATCHING_EQ_KEY)
        if eq_w is not None:
            eq_w.changed.connect(self._clear_source_label)

    def _clear_source_label(self) -> None:
        self.lbl_gate_source.setText("(ajustado manualmente)")

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
        self.status_message.emit(f"Preset '{name.strip()}' salvo com sucesso.")

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

        self.lbl_gate_source.setText("(carregado do preset)")
        if warnings:
            QMessageBox.warning(
                self,
                "Preset carregado com ressalvas",
                "Alguns parâmetros foram ignorados por incompatibilidade:\n\n"
                + "\n".join(f"• {w}" for w in warnings),
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
        Preenche os parâmetros calculados pelo Tone Matching (Noise Gate e EQ 4-bandas).
        """
        if not params:
            return

        updated_items = []

        # 1. Noise Gate
        gate_db = params.get("noise_gate_threshold_db")
        gate_widget = self.effect_widgets.get(self.TONE_MATCHING_GATE_KEY)
        if gate_db is not None and gate_widget is not None:
            gate_widget.set_param_value(self.TONE_MATCHING_GATE_PARAM, round(gate_db))
            gate_widget.set_active(True)
            updated_items.append("Gate")

        # 2. Equalizador 4 Bandas
        eq_data = params.get("eq", {})
        eq_widget = self.effect_widgets.get(self.TONE_MATCHING_EQ_KEY)
        if eq_data and eq_widget is not None:
            bass = eq_data.get("bass", 3.33)
            mid = eq_data.get("mid", 3.33)
            treble = eq_data.get("treble", 3.33)

            # Mapeamento do balanço de energia espectral para dB (-12 dB a +12 dB)
            low_db = max(-12, min(12, round((bass - 3.33) * 2.5)))
            mid1_db = max(-12, min(12, round((mid - 3.33) * 2.5)))
            mid2_db = max(-12, min(12, round((mid - 3.33) * 2.0)))
            high_db = max(-12, min(12, round((treble - 3.33) * 2.5)))

            eq_widget.set_param_value("eq_low_gain", low_db)
            eq_widget.set_param_value("eq_mid1_gain", mid1_db)
            eq_widget.set_param_value("eq_mid2_gain", mid2_db)
            eq_widget.set_param_value("eq_high_gain", high_db)
            eq_widget.set_active(True)
            updated_items.append("EQ")

        if updated_items:
            self.lbl_gate_source.setText(f"({ ' e '.join(updated_items) } preenchido(s) a partir do Tone Matching)")

    def reset(self) -> None:
        self.lbl_gate_source.setText("")

    def _build_pedal_state(self) -> PedalState:
        fields: dict = {}
        for widget in self.effect_widgets.values():
            fields.update(widget.to_struct_fields())
        return PedalState(**fields)

    def start_send_hardware(self) -> None:
        state = self._build_pedal_state()
        logger.info(f"Enviando estado para a ESP32-S3: {state!r}")
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
                "Nenhuma ESP32-S3 conectada via USB foi detectada.\n\n"
                "O pacote binário de 140 bytes com COBS foi gerado e simulado com sucesso.",
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