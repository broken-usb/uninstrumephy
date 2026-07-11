from __future__ import annotations

import json
import logging
import time
from typing import Callable

import serial
from serial.tools import list_ports

logger = logging.getLogger(__name__)

# Porta especial que ativa o modo simulado (sem hardware físico conectado).
# Útil para desenvolver e demonstrar o software antes da placa chegar.
MOCK_PORT = "MOCK"


class HardwareLinkError(Exception):
    """Erro genérico de comunicação com a placa ESP32-S3."""


class ESP32Link:
    """
    Envia os parâmetros de tone-matching calculados pelo AudioAnalyzer
    para uma ESP32-S3 conectada via USB (porta serial), usando um
    protocolo simples de uma linha JSON por mensagem.

    Formato enviado (terminado em '\\n'):
        {"noise_gate_threshold_db": -42.5, "eq": {"bass": 4.1, "mid": 3.2, "treble": 2.7}}

    Modo simulado:
        Use port=MOCK_PORT (ou port="MOCK") para simular o envio sem
        precisar de hardware físico conectado. Nesse modo, nada é
        escrito de fato em uma porta serial — o payload é apenas
        logado, o que permite testar todo o fluxo da GUI sem a placa.
    """

    BAUDRATE: int = 115_200
    TIMEOUT_S: float = 2.0

    # Tempo de espera após abrir a porta: a maioria das placas baseadas em
    # ESP32 reinicia ao abrir a conexão serial (DTR/RTS), então é preciso
    # aguardar o boot antes de enviar dados, ou os primeiros bytes se perdem.
    BOOT_DELAY_S: float = 2.0

    def __init__(self, port: str | None = None) -> None:
        self.port = port or self._autodetect_port()
        self.is_mock = self.port == MOCK_PORT
        self._conn: serial.Serial | None = None

    @staticmethod
    def _autodetect_port() -> str:
        """
        Tenta localizar automaticamente a porta da ESP32-S3 pela descrição
        do dispositivo USB. Ajuste os termos de busca conforme o chip
        USB-serial da placa (ex.: CP210x, CH340, nativo USB-CDC etc.).

        Se nenhuma porta for encontrada, cai automaticamente no modo mock
        para não travar o fluxo do usuário — apenas registra um aviso.
        """
        candidates = [
            p.device
            for p in list_ports.comports()
            if any(
                keyword in (p.description or "").upper()
                for keyword in ("CP210", "CH340", "ESP32", "USB", "USB-SERIAL")
            )
        ]
        if not candidates:
            logger.warning(
                "Nenhuma porta serial compatível foi encontrada. "
                "Usando modo simulado (MOCK)."
            )
            return MOCK_PORT
        return candidates[0]

    @staticmethod
    def list_available_ports() -> list[str]:
        """Retorna a lista de portas seriais disponíveis no sistema, para popular um combo na GUI."""
        return [p.device for p in list_ports.comports()]

    def connect(self) -> None:
        if self.is_mock:
            logger.info("[MOCK] Conexão simulada estabelecida (sem hardware).")
            return

        try:
            self._conn = serial.Serial(
                self.port, self.BAUDRATE, timeout=self.TIMEOUT_S
            )
            # Aguarda o boot/reset da placa após abrir a porta
            time.sleep(self.BOOT_DELAY_S)
            logger.info(f"Conectado à ESP32-S3 na porta {self.port}")
        except serial.SerialException as exc:
            raise HardwareLinkError(f"Falha ao abrir {self.port}: {exc}") from exc

    def send_params(
        self,
        params: dict,
        progress_cb: Callable[[str], None] | None = None,
    ) -> None:
        """
        Envia os parâmetros de tone-matching como uma linha JSON.

        Args:
            params: Dicionário retornado por AudioAnalyzer.analyze_stem()
                    (ex.: {"noise_gate_threshold_db": ..., "eq": {...}}).
            progress_cb: Callback opcional de progresso, para conectar a
                    um pyqtSignal da UI.

        Raises:
            HardwareLinkError: Se a conexão ou o envio falharem.
        """
        # Envia apenas os campos relevantes para o firmware, evitando
        # vazar metadados internos (ex.: is_silent) sem necessidade
        payload = {
            "noise_gate_threshold_db": params.get("noise_gate_threshold_db"),
            "eq": params.get("eq", {}),
        }

        if self.is_mock:
            self._notify(progress_cb, "[Simulado] Conectando…")
            self._notify(progress_cb, f"[Simulado] Enviando: {payload}")
            logger.info(f"[MOCK] Payload que seria enviado: {payload}")
            self._notify(progress_cb, "[Simulado] Envio concluído (nenhum hardware real envolvido).")
            return

        if self._conn is None or not self._conn.is_open:
            self._notify(progress_cb, f"Conectando à porta {self.port}…")
            self.connect()

        line = (json.dumps(payload) + "\n").encode("utf-8")

        try:
            self._notify(progress_cb, "Enviando parâmetros…")
            self._conn.write(line)
            self._conn.flush()
            logger.info(f"Parâmetros enviados: {payload}")
            self._notify(progress_cb, "Envio concluído.")
        except serial.SerialException as exc:
            raise HardwareLinkError(f"Falha ao enviar dados: {exc}") from exc

    def close(self) -> None:
        if self._conn is not None and self._conn.is_open:
            self._conn.close()
            logger.info("Conexão serial encerrada.")

    @staticmethod
    def _notify(cb: Callable[[str], None] | None, msg: str) -> None:
        if cb is not None:
            cb(msg)

    def __enter__(self) -> "ESP32Link":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()