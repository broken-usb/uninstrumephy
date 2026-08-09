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

    Formato enviado para tone-matching (terminado em '\\n'):
        {"noise_gate_threshold_db": -42.5, "eq": {"bass": 4.1, "mid": 3.2, "treble": 2.7}}

    Formato do protocolo de descoberta de filtros (comando/resposta):
        Software → ESP32:  {"cmd": "list_filters"}
        ESP32 → Software:  {"filters": [
            {"id": "low_shelf", "name": "Low Shelf", "params": ["freq_hz", "gain_db"]},
            {"id": "peaking",   "name": "Peaking",   "params": ["freq_hz", "gain_db", "q"]},
            ...
        ]}

    Este protocolo de descoberta é provisório — o formato exato dos
    filtros (campos, nomes) deve ser acordado com o firmware assim que
    ele estiver disponível para testes reais. Por ora, o software só
    define o contrato mínimo: uma lista de filtros, cada um com id,
    nome de exibição e a lista de parâmetros que aceita.

    Modo simulado:
        Use port=MOCK_PORT (ou port="MOCK") para simular o envio sem
        precisar de hardware físico conectado. Nesse modo, nada é
        escrito de fato em uma porta serial — o payload é apenas
        logado, o que permite testar todo o fluxo da GUI sem a placa.
        No caso da descoberta de filtros, uma lista de filtros de
        exemplo é devolvida, para permitir testar a UI de seleção
        sem depender do firmware real.
    """

    BAUDRATE: int = 115_200
    TIMEOUT_S: float = 2.0

    # Filtros de exemplo devolvidos em modo MOCK, só para permitir testar
    # a UI de seleção de filtros sem hardware/firmware real disponível.
    # Deve ser substituído pela lista real assim que o firmware existir.
    MOCK_FILTERS: list[dict] = [
        {"id": "low_shelf",  "name": "Low Shelf (Graves)",  "params": ["freq_hz", "gain_db"]},
        {"id": "peaking",    "name": "Peaking (Médios)",    "params": ["freq_hz", "gain_db", "q"]},
        {"id": "high_shelf", "name": "High Shelf (Agudos)", "params": ["freq_hz", "gain_db"]},
        {"id": "noise_gate", "name": "Noise Gate",          "params": ["threshold_db"]},
    ]

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
                self.port,
                self.BAUDRATE,
                timeout=self.TIMEOUT_S,
                write_timeout=self.TIMEOUT_S,
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
        except serial.SerialTimeoutException as exc:
            raise HardwareLinkError(
                f"Timeout ao enviar dados para {self.port}: a placa não "
                f"respondeu a tempo (verifique o cabo/conexão). Detalhe: {exc}"
            ) from exc
        except serial.SerialException as exc:
            raise HardwareLinkError(f"Falha ao enviar dados: {exc}") from exc

    def close(self) -> None:
        if self._conn is not None and self._conn.is_open:
            self._conn.close()
            logger.info("Conexão serial encerrada.")

    def list_filters(
        self,
        progress_cb: Callable[[str], None] | None = None,
    ) -> list[dict]:
        """
        Pergunta à ESP32-S3 quais filtros ela conhece, enviando o comando
        {"cmd": "list_filters"} e aguardando uma linha JSON de resposta
        no formato {"filters": [...]}.

        Em modo MOCK (sem placa conectada), devolve MOCK_FILTERS — uma
        lista de exemplo — para permitir testar a UI de seleção sem
        depender do firmware real.

        Returns:
            Lista de filtros, cada um como
            {"id": str, "name": str, "params": [str, ...]}.

        Raises:
            HardwareLinkError: Se a conexão, o envio, ou a leitura da
                resposta falharem (incluindo timeout ou resposta
                malformada).
        """
        if self.is_mock:
            self._notify(progress_cb, "[Simulado] Consultando filtros conhecidos…")
            logger.info(f"[MOCK] Devolvendo filtros de exemplo: {self.MOCK_FILTERS}")
            self._notify(progress_cb, f"[Simulado] {len(self.MOCK_FILTERS)} filtro(s) recebido(s).")
            return list(self.MOCK_FILTERS)

        if self._conn is None or not self._conn.is_open:
            self._notify(progress_cb, f"Conectando à porta {self.port}…")
            self.connect()

        request = (json.dumps({"cmd": "list_filters"}) + "\n").encode("utf-8")

        try:
            self._notify(progress_cb, "Consultando filtros conhecidos pelo pedal…")
            self._conn.write(request)
            self._conn.flush()

            raw_line = self._conn.readline()
        except serial.SerialTimeoutException as exc:
            raise HardwareLinkError(
                f"Timeout ao consultar filtros em {self.port}: a placa não "
                f"respondeu a tempo. Detalhe: {exc}"
            ) from exc
        except serial.SerialException as exc:
            raise HardwareLinkError(f"Falha ao consultar filtros: {exc}") from exc

        if not raw_line:
            raise HardwareLinkError(
                f"A placa em {self.port} não respondeu ao comando "
                f"'list_filters' dentro do timeout ({self.TIMEOUT_S}s)."
            )

        try:
            response = json.loads(raw_line.decode("utf-8").strip())
            filters = response["filters"]
            if not isinstance(filters, list):
                raise TypeError("campo 'filters' não é uma lista")
        except (json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError) as exc:
            raise HardwareLinkError(
                f"Resposta malformada da placa ao consultar filtros: "
                f"{raw_line!r} ({exc})"
            ) from exc

        logger.info(f"Filtros recebidos da ESP32-S3: {filters}")
        self._notify(progress_cb, f"{len(filters)} filtro(s) recebido(s).")

        return filters

    @staticmethod
    def _notify(cb: Callable[[str], None] | None, msg: str) -> None:
        if cb is not None:
            cb(msg)

    def __enter__(self) -> "ESP32Link":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()