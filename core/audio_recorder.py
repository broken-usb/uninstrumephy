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


def list_output_devices() -> list[dict]:
    """Lista as saídas compatíveis com o monitoramento ao vivo.

    O UAC da Placa A é somente de captura. O áudio é reproduzido pelo
    computador, portanto esta lista contém a interface/saída que o usuário
    quer escutar (fones, caixas de som ou outra interface USB).
    """
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        output_devs = []
        for idx, d in enumerate(devices):
            if d.get("max_output_channels", 0) > 0:
                name = d.get("name", f"Saída {idx}")
                output_devs.append({
                    "index": idx,
                    "name": name,
                    "channels": d.get("max_output_channels", 1),
                    "default_samplerate": int(d.get("default_samplerate", 44100)),
                })
        return output_devs
    except Exception as exc:
        logger.warning("Erro ao listar saídas com sounddevice: %s", exc)
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


def get_default_output_device_index() -> Optional[int]:
    """Retorna a saída padrão do PortAudio, se houver uma disponível."""
    try:
        import sounddevice as sd
        default_out = sd.default.device[1]
        if default_out is not None and default_out >= 0:
            return int(default_out)
        devices = list_output_devices()
        return devices[0]["index"] if devices else None
    except Exception:
        return None


class LiveMonitorThread(QThread):
    """Liga a captura UAC da pedaleira diretamente à saída do computador.

    O callback de PortAudio copia uma entrada mono para a saída mono e nunca
    bloqueia em fila. Isso mantém a reprodução independente da gravação em
    arquivo e reduz a chance de estalos causados pelo aplicativo.
    """

    error = pyqtSignal(str)
    status_msg = pyqtSignal(str)
    level_meter = pyqtSignal(float)

    def __init__(
        self,
        input_device_index: Optional[int],
        output_device_index: Optional[int],
        sample_rate: int = 44100,
        input_name_hint: str | None = None,
        output_name_hint: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.input_device_index = input_device_index
        self.output_device_index = output_device_index
        self.sample_rate = sample_rate
        self.input_name_hint = input_name_hint or ""
        self.output_name_hint = output_name_hint or ""
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    @staticmethod
    def _find_device_index(sd, name_hint: str, input_device: bool) -> Optional[int]:
        """Reobtém o índice após hotplug ou reset da USB.

        Índices do PortAudio não são estáveis quando uma placa USB é
        reconectada. O nome ALSA contém ``ESP32-S3 Processed Audio`` e é
        usado como identidade estável para a tentativa de reabertura.
        """
        if not name_hint:
            return None
        # O sufixo ``(hw:N,0)`` pode mudar após reconexão; use o nome do
        # produto antes dos detalhes ALSA.
        needle = name_hint.split(":", 1)[0].strip().lower()
        for index, info in enumerate(sd.query_devices()):
            channels = info.get("max_input_channels", 0) if input_device else info.get("max_output_channels", 0)
            if channels and needle in info.get("name", "").lower():
                return index
        return None

    def run(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            self.error.emit(
                "A biblioteca 'sounddevice' não foi encontrada. "
                "Instale-a no ambiente do aplicativo."
            )
            return

        meter_counter = 0
        status_counter = 0
        last_status = ""

        def callback(indata, outdata, frames, time_info, status):
            nonlocal meter_counter, status_counter, last_status
            if status:
                flags = [
                    name.replace("_", " ")
                    for name in (
                        "input_underflow", "input_overflow",
                        "output_underflow", "output_overflow",
                    )
                    if getattr(status, name, False)
                ]
                warning = ", ".join(flags) if flags else str(status)
                # Um host sobrecarregado pode marcar muitos callbacks. O
                # primeiro aviso é imediato; repetições são limitadas para
                # não transformar a própria UI em outra fonte de latência.
                if warning != last_status or status_counter >= 100:
                    logger.warning("PortAudio monitor: %s", warning)
                    self.status_msg.emit(f"Aviso PortAudio: {warning}")
                    last_status = warning
                    status_counter = 0
                status_counter += 1
            outdata.fill(0)
            if indata is None or indata.size == 0:
                return
            source = indata[:, 0] if indata.ndim > 1 else indata
            count = min(len(source), len(outdata))
            if outdata.ndim > 1:
                # A entrada é mono; duplique-a para os canais da saída para
                # que fones estéreo não reproduzam o sinal apenas à esquerda.
                outdata[:count, :] = source[:count, None]
            else:
                outdata[:count] = source[:count]
            peak = float(np.max(np.abs(source[:count]))) if count else 0.0
            db = 20.0 * np.log10(max(1e-5, peak))
            # O áudio permanece no callback; a atualização visual é reduzida
            # para não introduzir trabalho Qt a cada bloco nativo.
            meter_counter += 1
            if meter_counter >= 5:
                meter_counter = 0
                self.level_meter.emit(float(np.clip((db + 50.0) / 50.0 * 100.0, 0.0, 100.0)))

        try:
            output_channels = 1
            if self.output_device_index is not None:
                output_info = sd.query_devices(self.output_device_index)
                output_channels = max(1, min(2, int(output_info.get("max_output_channels", 1))))
            if self.input_device_index is not None:
                input_error = None
                # Após uma alteração CDC a placa pode reenumerar a UAC e o
                # índice anterior deixa de existir por alguns segundos.
                for _attempt in range(40):
                    if self._stop_requested:
                        return
                    if _attempt in (0, 8, 20):
                        self.status_msg.emit(
                            "Aguardando a UAC da Placa A terminar a enumeração…"
                        )
                    if self.input_name_hint:
                        refreshed = self._find_device_index(sd, self.input_name_hint, True)
                        if refreshed is None:
                            input_error = RuntimeError("dispositivo UAC ainda não enumerado")
                            time.sleep(0.25)
                            continue
                        self.input_device_index = refreshed
                    try:
                        sd.check_input_settings(
                            device=self.input_device_index,
                            samplerate=self.sample_rate,
                            channels=1,
                            dtype="float32",
                        )
                        input_error = None
                        break
                    except Exception as exc:
                        input_error = exc
                        # -9985 (Device unavailable) inclui a janela de
                        # reconexão/hotplug; dê tempo à ALSA para atualizar.
                        if "Device unavailable" not in str(exc) and "No such device" not in str(exc):
                            break
                        time.sleep(0.25)
                if input_error is not None:
                    input_name = self.input_name_hint or "entrada selecionada"
                    busy_hint = " Feche outra gravação/arecord que possa estar usando a UAC." if "Device unavailable" in str(input_error) else ""
                    raise RuntimeError(
                        f"A entrada '{input_name}' ficou indisponível ou não aceita "
                        f"{self.sample_rate} Hz. Desconecte/reconecte a USB da Placa A, "
                        "aguarde a enumeração e use Atualizar."
                        f"{busy_hint} Detalhe: "
                        f"{input_error}"
                    ) from input_error
            if self.output_device_index is not None:
                try:
                    sd.check_output_settings(
                        device=self.output_device_index,
                        samplerate=self.sample_rate,
                        channels=output_channels,
                        dtype="float32",
                    )
                except Exception as exc:
                    output_name = sd.query_devices(self.output_device_index).get("name", "saída")
                    raise RuntimeError(
                        f"A saída '{output_name}' não aceita {self.sample_rate} Hz. "
                        "Selecione outra saída ou ajuste a taxa no sistema. "
                        f"Detalhe: {exc}"
                    ) from exc

            self.status_msg.emit("Monitoramento ao vivo ativo — áudio processado da Placa A")
            with sd.Stream(
                device=(self.input_device_index, self.output_device_index),
                samplerate=self.sample_rate,
                channels=(1, output_channels),
                dtype="float32",
                blocksize=0,
                latency=("low", "low"),
                callback=callback,
            ) as stream:
                self.status_msg.emit(
                    "Monitoramento ativo — latência PortAudio: "
                    f"entrada {stream.input_latency * 1000.0:.1f} ms / "
                    f"saída {stream.output_latency * 1000.0:.1f} ms"
                )
                while not self._stop_requested:
                    self.msleep(50)
            self.status_msg.emit("Monitoramento ao vivo parado")
        except Exception as exc:
            logger.exception("Erro durante o monitoramento ao vivo")
            self.error.emit(
                "Não foi possível reproduzir a Placa A em tempo real. "
                "Confirme que a entrada UAC e a saída aceitam 44,1 kHz e que não estão em uso: "
                f"{exc}"
            )


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
        dropped_blocks = 0
        self.output_filepath.parent.mkdir(parents=True, exist_ok=True)

        def callback(indata, frames, time_info, status):
            nonlocal dropped_blocks
            if status:
                logger.debug(f"PortAudio status: {status}")
            try:
                audio_queue.put_nowait(indata.copy())
            except queue.Full:
                # Nunca bloquear o callback de áudio: descartar o bloco mais
                # recente é preferível a provocar uma perda em cascata.
                dropped_blocks += 1

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
            if dropped_blocks:
                self.status_msg.emit(
                    f"Aviso: {dropped_blocks} blocos de captura foram descartados pelo aplicativo."
                )
            # PCM_24 preserva a resolução anunciada pela UAC da Placa A.
            sf.write(str(self.output_filepath), full_audio, self.sample_rate, subtype="PCM_24")

            logger.info(f"Áudio de entrada gravado com sucesso: {self.output_filepath} ({len(full_audio)} amostras)")
            self.finished_recording.emit(str(self.output_filepath.resolve()))

        except Exception as exc:
            logger.exception("Erro durante a captura de áudio.")
            self.error.emit(f"Falha ao acessar o dispositivo de áudio: {exc}")
