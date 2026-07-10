from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Callable

import torch
import soundfile as sf

from demucs.pretrained import get_model
from demucs.apply import apply_model
from demucs.audio import AudioFile

# Logger

logger = logging.getLogger(__name__)

# Classe principal

class AudioSeparator:
    """
    Separa as faixas de um arquivo de áudio usando o modelo Demucs.

    O modelo é carregado uma única vez e reutilizado via cache de classe
    (_cached_model), evitando recarregamentos desnecessários entre chamadas.

    Stems disponíveis no htdemucs_6s:
        guitar, bass, drums, piano, vocals, other
    """

    _cached_model = None

    MODEL_NAME = "htdemucs_6s"
    DEFAULT_STEM = "guitar"

    def __init__(self, output_dir: str = "output") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Device selecionado: {self.device}")

        # Cache global do modelo
        if AudioSeparator._cached_model is None:
            logger.info(f"Carregando modelo Demucs: {self.MODEL_NAME}")
            model = get_model(self.MODEL_NAME)
            model.to(self.device)
            model.eval()
            AudioSeparator._cached_model = model

        self.model = AudioSeparator._cached_model

    # Separação

    def extract_stem(
        self,
        audio_path: str,
        stem_name: str = DEFAULT_STEM,
        progress_cb: Callable[[str], None] | None = None,
    ) -> str:
        """
        Separa todos os stems do arquivo de áudio e retorna o caminho
        do stem solicitado (guitar, bass, drums, piano, vocals ou other).

        O progress_cb, se fornecido, é chamado com strings de status
        intermediárias — ideal para conectar a um pyqtSignal da UI.

        Args:
            audio_path:  Caminho para o arquivo de áudio de entrada.
            stem_name:   Nome do stem desejado (deve existir em model.sources).
            progress_cb: Callback opcional para progresso (str → None).

        Returns:
            Caminho absoluto para o arquivo <stem_name>.wav gerado.

        Raises:
            FileNotFoundError: Se audio_path não existir.
            ValueError: Se stem_name não for suportado pelo modelo carregado.
        """
        audio_path = Path(audio_path)

        if not audio_path.exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {audio_path}"
            )

        if stem_name not in self.model.sources:
            raise ValueError(
                f"Stem '{stem_name}' não é suportado pelo modelo "
                f"{self.MODEL_NAME}. Disponíveis: {list(self.model.sources)}"
            )

        logger.info(f"Processando áudio: {audio_path} (stem alvo: {stem_name})")

        out_dir = self._cache_dir_for(audio_path)
        out_dir.mkdir(parents=True, exist_ok=True)

        target_path = out_dir / f"{stem_name}.wav"

        # Reaproveita stems existentes (todos os stems são salvos juntos,
        # então a existência de qualquer um indica que o cache é válido)
        if target_path.exists():
            logger.info("Stem já existe. Reutilizando cache.")
            self._notify(progress_cb, "Reutilizando cache de stems…")
            return str(target_path.resolve())

        # Leitura do áudio
        self._notify(progress_cb, "Carregando áudio…")

        wav = AudioFile(str(audio_path)).read(
            streams=0,
            samplerate=self.model.samplerate,
            channels=self.model.audio_channels,
        )

        # Evita cópia desnecessária e reduz warnings/overhead
        wav = torch.as_tensor(wav, dtype=torch.float32, device=self.device)

        if wav.dim() == 2:
            wav = wav.unsqueeze(0)

        # Inferência
        self._notify(progress_cb, "Executando separação Demucs (IA)…")
        logger.info("Executando separação Demucs…")

        with torch.no_grad():
            sources = apply_model(self.model, wav, device=self.device)

        sources = sources[0]   # remove dimensão de batch

        # Exporta stems
        self._notify(progress_cb, "Salvando stems…")
        logger.info("Salvando stems…")

        for source, name in zip(sources, self.model.sources):
            out_path = out_dir / f"{name}.wav"
            audio = source.detach().cpu().numpy().T
            sf.write(
                str(out_path),
                audio,
                self.model.samplerate,
                subtype="PCM_16",
            )
            logger.info(f"Stem salva: {out_path}")

        self._notify(progress_cb, "Separação concluída!")
        logger.info("Separação concluída.")

        return str(target_path.resolve())

    def extract_guitar(
        self,
        audio_path: str,
        progress_cb: Callable[[str], None] | None = None,
    ) -> str:
        """Mantido por compatibilidade — equivalente a extract_stem(..., 'guitar')."""
        return self.extract_stem(audio_path, stem_name="guitar", progress_cb=progress_cb)

    # Utilitários internos

    def _cache_dir_for(self, audio_path: Path) -> Path:
        """
        Gera um diretório de cache único por arquivo de entrada, baseado
        no caminho absoluto (evita colisão entre arquivos de mesmo nome
        localizados em pastas diferentes).
        """
        digest = hashlib.sha1(
            str(audio_path.resolve()).encode("utf-8")
        ).hexdigest()[:10]
        safe_name = f"{audio_path.stem}_{digest}"
        return self.output_dir / self.MODEL_NAME / safe_name

    @staticmethod
    def _notify(
        cb: Callable[[str], None] | None,
        msg: str,
    ) -> None:
        """Chama o callback de progresso apenas se ele existir."""
        if cb is not None:
            cb(msg)