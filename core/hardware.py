from __future__ import annotations

import logging
import struct
import time
from typing import Callable

import serial
from serial.tools import list_ports

logger = logging.getLogger(__name__)

# Porta especial que ativa o modo simulado (sem hardware físico conectado).
MOCK_PORT = "MOCK"

# Byte delimitador de fim de pacote no protocolo COBS.
PACKET_DELIMITER = 0x00

# Protocolo CDC v2 da Placa A (esp32/placaA/include/Protocol.h).
PROTOCOL_VERSION = 2
CMD_HELLO = 0x10
CMD_GET_CAPS = 0x11
CMD_SET_PARAM = 0x13
RSP_ACK = 0x80
RSP_CAPS = 0x81
RSP_ERROR = 0xFF
# Bit 8 do effect_mask do pacote CAPS: convolutor de gabinete IR opcional.
EFFECT_CAP_CAB_SIM = 1 << 8


class HardwareLinkError(Exception):
    """Erro genérico de comunicação com a placa ESP32-S3."""


def cobs_encode(data: bytes) -> bytes:
    """
    Codifica `data` em COBS (Consistent Overhead Byte Stuffing), removendo
    todos os bytes 0x00 do payload e substituindo-os por marcadores de
    comprimento. Réplica em Python do `cobs_encode()` usado no firmware.
    """
    output = bytearray()
    code_index = 0
    output.append(0)
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
    Python do `cobs_decode()` usado no firmware.
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


def crc8(data: bytes) -> int:
    """CRC-8 polinomial 0x07 usado nos quadros CDC v2."""
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ 0x07) & 0xFF if value & 0x80 else (value << 1) & 0xFF
    return value


def encode_control_frame(command: int, sequence: int, payload: bytes = b"") -> bytes:
    if len(payload) > 245:
        raise ValueError("payload CDC excede 245 bytes")
    raw = struct.pack("<BBH", PROTOCOL_VERSION, command, sequence & 0xFFFF) + payload
    return cobs_encode(raw + bytes((crc8(raw),))) + bytes((PACKET_DELIMITER,))


def decode_control_frame(frame: bytes) -> tuple[int, int, bytes]:
    if not frame or frame[-1] != PACKET_DELIMITER:
        raise ValueError("quadro CDC sem terminador")
    raw = cobs_decode(frame[:-1])
    if len(raw) < 5 or crc8(raw[:-1]) != raw[-1]:
        raise ValueError("CRC CDC inválido")
    version, kind, sequence = struct.unpack_from("<BBH", raw)
    if version != PROTOCOL_VERSION:
        raise ValueError(f"versão CDC incompatível: {version}")
    return kind, sequence, raw[4:-1]


class PedalState:
    """
    Espelha a struct C++ `PedalState` (140 bytes empacotados, __attribute__((packed))).

    Layout de memória:
        1.  Noise Gate:     uint8_t, float (5 bytes)
        2.  Compressor:     uint8_t, float, float, float (13 bytes)
        3.  Auto-Wah:       uint8_t, float, float, float (13 bytes)
        4.  Overdrive:      uint8_t, float, float, float (13 bytes)
        5.  Equalizador 4B: uint8_t, float, float, float, float (17 bytes)
        6.  Modulação:      uint8_t, float, float, float (13 bytes)
        7.  Tape Delay:     uint8_t, uint32_t, float, float (13 bytes)
        8.  Reverb Plate:   uint8_t, float, float, float (13 bytes)
        9.  Cab Sim:        uint8_t, uint8_t (2 bytes)
        10. Bitcrusher:     uint8_t, uint8_t, uint8_t, float (7 bytes)
        11. Tremolo:        uint8_t, float, float, uint8_t, float (14 bytes)
        12. Phaser:         uint8_t, float, float, float, float (17 bytes)
        Total: 140 bytes.
    """

    STRUCT_FORMAT = "<BfBfffBfffBfffBffffBfffBIffBfffBBBBBfBffBfBffff"
    SIZE = struct.calcsize(STRUCT_FORMAT)  # 140 bytes

    def __init__(
        self,
        gate_active: bool = True,
        gate_threshold: float = 0.005,
        comp_active: bool = False,
        comp_threshold: float = 0.4,
        comp_ratio: float = 3.0,
        comp_makeup_gain: float = 1.0,
        wah_active: bool = False,
        wah_sensitivity: float = 0.5,
        wah_base_freq: float = 350.0,
        wah_resonance: float = 0.6,
        dist_active: bool = False,
        dist_drive: float = 2.0,
        dist_tone: float = 0.5,
        dist_level: float = 0.8,
        eq_active: bool = False,
        eq_low_gain: float = 0.0,
        eq_mid1_gain: float = 0.0,
        eq_mid2_gain: float = 0.0,
        eq_high_gain: float = 0.0,
        mod_active: bool = False,
        mod_rate_hz: float = 1.5,
        mod_depth: float = 0.6,
        mod_mix: float = 0.5,
        delay_active: bool = False,
        delay_time_samples: int = 15435,  # 350 ms @ 44100 Hz
        delay_feedback: float = 0.4,
        delay_mix: float = 0.3,
        reverb_active: bool = False,
        reverb_decay: float = 0.5,
        reverb_damping: float = 0.3,
        reverb_mix: float = 0.25,
        cab_active: bool = False,
        cab_index: int = 0,
        bitcrusher_active: bool = False,
        bitcrusher_bits: int = 8,
        bitcrusher_hold: int = 4,
        bitcrusher_mix: float = 0.5,
        tremolo_active: bool = False,
        tremolo_rate_hz: float = 4.0,
        tremolo_depth: float = 0.5,
        tremolo_shape: int = 0,
        tremolo_mix: float = 1.0,
        phaser_active: bool = False,
        phaser_rate_hz: float = 0.6,
        phaser_depth: float = 0.7,
        phaser_feedback: float = 0.3,
        phaser_mix: float = 0.5,
    ) -> None:
        self.gate_active = gate_active
        self.gate_threshold = gate_threshold
        self.comp_active = comp_active
        self.comp_threshold = comp_threshold
        self.comp_ratio = comp_ratio
        self.comp_makeup_gain = comp_makeup_gain
        self.wah_active = wah_active
        self.wah_sensitivity = wah_sensitivity
        self.wah_base_freq = wah_base_freq
        self.wah_resonance = wah_resonance
        self.dist_active = dist_active
        self.dist_drive = dist_drive
        self.dist_tone = dist_tone
        self.dist_level = dist_level
        self.eq_active = eq_active
        self.eq_low_gain = eq_low_gain
        self.eq_mid1_gain = eq_mid1_gain
        self.eq_mid2_gain = eq_mid2_gain
        self.eq_high_gain = eq_high_gain
        self.mod_active = mod_active
        self.mod_rate_hz = mod_rate_hz
        self.mod_depth = mod_depth
        self.mod_mix = mod_mix
        self.delay_active = delay_active
        self.delay_time_samples = delay_time_samples
        self.delay_feedback = delay_feedback
        self.delay_mix = delay_mix
        self.reverb_active = reverb_active
        self.reverb_decay = reverb_decay
        self.reverb_damping = reverb_damping
        self.reverb_mix = reverb_mix
        self.cab_active = cab_active
        self.cab_index = cab_index
        self.bitcrusher_active = bitcrusher_active
        self.bitcrusher_bits = bitcrusher_bits
        self.bitcrusher_hold = bitcrusher_hold
        self.bitcrusher_mix = bitcrusher_mix
        self.tremolo_active = tremolo_active
        self.tremolo_rate_hz = tremolo_rate_hz
        self.tremolo_depth = tremolo_depth
        self.tremolo_shape = tremolo_shape
        self.tremolo_mix = tremolo_mix
        self.phaser_active = phaser_active
        self.phaser_rate_hz = phaser_rate_hz
        self.phaser_depth = phaser_depth
        self.phaser_feedback = phaser_feedback
        self.phaser_mix = phaser_mix

    def pack(self) -> bytes:
        """Serializa exatamente os 140 bytes esperados pela ESP32-S3."""
        return struct.pack(
            self.STRUCT_FORMAT,
            int(self.gate_active), float(self.gate_threshold),
            int(self.comp_active), float(self.comp_threshold), float(self.comp_ratio), float(self.comp_makeup_gain),
            int(self.wah_active), float(self.wah_sensitivity), float(self.wah_base_freq), float(self.wah_resonance),
            int(self.dist_active), float(self.dist_drive), float(self.dist_tone), float(self.dist_level),
            int(self.eq_active), float(self.eq_low_gain), float(self.eq_mid1_gain), float(self.eq_mid2_gain), float(self.eq_high_gain),
            int(self.mod_active), float(self.mod_rate_hz), float(self.mod_depth), float(self.mod_mix),
            int(self.delay_active), int(self.delay_time_samples), float(self.delay_feedback), float(self.delay_mix),
            int(self.reverb_active), float(self.reverb_decay), float(self.reverb_damping), float(self.reverb_mix),
            int(self.cab_active), int(self.cab_index),
            int(self.bitcrusher_active), int(self.bitcrusher_bits), int(self.bitcrusher_hold), float(self.bitcrusher_mix),
            int(self.tremolo_active), float(self.tremolo_rate_hz), float(self.tremolo_depth), int(self.tremolo_shape), float(self.tremolo_mix),
            int(self.phaser_active), float(self.phaser_rate_hz), float(self.phaser_depth), float(self.phaser_feedback), float(self.phaser_mix),
        )

    @classmethod
    def unpack(cls, data: bytes) -> "PedalState":
        """Desserializa 140 bytes de volta para uma instância de PedalState."""
        if len(data) != cls.SIZE:
            raise ValueError(
                f"Tamanho de pacote incompatível: recebido {len(data)} bytes, esperado {cls.SIZE}."
            )
        f = struct.unpack(cls.STRUCT_FORMAT, data)
        return cls(
            gate_active=bool(f[0]), gate_threshold=f[1],
            comp_active=bool(f[2]), comp_threshold=f[3], comp_ratio=f[4], comp_makeup_gain=f[5],
            wah_active=bool(f[6]), wah_sensitivity=f[7], wah_base_freq=f[8], wah_resonance=f[9],
            dist_active=bool(f[10]), dist_drive=f[11], dist_tone=f[12], dist_level=f[13],
            eq_active=bool(f[14]), eq_low_gain=f[15], eq_mid1_gain=f[16], eq_mid2_gain=f[17], eq_high_gain=f[18],
            mod_active=bool(f[19]), mod_rate_hz=f[20], mod_depth=f[21], mod_mix=f[22],
            delay_active=bool(f[23]), delay_time_samples=f[24], delay_feedback=f[25], delay_mix=f[26],
            reverb_active=bool(f[27]), reverb_decay=f[28], reverb_damping=f[29], reverb_mix=f[30],
            cab_active=bool(f[31]), cab_index=f[32],
            bitcrusher_active=bool(f[33]), bitcrusher_bits=f[34], bitcrusher_hold=f[35], bitcrusher_mix=f[36],
            tremolo_active=bool(f[37]), tremolo_rate_hz=f[38], tremolo_depth=f[39], tremolo_shape=f[40], tremolo_mix=f[41],
            phaser_active=bool(f[42]), phaser_rate_hz=f[43], phaser_depth=f[44], phaser_feedback=f[45], phaser_mix=f[46],
        )

    def __repr__(self) -> str:
        return (
            f"PedalState(Gate={'ON' if self.gate_active else 'OFF'}, "
            f"Comp={'ON' if self.comp_active else 'OFF'}, "
            f"Wah={'ON' if self.wah_active else 'OFF'}, "
            f"Drive={'ON' if self.dist_active else 'OFF'}, "
            f"EQ={'ON' if self.eq_active else 'OFF'}, "
            f"Mod={'ON' if self.mod_active else 'OFF'}, "
            f"Delay={'ON' if self.delay_active else 'OFF'}, "
            f"Reverb={'ON' if self.reverb_active else 'OFF'}, "
            f"Bitcrusher={'ON' if self.bitcrusher_active else 'OFF'}, "
            f"Tremolo={'ON' if self.tremolo_active else 'OFF'}, "
            f"Phaser={'ON' if self.phaser_active else 'OFF'})"
        )


class ESP32Link:
    BAUDRATE: int = 115_200
    TIMEOUT_S: float = 2.0
    BOOT_DELAY_S: float = 2.0

    def __init__(self, port: str | None = None) -> None:
        self.port = port or self._autodetect_port()
        self.is_mock = self.port == MOCK_PORT
        self._conn: serial.Serial | None = None

    @staticmethod
    def _autodetect_port() -> str:
        ports = list(list_ports.comports())
        # VID/PID do dispositivo composto UAC + CDC do firmware atual.
        candidates = [p.device for p in ports if p.vid == 0x303A and p.pid == 0x81A1]
        if not candidates:
            candidates = [
                p.device for p in ports
                if any(keyword in " ".join(
                    (p.description or ""), (p.product or ""), (p.manufacturer or "")
                ).upper() for keyword in ("ESP32", "PROCESSED AUDIO", "PEDAL"))
            ]
        if not candidates:
            logger.warning("Nenhuma porta serial detectada. Usando modo simulado (MOCK).")
            return MOCK_PORT
        return candidates[0]

    @staticmethod
    def list_available_ports() -> list[str]:
        return [p.device for p in list_ports.comports()]

    def connect(self) -> None:
        if self.is_mock:
            logger.info("[MOCK] Conexão simulada ativa.")
            return

        try:
            self._conn = serial.Serial(
                self.port,
                self.BAUDRATE,
                timeout=self.TIMEOUT_S,
                write_timeout=self.TIMEOUT_S,
            )
            # A CDC nativa do ESP32-S3 não usa DTR/RTS para reset. Mantê-los
            # baixos evita que abrir a porta de controle provoque uma
            # reconexão USB da UAC em hosts que alternam essas linhas.
            try:
                self._conn.dtr = False
                self._conn.rts = False
            except serial.SerialException:
                logger.debug("Não foi possível ajustar DTR/RTS da CDC", exc_info=True)
            time.sleep(self.BOOT_DELAY_S)
            self._conn.reset_input_buffer()
            logger.info(f"Conectado à ESP32-S3 na porta {self.port}")
        except serial.SerialException as exc:
            raise HardwareLinkError(f"Falha ao abrir {self.port}: {exc}") from exc

    def send_state(
        self,
        state: PedalState,
        progress_cb: Callable[[str], None] | None = None,
    ) -> None:
        if self.is_mock:
            self._notify(progress_cb, "[Simulado] Conectando…")
            self._notify(progress_cb, f"[Simulado] Enviando: {state!r}")
            logger.info("[MOCK] Estado de 140 bytes validado localmente (CDC v2 não conectado)")
            self._notify(progress_cb, "[Simulado] Envio concluído.")
            return

        if self._conn is None or not self._conn.is_open:
            self._notify(progress_cb, f"Conectando à porta {self.port}…")
            self.connect()

        try:
            caps = self._get_caps()
            if caps[0] != 44100 or caps[3] != 1 or caps[9] != PedalState.SIZE:
                raise HardwareLinkError(
                    "A Placa A anunciou capacidades incompatíveis "
                    f"(taxa={caps[0]}, canais={caps[3]}, estado={caps[9]})."
                )

            cab_supported = bool(int(caps[8]) & EFFECT_CAP_CAB_SIM)

            # O CDC atual recebe alterações absolutas por parâmetro. O antigo
            # pacote COBS com os 140 bytes de PedalState não é mais aceito.
            parameters = [
                (0, 0, state.gate_active), (0, 1, state.gate_threshold),
                (1, 0, state.comp_active), (1, 1, state.comp_threshold),
                (1, 2, state.comp_ratio), (1, 3, state.comp_makeup_gain),
                (2, 0, state.wah_active), (2, 1, state.wah_sensitivity),
                (2, 2, state.wah_base_freq), (2, 3, state.wah_resonance),
                (3, 0, state.dist_active), (3, 1, state.dist_drive),
                (3, 2, state.dist_tone), (3, 3, state.dist_level),
                (4, 0, state.eq_active), (4, 1, state.eq_low_gain),
                (4, 2, state.eq_mid1_gain), (4, 3, state.eq_mid2_gain),
                (4, 4, state.eq_high_gain),
                (5, 0, state.mod_active), (5, 1, state.mod_rate_hz),
                (5, 2, state.mod_depth), (5, 3, state.mod_mix),
                (6, 0, state.delay_active), (6, 1, state.delay_time_samples),
                (6, 2, state.delay_feedback), (6, 3, state.delay_mix),
                (7, 0, state.reverb_active), (7, 1, state.reverb_decay),
                (7, 2, state.reverb_damping), (7, 3, state.reverb_mix),
                (9, 0, state.bitcrusher_active), (9, 1, state.bitcrusher_bits),
                (9, 2, state.bitcrusher_hold), (9, 3, state.bitcrusher_mix),
                (10, 0, state.tremolo_active), (10, 1, state.tremolo_rate_hz),
                (10, 2, state.tremolo_depth), (10, 3, state.tremolo_shape),
                (10, 4, state.tremolo_mix),
                (11, 0, state.phaser_active), (11, 1, state.phaser_rate_hz),
                (11, 2, state.phaser_depth), (11, 3, state.phaser_feedback),
                (11, 4, state.phaser_mix),
            ]
            if cab_supported:
                # O efeito 8 mantém os campos históricos do PedalState e só
                # é enviado quando a imagem anuncia o motor IR no CAPS.
                parameters.extend([
                    (8, 0, state.cab_active),
                    (8, 1, state.cab_index),
                ])
            elif state.cab_active:
                self._notify(
                    progress_cb,
                    "Aviso: o cab sim foi solicitado, mas está desativado no build padrão da Placa A.",
                )
            self._notify(progress_cb, "Enviando parâmetros pela CDC v2…")
            for index, (effect, parameter, value) in enumerate(parameters, 1):
                self._set_param(effect, parameter, float(value))
                if index % 8 == 0 or index == len(parameters):
                    self._notify(progress_cb, f"Parâmetros enviados: {index}/{len(parameters)}")
            self._notify(progress_cb, "Envio concluído.")
        except serial.SerialTimeoutException as exc:
            raise HardwareLinkError(f"Timeout ao comunicar com {self.port}: {exc}") from exc
        except serial.SerialException as exc:
            raise HardwareLinkError(f"Falha na transmissão serial: {exc}") from exc

    def _next_sequence(self) -> int:
        sequence = getattr(self, "_sequence", 1)
        self._sequence = (sequence + 1) & 0xFFFF or 1
        return sequence

    def _request(
        self,
        command: int,
        payload: bytes = b"",
        response_type: int | None = None,
        retries: int = 3,
    ) -> bytes:
        if self._conn is None or not self._conn.is_open:
            raise HardwareLinkError("A conexão CDC não está aberta")
        sequence = self._next_sequence()
        frame = encode_control_frame(command, sequence, payload)
        for attempt in range(retries):
            try:
                self._conn.write(frame)
                self._conn.flush()
            except serial.SerialException as exc:
                raise HardwareLinkError(f"Falha ao enviar comando CDC: {exc}") from exc
            deadline = time.monotonic() + self.TIMEOUT_S
            while time.monotonic() < deadline:
                encoded = self._conn.read_until(bytes((PACKET_DELIMITER,)))
                if not encoded:
                    continue
                try:
                    kind, received_sequence, response = decode_control_frame(encoded)
                except ValueError:
                    continue
                if received_sequence != sequence:
                    continue
                if kind == RSP_ERROR:
                    status = response[0] if response else 0xFF
                    raise HardwareLinkError(f"A Placa A rejeitou o comando CDC (status {status}).")
                if response_type is None or kind == response_type:
                    return response
            if attempt + 1 < retries:
                logger.warning("Sem resposta CDC para sequência %d; repetindo", sequence)
        raise HardwareLinkError(f"Sem resposta CDC para sequência {sequence}.")

    def _get_caps(self) -> tuple:
        data = self._request(CMD_HELLO, response_type=RSP_CAPS)
        expected = struct.calcsize("<I7BHH")
        if len(data) != expected:
            raise HardwareLinkError(f"CAPS com tamanho inesperado: {len(data)} (esperado {expected}).")
        return struct.unpack("<I7BHH", data)

    def _set_param(self, effect: int, parameter: int, value: float) -> None:
        self._request(
            CMD_SET_PARAM,
            struct.pack("<BBf", effect, parameter, value),
            response_type=RSP_ACK,
        )

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
