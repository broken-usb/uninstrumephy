from pathlib import Path
import logging

import torch
import soundfile as sf

from demucs.pretrained import get_model
from demucs.apply import apply_model
from demucs.audio import AudioFile

logger = logging.getLogger(__name__)

class AudioSeparator:

    _cached_model = None

    def __init__(self, output_dir="output"):

        self.output_dir = Path(output_dir)

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        self.model_name = "htdemucs_6s"

        self.device = (
            "cuda"
            if torch.cuda.is_available()
            else "cpu"
        )

        logger.info(f"Device selecionado: {self.device}")

        if AudioSeparator._cached_model is None:

            logger.info(
                f"Carregando modelo Demucs: {self.model_name}"
            )

            model = get_model(self.model_name)

            model.to(self.device)
            model.eval()

            AudioSeparator._cached_model = model

        self.model = AudioSeparator._cached_model

    def extract_guitar(self, audio_path):

        audio_path = Path(audio_path)

        if not audio_path.exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {audio_path}"
            )

        logger.info(f"Processando áudio: {audio_path}")

        base_name = audio_path.stem

        out_dir = (
            self.output_dir
            / self.model_name
            / base_name
        )

        out_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        guitar_path = out_dir / "guitar.wav"

        if guitar_path.exists():

            logger.info(
                "Stem já existe. Reutilizando cache."
            )

            return str(guitar_path.resolve())

        wav = AudioFile(str(audio_path)).read(
            streams=0,
            samplerate=self.model.samplerate,
            channels=self.model.audio_channels
        )

        wav = torch.tensor(
            wav,
            dtype=torch.float32,
            device=self.device
        )

        if wav.dim() == 2:
            wav = wav.unsqueeze(0)

        logger.info("Executando separação Demucs...")

        with torch.no_grad():

            sources = apply_model(
                self.model,
                wav,
                device=self.device
            )

        sources = sources[0]

        stems = self.model.sources

        logger.info("Salvando stems...")

        for source, stem_name in zip(sources, stems):

            out_path = out_dir / f"{stem_name}.wav"

            audio = (
                source
                .detach()
                .cpu()
                .numpy()
                .T
            )

            sf.write(
                str(out_path),
                audio,
                self.model.samplerate
            )

            logger.info(
                f"Stem salva: {out_path}"
            )

        logger.info("Separação concluída.")

        return str(guitar_path.resolve())