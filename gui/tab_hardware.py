from __future__ import annotations

import logging
import traceback

from PyQt6.QtWidgets import QWidget, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal

from gui.ui_tab_hardware import Ui_TabHardware
from core.hardware import ESP32Link, HardwareLinkError, PedalState

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
    Aba de comunicação com a ESP32-S3: controles diretos para os três
    efeitos fixos implementados no firmware atual (Noise Gate, Overdrive
    e Delay), com envio do estado completo via protocolo binário
    COBS/PedalState (ver core/hardware.py).

    O firmware não expõe mais um comando de descoberta de filtros — os
    efeitos disponíveis são fixos no código da placa de UI (Board B), e
    esta aba espelha exatamente esses três efeitos e seus parâmetros.

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

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        self.hardware_thread: HardwareWorker | None = None

        self.btn_send_hardware.clicked.connect(self.start_send_hardware)

        # Sincroniza os labels de valor com os sliders
        self.slider_gate_threshold.valueChanged.connect(self._update_gate_label)
        self.slider_dist_drive.valueChanged.connect(self._update_dist_drive_label)
        self.slider_dist_level.valueChanged.connect(self._update_dist_level_label)
        self.slider_delay_time.valueChanged.connect(self._update_delay_time_label)
        self.slider_delay_feedback.valueChanged.connect(self._update_delay_feedback_label)
        self.slider_delay_mix.valueChanged.connect(self._update_delay_mix_label)

        # Se o usuário mexer manualmente no threshold do gate, isso deixa
        # de ser "vindo do Tone Matching" — limpa a anotação de origem.
        self.slider_gate_threshold.valueChanged.connect(
            lambda _: self.lbl_gate_source.setText("(ajustado manualmente)")
        )

    # Sincronização de labels

    def _update_gate_label(self, value: int) -> None:
        self.lbl_gate_threshold_value.setText(f"{value} dB")

    def _update_dist_drive_label(self, value: int) -> None:
        self.lbl_dist_drive_value.setText(f"{value}%")

    def _update_dist_level_label(self, value: int) -> None:
        self.lbl_dist_level_value.setText(f"{value}%")

    def _update_delay_time_label(self, value: int) -> None:
        self.lbl_delay_time_value.setText(f"{value} ms")

    def _update_delay_feedback_label(self, value: int) -> None:
        self.lbl_delay_feedback_value.setText(f"{value}%")

    def _update_delay_mix_label(self, value: int) -> None:
        self.lbl_delay_mix_value.setText(f"{value}%")

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

        gate_db = params.get("noise_gate_threshold_db")
        if gate_db is not None:
            clamped = max(
                self.slider_gate_threshold.minimum(),
                min(self.slider_gate_threshold.maximum(), round(gate_db)),
            )
            self.slider_gate_threshold.setValue(clamped)
            self.check_gate_active.setChecked(True)
            self.lbl_gate_source.setText("(a partir do Tone Matching)")

    def reset(self) -> None:
        """Reseta o estado da aba (ex.: ao carregar um novo arquivo)."""
        self.lbl_gate_source.setText("")

    def _build_pedal_state(self) -> PedalState:
        """Monta um PedalState a partir do estado atual dos controles da aba."""
        return PedalState(
            gate_active=self.check_gate_active.isChecked(),
            gate_threshold=float(self.slider_gate_threshold.value()),
            dist_active=self.check_dist_active.isChecked(),
            dist_drive=1.0 + (self.slider_dist_drive.value() / 100.0) * 19.0,
            dist_level=self.slider_dist_level.value() / 100.0,
            delay_active=self.check_delay_active.isChecked(),
            delay_time_samples=int((self.slider_delay_time.value() * 44100) / 1000),
            delay_feedback=(self.slider_delay_feedback.value() / 100.0) * 0.95,
            delay_mix=self.slider_delay_mix.value() / 100.0,
        )

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
