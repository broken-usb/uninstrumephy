"""Protocolo CDC v2 da Placa A (core/hardware.py), com um firmware simulado."""

import struct
import time

import pytest

from core import hardware as hw


def test_crc8_vetor_de_referencia():
    # CRC-8 polinômio 0x07, valor de referência para "123456789"
    assert hw.crc8(b"123456789") == 0xF4


def test_quadro_ida_e_volta():
    payload = struct.pack("<BBf", 3, 1, 0.75)
    frame = hw.encode_control_frame(hw.CMD_SET_PARAM, 0x1234, payload)
    assert frame[-1] == 0 and 0 not in frame[:-1]
    assert hw.decode_control_frame(frame) == (hw.CMD_SET_PARAM, 0x1234, payload)


def test_crc_invalido_e_rejeitado():
    frame = bytearray(hw.encode_control_frame(hw.CMD_HELLO, 1))
    frame[2] ^= 0x01
    with pytest.raises(ValueError):
        hw.decode_control_frame(bytes(frame))


def test_pedal_state_tem_140_bytes():
    assert hw.PedalState.SIZE == 140


class FakeFirmware:
    """Responde HELLO com CAPS e SET_PARAM com ACK, como a Placa A."""

    def __init__(self, effect_mask=0, rate=44100, drop_first=False):
        self.is_open = True
        self.effect_mask, self.rate, self.drop_first = effect_mask, rate, drop_first
        self.rx, self.params, self.writes = [], [], 0

    @staticmethod
    def _frame(kind, seq, payload=b""):
        raw = struct.pack("<BBH", hw.PROTOCOL_VERSION, kind, seq) + payload
        return hw.cobs_encode(raw + bytes((hw.crc8(raw),))) + b"\x00"

    def write(self, data):
        self.writes += 1
        kind, seq, payload = hw.decode_control_frame(data)
        if self.drop_first and self.writes == 1:
            return len(data)
        if kind == hw.CMD_HELLO:
            caps = struct.pack("<I7BHH", self.rate, 24, 32, 1, 0, 0, 0, 0, self.effect_mask, 140)
            self.rx.append(self._frame(hw.RSP_CAPS, seq, caps))
        elif kind == hw.CMD_SET_PARAM:
            self.params.append(struct.unpack("<BBf", payload))
            self.rx.append(self._frame(hw.RSP_ACK, seq))
        return len(data)

    def read_until(self, _delimiter):
        if self.rx:
            return self.rx.pop(0)
        time.sleep(0.005)
        return b""

    def flush(self):
        pass

    def reset_input_buffer(self):
        pass

    def close(self):
        self.is_open = False


def _link(fw):
    link = hw.ESP32Link(port="/dev/fake")
    link._conn = fw
    link.TIMEOUT_S = 0.2
    return link


def test_envio_sem_cab_sim():
    fw, msgs = FakeFirmware(), []
    state = hw.PedalState()
    state.cab_active = True
    _link(fw).send_state(state, progress_cb=msgs.append)
    assert len(fw.params) == 45
    assert all(effect != 8 for effect, _, _ in fw.params)
    assert any("cab sim" in m for m in msgs)


def test_envio_com_cab_sim_anunciado():
    fw = FakeFirmware(effect_mask=hw.EFFECT_CAP_CAB_SIM)
    _link(fw).send_state(hw.PedalState())
    assert len(fw.params) == 47
    assert any(effect == 8 for effect, _, _ in fw.params)


def test_caps_incompativeis_geram_erro():
    with pytest.raises(hw.HardwareLinkError):
        _link(FakeFirmware(rate=48000)).send_state(hw.PedalState())


def test_comando_sem_resposta_e_repetido():
    fw = FakeFirmware(drop_first=True)
    _link(fw).send_state(hw.PedalState())
    assert len(fw.params) == 45
    assert fw.writes == 47  # HELLO perdido + HELLO repetido + 45 parâmetros
