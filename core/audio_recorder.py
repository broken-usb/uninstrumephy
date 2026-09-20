from __future__ import annotations

import logging
import queue
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


def list_input_devices() -> list[dict]:
    """
    Lista todos os dispositivos de entrada de áudio do sistema operacional,
    identificando automaticamente se algum deles pertence à pedaleira ESP32-S3.
    """
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devs = []
        for idx, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0:
                name = d.get("name", f"Dispositivo {idx}")
                # Identifica descritores do firmware TinyUSB da Placa A
                is_esp = any(k in name.lower() for k in ("esp32", "pedal", "processed audio", "uac"))
                input_devs.append({
                    "index": idx,
                    "name": name,
                    "channels": d.get("max_input_channels", 1),
                    "default_samplerate": int(d.get("default_samplerate", 44100)),
                    "is_esp32": is_esp
                })
        return input_devs
    except Exception as exc:
        logger.warning(f"Erro ao listar dispositivos com sounddevice: {exc}")
        return []


def get_default_input_device_index() -> Optional[int]:
    """
    Retorna o índice da ESP32-S3 se conectada; caso contrário,
    retorna o dispositivo de entrada padrão do sistema.
    """
    try:
        import sounddevice as sd
        devices = list_input_devices()
        for d in devices:
            if d["is_esp32"]:
                return d["index"]
        default_in = sd.default.device[0]
        if default_in is not None and default_in >= 0:
            return int(default_in)
        if devices:
            return devices[0]["index"]
    except Exception:
        pass
    return None


class AudioRecorderThread(QThread):
    """
    Thread de captura assíncrona de áudio via sounddevice, transmitindo o
    nível de pico (VU meter) em tempo real e gravando o sinal em arquivo WAV.
    """
    progress = pyqtSignal(float, float)      # (tempo_decorrido_s, duracao_total_s)
    level_meter = pyqtSignal(float)          # Nível do VU Meter (0.0 a 100.0 %)
    finished_recording = pyqtSignal(str)     # Caminho do arquivo .wav gerado
    error = pyqtSignal(str)
    status_msg = pyqtSignal(str)

    def __init__(
        self,
        output_filepath: str,
        device_index: Optional[int] = None,
        duration_s: float = 15.0,
        sample_rate: int = 44100,
        channels: int = 1,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.output_filepath = Path(output_filepath)
        self.device_index = device_index
        self.duration_s = duration_s
        self.sample_rate = sample_rate
        self.channels = channels
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            self.error.emit("A biblioteca 'sounddevice' não foi encontrada. Execute: pip install sounddevice")
            return

        audio_queue = queue.Queue(maxsize=256)
        self.output_filepath.parent.mkdir(parents=True, exist_ok=True)

        def callback(indata, frames, time_info, status):
            if status:
                logger.debug(f"PortAudio status: {status}")
            audio_queue.put(indata.copy())

        self.status_msg.emit("Capturando áudio da entrada…")
        start_time = time.monotonic()
        collected_chunks = []

        try:
            with sd.InputStream(
                device=self.device_index,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                blocksize=1024,
                callback=callback,
            ):
                while not self._stop_requested:
                    elapsed = time.monotonic() - start_time
                    self.progress.emit(elapsed, self.duration_s)

                    if self.duration_s > 0 and elapsed >= self.duration_s:
                        break

                    try:
                        chunk = audio_queue.get(timeout=0.08)
                        collected_chunks.append(chunk)

                        # Cálculo de pico logarítmico para o VU meter (-50 dBFS a 0 dBFS)
                        peak = float(np.max(np.abs(chunk)))
                        db = 20.0 * np.log10(max(1e-5, peak))
                        meter_pct = float(np.clip((db + 50.0) / 50.0 * 100.0, 0.0, 100.0))
                        self.level_meter.emit(meter_pct)
                    except queue.Empty:
                        continue

            while not audio_queue.empty():
                try:
                    collected_chunks.append(audio_queue.get_nowait())
                except queue.Empty:
                    break

            if not collected_chunks:
                self.error.emit("Nenhum sinal de áudio foi recebido do dispositivo selecionado.")
                return

            full_audio = np.concatenate(collected_chunks, axis=0)
            if full_audio.ndim == 2 and full_audio.shape[1] == 1:
                full_audio = full_audio[:, 0]

            self.status_msg.emit("Salvando gravação em disco…")
            sf.write(str(self.output_filepath), full_audio, self.sample_rate, subtype="PCM_16")

            logger.info(f"Áudio de entrada gravado com sucesso: {self.output_filepath} ({len(full_audio)} amostras)")
            self.finished_recording.emit(str(self.output_filepath.resolve()))

        except Exception as exc:
            logger.exception("Erro durante a captura de áudio.")
            self.error.emit(f"Falha ao acessar o dispositivo de áudio: {exc}")