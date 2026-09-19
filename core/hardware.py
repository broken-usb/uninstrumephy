from __future__ import annotations

import logging
import struct
import time
from typing import Callable

import serial
from serial.tools import list_ports

logger = logging.getLogger(__name__)

# Porta especial que ativa o modo simulado (sem hardware físico conectado).
# Útil para desenvolver e demonstrar o software antes da placa chegar.
MOCK_PORT = "MOCK"

# Byte delimitador de fim de pacote no protocolo COBS. O COBS garante que
# este valor nunca aparece no meio dos dados codificados, então ele pode
# ser usado com segurança para marcar onde um pacote termina.
PACKET_DELIMITER = 0x00


class HardwareLinkError(Exception):
    """Erro genérico de comunicação com a placa ESP32-S3."""


def cobs_encode(data: bytes) -> bytes:
    """
    Codifica `data` em COBS (Consistent Overhead Byte Stuffing), removendo
    todos os bytes 0x00 do payload e substituindo-os por marcadores de
    comprimento. Réplica em Python do `cobs_encode()` usado no firmware
    (Board B / UI), garantindo compatibilidade byte a byte.

    O resultado NUNCA contém 0x00 internamente — o chamador deve anexar
    um único 0x00 ao final para marcar o fim do pacote na UART.
    """
    output = bytearray()
    code_index = 0
    output.append(0)  # placeholder do primeiro code, preenchido no final do bloco
    code = 1

    for byte in data:
        if byte == 0:
            output[code_index] = code
            code = 1
            code_index = len(output)
            output.append(0)
        else:
            output.append(byte)
            code += 1
            if code == 0xFF:
                output[code_index] = code
                code = 1
                code_index = len(output)
                output.append(0)

    output[code_index] = code
    return bytes(output)


def cobs_decode(data: bytes) -> bytes:
    """
    Decodifica um bloco COBS de volta aos bytes originais. Réplica em
    Python do `cobs_decode()` usado no firmware (Board A / DSP Master).

    Retorna b"" se o bloco estiver malformado (mesmo comportamento do
    `return 0` no código C original).
    """
    output = bytearray()
    read_index = 0
    length = len(data)

    while read_index < length:
        code = data[read_index]
        if read_index + code > length and code != 1:
            return b""
        read_index += 1
        for _ in range(1, code):
            output.append(data[read_index])
            read_index += 1
        if code != 0xFF and read_index != length:
            output.append(0)

    return bytes(output)


class PedalState:
    """
    Espelha em Python a struct C `PedalState` (arquivo PedalState.h,
    compartilhado entre as duas placas ESP32-S3 do pedal). A struct é
    `__attribute__((packed))`, ou seja, sem padding entre os campos —
    o formato abaixo replica exatamente essa disposição de memória.

    Layout (little-endian, 27 bytes total):
        uint8_t  gate_active            (offset  0, 1 byte)
        float    gate_threshold         (offset  1, 4 bytes)
        uint8_t  dist_active            (offset  5, 1 byte)
        float    dist_drive             (offset  6, 4 bytes)
        float    dist_level             (offset 10, 4 bytes)
        uint8_t  delay_active           (offset 14, 1 byte)
        uint32_t delay_time_samples     (offset 15, 4 bytes)
        float    delay_feedback         (offset 19, 4 bytes)
        float    delay_mix              (offset 23, 4 bytes)

    IMPORTANTE: esta struct não possui campos de equalização (bass/mid/
    treble) — o firmware atual só implementa Noise Gate, Overdrive e
    Delay. Um "Equalizador" aparece comentado no código da UI (Board B)
    como efeito futuro ainda não habilitado. Os parâmetros de EQ
    calculados pelo Tone Matching não têm, por ora, um destino no
    protocolo — isso precisa ser resolvido com o time de firmware antes
    de o EQ poder ser efetivamente aplicado no pedal.
    """

    STRUCT_FORMAT = "<BfBffBIff"
    SIZE = struct.calcsize(STRUCT_FORMAT)  # 27 bytes

    def __init__(
        self,
        gate_active: bool = False,
        gate_threshold: float = 0.0,
        dist_active: bool = False,
        dist_drive: float = 1.0,
        dist_level: float = 1.0,
        delay_active: bool = False,
        delay_time_samples: int = 0,
        delay_feedback: float = 0.0,
        delay_mix: float = 0.0,
    ) -> None:
        self.gate_active = gate_active
        self.gate_threshold = gate_threshold
        self.dist_active = dist_active
        self.dist_drive = dist_drive
        self.dist_level = dist_level
        self.delay_active = delay_active
        self.delay_time_samples = delay_time_samples
        self.delay_feedback = delay_feedback
        self.delay_mix = delay_mix

    def pack(self) -> bytes:
        """Serializa para os 27 bytes binários exatos esperados pelo firmware."""
        return struct.pack(
            self.STRUCT_FORMAT,
            int(self.gate_active),
            float(self.gate_threshold),
            int(self.dist_active),
            float(self.dist_drive),
            float(self.dist_level),
            int(self.delay_active),
            int(self.delay_time_samples),
            float(self.delay_feedback),
            float(self.delay_mix),
        )

    @classmethod
    def unpack(cls, data: bytes) -> "PedalState":
        """Desserializa 27 bytes binários de volta para um PedalState."""
        if len(data) != cls.SIZE:
            raise ValueError(
                f"Tamanho inválido para PedalState: recebido {len(data)} "
                f"bytes, esperado {cls.SIZE}."
            )
        fields = struct.unpack(cls.STRUCT_FORMAT, data)
        return cls(
            gate_active=bool(fields[0]),
            gate_threshold=fields[1],
            dist_active=bool(fields[2]),
            dist_drive=fields[3],
            dist_level=fields[4],
            delay_active=bool(fields[5]),
            delay_time_samples=fields[6],
            delay_feedback=fields[7],
            delay_mix=fields[8],
        )

    def __repr__(self) -> str:
        return (
            f"PedalState(gate_active={self.gate_active}, "
            f"gate_threshold={self.gate_threshold}, "
            f"dist_active={self.dist_active}, "
            f"dist_drive={self.dist_drive}, dist_level={self.dist_level}, "
            f"delay_active={self.delay_active}, "
            f"delay_time_samples={self.delay_time_samples}, "
            f"delay_feedback={self.delay_feedback}, "
            f"delay_mix={self.delay_mix})"
        )


class ESP32Link:
    """
    Envia um PedalState para a ESP32-S3 conectada via USB (porta serial),
    usando o protocolo real implementado pelo firmware: a struct é
    serializada em binário (27 bytes, ver PedalState), codificada em
    COBS e terminada por um byte 0x00 que marca o fim do pacote na UART.

    Este protocolo substitui a versão anterior baseada em JSON — o
    firmware real (Board A: DSP Master / Board B: UI) não fala JSON, e
    não expõe um comando de descoberta de filtros: os efeitos disponíveis
    (Noise Gate, Overdrive, Delay) são fixos no firmware.

    Modo simulado:
        Use port=MOCK_PORT (ou port="MOCK") para simular o envio sem
        precisar de hardware físico conectado. Nesse modo, nada é
        escrito de fato em uma porta serial — o pacote COBS resultante é
        apenas logado, o que permite testar o fluxo da GUI sem a placa.
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

    def send_state(
        self,
        state: PedalState,
        progress_cb: Callable[[str], None] | None = None,
    ) -> None:
        """
        Envia um PedalState completo para o pedal: serializa a struct em
        27 bytes binários, codifica em COBS, e transmite seguido do byte
        delimitador 0x00.

        Args:
            state: PedalState com os parâmetros atuais de gate/distortion/delay.
            progress_cb: Callback opcional de progresso, para conectar a
                    um pyqtSignal da UI.

        Raises:
            HardwareLinkError: Se a conexão ou o envio falharem.
        """
        raw = state.pack()
        packet = cobs_encode(raw) + bytes([PACKET_DELIMITER])

        if self.is_mock:
            self._notify(progress_cb, "[Simulado] Conectando…")
            self._notify(progress_cb, f"[Simulado] Enviando: {state!r}")
            logger.info(
                f"[MOCK] PedalState que seria enviado: {state!r} "
                f"({len(raw)} bytes crus, {len(packet)} bytes no pacote COBS)"
            )
            self._notify(progress_cb, "[Simulado] Envio concluído (nenhum hardware real envolvido).")
            return

        if self._conn is None or not self._conn.is_open:
            self._notify(progress_cb, f"Conectando à porta {self.port}…")
            self.connect()

        try:
            self._notify(progress_cb, "Enviando parâmetros…")
            self._conn.write(packet)
            self._conn.flush()
            logger.info(f"PedalState enviado: {state!r} ({len(packet)} bytes no pacote)")
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

    @staticmethod
    def _notify(cb: Callable[[str], None] | None, msg: str) -> None:
        if cb is not None:
            cb(msg)

    def __enter__(self) -> "ESP32Link":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()