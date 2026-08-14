from __future__ import annotations

import logging
import traceback

from PyQt6.QtWidgets import QWidget, QMessageBox, QListWidgetItem, QSystemTrayIcon
from PyQt6.QtCore import QThread, pyqtSignal, Qt

from gui.ui_tab_hardware import Ui_TabHardware
from core.hardware import ESP32Link, HardwareLinkError

logger = logging.getLogger(__name__)


class HardwareWorker(QThread):
    """Envia os parâmetros de Tone Matching para a ESP32-S3 em uma thread separada."""

    finished = pyqtSignal(bool)   # True se foi enviado em modo simulado (MOCK)
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)

    def __init__(self, params: dict, port: str | None = None) -> None:
        super().__init__()
        self.params = params
        self.port = port

    def run(self) -> None:
        try:
            logger.info("Iniciando envio para a ESP32-S3.")

            link = ESP32Link(port=self.port)
            was_mock = link.is_mock

            if was_mock:
                self.status.emit(
                    "Nenhuma placa detectada — simulando envio (modo MOCK)…"
                )
            else:
                self.status.emit(f"Conectando à porta {link.port}…")

            link.send_params(self.params, progress_cb=self.status.emit)
            link.close()

            logger.info("Envio para a ESP32-S3 concluído.")
            self.finished.emit(was_mock)

        except HardwareLinkError as exc:
            logger.exception("Erro de comunicação com a ESP32-S3.")
            self.error.emit(str(exc))

        except Exception:
            logger.exception("Erro inesperado durante o envio para hardware.")
            self.error.emit(traceback.format_exc())


class FilterQueryWorker(QThread):
    """Consulta a ESP32-S3 para descobrir quais filtros ela conhece."""

    finished = pyqtSignal(list, bool)   # (filtros, was_mock)
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)

    def __init__(self, port: str | None = None) -> None:
        super().__init__()
        self.port = port

    def run(self) -> None:
        try:
            logger.info("Consultando filtros disponíveis na ESP32-S3.")

            link = ESP32Link(port=self.port)
            was_mock = link.is_mock

            if was_mock:
                self.status.emit(
                    "Nenhuma placa detectada — usando filtros de exemplo (modo MOCK)…"
                )
            else:
                self.status.emit(f"Conectando à porta {link.port}…")

            filters = link.list_filters(progress_cb=self.status.emit)
            link.close()

            logger.info(f"Consulta de filtros concluída: {len(filters)} filtro(s).")
            self.finished.emit(filters, was_mock)

        except HardwareLinkError as exc:
            logger.exception("Erro de comunicação ao consultar filtros na ESP32-S3.")
            self.error.emit(str(exc))

        except Exception:
            logger.exception("Erro inesperado durante a consulta de filtros.")
            self.error.emit(traceback.format_exc())


class TabHardware(QWidget, Ui_TabHardware):
    """
    Aba de comunicação com a ESP32-S3: envio dos parâmetros de Tone
    Matching calculados e consulta/seleção dos filtros conhecidos pelo
    pedal.

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

        self.last_params: dict = {}
        self.hardware_thread: HardwareWorker | None = None
        self.filter_query_thread: FilterQueryWorker | None = None
        self._known_filters: dict = {}

        self.btn_send_hardware.clicked.connect(self.start_send_hardware)
        self.btn_query_filters.clicked.connect(self.start_query_filters)
        self.btn_apply_filters.clicked.connect(self.apply_selected_filters)
        self.list_filters.itemSelectionChanged.connect(
            self._on_filter_selection_changed
        )

    # API pública, chamada pelo main_gui.py

    def set_params(self, params: dict) -> None:
        """
        Define os últimos parâmetros de Tone Matching calculados,
        habilitando o botão de envio. Chamado pelo main_gui.py sempre
        que a aba de Tone Matching termina uma análise (ou invalida os
        resultados ao trocar de stem).
        """
        self.last_params = params
        self.btn_send_hardware.setEnabled(bool(params))

    def reset(self) -> None:
        """Reseta o estado da aba (ex.: ao carregar um novo arquivo)."""
        self.last_params = {}
        self.btn_send_hardware.setEnabled(False)

    # Envio de parâmetros

    def start_send_hardware(self) -> None:
        if not self.last_params:
            QMessageBox.warning(
                self,
                "Nenhum parâmetro calculado",
                "Execute a análise antes de enviar os dados para o pedal.",
            )
            return

        logger.info("Iniciando envio para a ESP32-S3.")
        self.btn_send_hardware.setEnabled(False)
        self.send_started.emit()

        # port=None → tenta autodetectar a placa; cai em modo simulado
        # (MOCK) automaticamente se nenhuma porta compatível for encontrada.
        self.hardware_thread = HardwareWorker(self.last_params, port=None)
        self.hardware_thread.status.connect(self.status_message.emit)
        self.hardware_thread.finished.connect(self._on_send_finished)
        self.hardware_thread.error.connect(self._on_send_error)
        self.hardware_thread.start()

    def _on_send_finished(self, was_mock: bool) -> None:
        logger.info("Workflow de envio para hardware finalizado.")
        self.btn_send_hardware.setEnabled(bool(self.last_params))

        if was_mock:
            QMessageBox.information(
                self,
                "Envio simulado (sem hardware)",
                "Nenhuma ESP32-S3 foi detectada na porta USB.\n\n"
                "Os parâmetros NÃO foram enviados para uma placa real — "
                "apenas simulados (modo MOCK), para fins de teste.\n\n"
                "Conecte a placa via USB e tente novamente quando ela "
                "estiver disponível."
            )

        self.send_finished.emit(was_mock)

    def _on_send_error(self, err_msg: str) -> None:
        logger.error(f"Erro ao enviar para a ESP32-S3:\n{err_msg}")
        self.btn_send_hardware.setEnabled(bool(self.last_params))

        QMessageBox.critical(
            self,
            "Erro de comunicação",
            f"Não foi possível enviar os parâmetros para a ESP32-S3:\n\n"
            f"{self._friendly_error_summary(err_msg)}\n\n"
            f"Detalhes completos foram registrados no terminal/log.",
        )
        self.send_error.emit(err_msg)

    # Seleção de filtros

    def start_query_filters(self) -> None:
        """Consulta a ESP32-S3 para descobrir quais filtros ela conhece."""
        logger.info("Iniciando consulta de filtros disponíveis.")
        self.btn_query_filters.setEnabled(False)
        self.btn_apply_filters.setEnabled(False)
        self.list_filters.clear()
        self.lbl_filters_status.setText("Consultando…")

        self.filter_query_thread = FilterQueryWorker(port=None)
        self.filter_query_thread.status.connect(self.status_message.emit)
        self.filter_query_thread.finished.connect(self._on_filters_received)
        self.filter_query_thread.error.connect(self._on_filter_query_error)
        self.filter_query_thread.start()

    def _on_filters_received(self, filters: list, was_mock: bool) -> None:
        logger.info(f"Filtros recebidos: {filters}")
        self.btn_query_filters.setEnabled(True)

        # Guarda os metadados completos de cada filtro (id, params) para uso
        # posterior — a QListWidget só mostra o nome, então associamos o
        # dicionário original a cada item via UserRole.
        self._known_filters = {f["id"]: f for f in filters}

        self.list_filters.clear()
        for f in filters:
            item = QListWidgetItem(f.get("name", f["id"]))
            item.setData(Qt.ItemDataRole.UserRole, f["id"])
            self.list_filters.addItem(item)

        if was_mock:
            self.lbl_filters_status.setText(
                f"{len(filters)} filtro(s) de exemplo (modo simulado — sem placa conectada)."
            )
        else:
            self.lbl_filters_status.setText(
                f"{len(filters)} filtro(s) disponível(is) no pedal."
            )

        self.status_message.emit("Consulta de filtros concluída.")

    def _on_filter_query_error(self, err_msg: str) -> None:
        logger.error(f"Erro ao consultar filtros na ESP32-S3:\n{err_msg}")
        self.btn_query_filters.setEnabled(True)
        self.lbl_filters_status.setText("Falha ao consultar filtros.")

        QMessageBox.critical(
            self,
            "Erro de comunicação",
            f"Não foi possível consultar os filtros da ESP32-S3:\n\n"
            f"{self._friendly_error_summary(err_msg)}\n\n"
            f"Detalhes completos foram registrados no terminal/log.",
        )

    def _on_filter_selection_changed(self) -> None:
        self.btn_apply_filters.setEnabled(
            len(self.list_filters.selectedItems()) > 0
        )

    def apply_selected_filters(self) -> None:
        """
        Esqueleto inicial: por ora, apenas registra e notifica quais
        filtros foram selecionados pelo usuário. O envio efetivo da
        configuração de cada filtro (com seus parâmetros específicos,
        ex.: freq_hz/gain_db de um low_shelf) depende de definirmos,
        junto ao firmware, o formato exato de configuração por filtro.
        """
        selected_ids = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.list_filters.selectedItems()
        ]
        selected_names = [item.text() for item in self.list_filters.selectedItems()]

        logger.info(f"Filtros selecionados para aplicação: {selected_ids}")

        self.status_message.emit(
            f"{len(selected_ids)} filtro(s) selecionado(s) — "
            f"envio de configuração ainda não implementado."
        )
        QMessageBox.information(
            self,
            "Seleção registrada",
            "Filtros selecionados:\n\n"
            + "\n".join(f"• {name}" for name in selected_names)
            + "\n\nO envio da configuração de cada filtro para o pedal "
            "ainda será implementado — por enquanto, esta tela apenas "
            "registra a seleção."
        )

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
        for thread in (self.hardware_thread, self.filter_query_thread):
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait(2000)
