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
    """Envia um PedalState completo para a ESP32-S3 em uma thread separada."""

    finished = pyqtSignal(bool)   # True se foi enviado em modo simulado (MOCK)
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)

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
                self.status.emit(
                    "Nenhuma placa detectada — simulando envio (modo MOCK)…"
                )
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
    """
    Aba de comunicação com a ESP32-S3: renderiza um EffectWidget por
    efeito definido em core/effects_spec.py (EFFECT_SPECS), monta um
    PedalState a partir do estado atual desses widgets, e o envia via
    protocolo binário COBS (ver core/hardware.py).

    Arquitetura modular: nem esta classe, nem o .ui, precisam ser
    alterados para adicionar um novo efeito — desde que o campo
    correspondente já exista em PedalState.h (arquivo compartilhado com
    o firmware), basta acrescentar uma nova EffectSpec em
    core/effects_spec.py e o widget correspondente aparece
    automaticamente nesta aba, já lido corretamente por
    _build_pedal_state() e set_params().

    O threshold do Noise Gate pode ser preenchido automaticamente a
    partir do resultado do Tone Matching (ver set_params), ou ajustado
    manualmente pelo usuário — o valor manual sempre prevalece até a
    próxima análise ser propagada.

    Sinais emitidos para o main_gui.py orquestrar o restante da aplicação:
        send_started() / send_finished(bool) / send_error(str)
        status_message(str)
    """

    send_started  = pyqtSignal()
    send_finished = pyqtSignal(bool)   # was_mock
    send_error    = pyqtSignal(str)
    status_message = pyqtSignal(str)

    # Efeito cujo primeiro parâmetro é preenchido automaticamente a
    # partir do Tone Matching (ver set_params). Os demais efeitos são
    # controlados manualmente pelo usuário nesta aba.
    TONE_MATCHING_TARGET_KEY = "gate"
    TONE_MATCHING_TARGET_PARAM = "gate_threshold"
    TONE_MATCHING_SOURCE_FIELD = "noise_gate_threshold_db"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        self.hardware_thread: HardwareWorker | None = None

        # Constrói dinamicamente um EffectWidget por EffectSpec — este é
        # o ponto que torna a aba modular: adicionar/remover efeitos em
        # EFFECT_SPECS muda o que aparece aqui, sem tocar nesta classe.
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

        # Se o usuário mexer manualmente no threshold do gate, isso deixa
        # de ser "vindo do Tone Matching" — limpa a anotação de origem.
        gate_widget = self.effect_widgets.get(self.TONE_MATCHING_TARGET_KEY)
        if gate_widget is not None:
            gate_widget.changed.connect(self._clear_gate_source_label)

    def _clear_gate_source_label(self) -> None:
        self.lbl_gate_source.setText("(ajustado manualmente)")

    # Presets

    def _refresh_presets_combo(self) -> None:
        """Repopula o combo de presets a partir dos arquivos salvos em disco."""
        current = self.combo_presets.currentText()
        self.combo_presets.blockSignals(True)
        self.combo_presets.clear()
        self.combo_presets.addItems(list_presets())
        # Tenta manter a seleção anterior, se ainda existir
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

        logger.info(f"Preset salvo pelo usuário: {path}")
        self._refresh_presets_combo()
        index = self.combo_presets.findText(name.strip())
        if index >= 0:
            self.combo_presets.setCurrentIndex(index)
        self.status_message.emit(f"Preset '{name.strip()}' salvo.")

    def _on_load_preset_clicked(self) -> None:
        name = self.combo_presets.currentText()
        if not name:
            QMessageBox.warning(
                self,
                "Nenhum preset selecionado",
                "Selecione um preset no combo antes de carregar.",
            )
            return

        try:
            warnings = load_preset(name, self.effect_widgets)
        except PresetError as exc:
            QMessageBox.critical(self, "Erro ao carregar preset", str(exc))
            return

        # Carregar um preset conta como ajuste manual do gate: a
        # anotação "(a partir do Tone Matching)" deixa de fazer sentido
        # até uma nova análise ser propagada.
        self.lbl_gate_source.setText("(carregado do preset)")

        if warnings:
            QMessageBox.warning(
                self,
                "Preset carregado com ressalvas",
                f"O preset '{name}' foi carregado, mas alguns itens não "
                f"existem na versão atual e foram ignorados:\n\n"
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
            f"Tem certeza que deseja excluir o preset '{name}'?\n"
            f"Esta ação não pode ser desfeita.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        delete_preset(name)
        self._refresh_presets_combo()
        self.status_message.emit(f"Preset '{name}' excluído.")

    # API pública, chamada pelo main_gui.py

    def set_params(self, params: dict) -> None:
        """
        Preenche o threshold do Noise Gate a partir do resultado do Tone
        Matching. Chamado pelo main_gui.py sempre que a aba de Tone
        Matching termina uma análise (ou invalida os resultados ao
        trocar de stem, casos em que params vem vazio e nada é alterado
        aqui além da anotação de origem).

        Nota: a struct PedalState do firmware atual não possui campos de
        equalização (bass/mid/treble) — apenas o threshold do Noise Gate
        é aproveitado do Tone Matching. Os valores de EQ calculados não
        têm, por ora, para onde ir no protocolo.
        """
        if not params:
            return

        gate_db = params.get(self.TONE_MATCHING_SOURCE_FIELD)
        gate_widget = self.effect_widgets.get(self.TONE_MATCHING_TARGET_KEY)

        if gate_db is not None and gate_widget is not None:
            gate_widget.set_param_value(
                self.TONE_MATCHING_TARGET_PARAM, round(gate_db)
            )
            gate_widget.set_active(True)
            self.lbl_gate_source.setText("(a partir do Tone Matching)")

    def reset(self) -> None:
        """Reseta o estado da aba (ex.: ao carregar um novo arquivo)."""
        self.lbl_gate_source.setText("")

    def _build_pedal_state(self) -> PedalState:
        """
        Monta um PedalState a partir do estado atual de todos os
        EffectWidgets, coletando os campos via to_struct_fields() de
        cada um e combinando-os em um único dicionário de kwargs.
        """
        fields: dict = {}
        for widget in self.effect_widgets.values():
            fields.update(widget.to_struct_fields())
        return PedalState(**fields)

    # Envio de parâmetros

    def start_send_hardware(self) -> None:
        state = self._build_pedal_state()

        logger.info(f"Iniciando envio para a ESP32-S3: {state!r}")
        self.btn_send_hardware.setEnabled(False)
        self.send_started.emit()

        # port=None → tenta autodetectar a placa; cai em modo simulado
        # (MOCK) automaticamente se nenhuma porta compatível for encontrada.
        self.hardware_thread = HardwareWorker(state, port=None)
        self.hardware_thread.status.connect(self.status_message.emit)
        self.hardware_thread.finished.connect(self._on_send_finished)
        self.hardware_thread.error.connect(self._on_send_error)
        self.hardware_thread.start()

    def _on_send_finished(self, was_mock: bool) -> None:
        logger.info("Workflow de envio para hardware finalizado.")
        self.btn_send_hardware.setEnabled(True)

        if was_mock:
            QMessageBox.information(
                self,
                "Envio simulado (sem hardware)",
                "Nenhuma ESP32-S3 foi detectada na porta USB.\n\n"
                "O estado NÃO foi enviado para uma placa real — "
                "apenas simulado (modo MOCK), para fins de teste.\n\n"
                "Conecte a placa via USB e tente novamente quando ela "
                "estiver disponível."
            )

        self.send_finished.emit(was_mock)

    def _on_send_error(self, err_msg: str) -> None:
        logger.error(f"Erro ao enviar para a ESP32-S3:\n{err_msg}")
        self.btn_send_hardware.setEnabled(True)

        QMessageBox.critical(
            self,
            "Erro de comunicação",
            f"Não foi possível enviar o estado para a ESP32-S3:\n\n"
            f"{self._friendly_error_summary(err_msg)}\n\n"
            f"Detalhes completos foram registrados no terminal/log.",
        )
        self.send_error.emit(err_msg)

    # Utilitários

    @staticmethod
    def _friendly_error_summary(err_msg: str) -> str:
        """
        Extrai a última linha útil de um traceback do Python para exibir
        um resumo legível na UI, em vez do stack trace completo.
        """
        lines = [line.strip() for line in err_msg.strip().splitlines() if line.strip()]
        if not lines:
            return "Ocorreu um erro inesperado."
        return lines[-1]

    def stop_threads(self) -> None:
        """Encerra as threads em execução, se houver (usado no closeEvent)."""
        if self.hardware_thread is not None and self.hardware_thread.isRunning():
            self.hardware_thread.quit()
            self.hardware_thread.wait(2000)
