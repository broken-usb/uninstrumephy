from __future__ import annotations

import hashlib
import logging
import time
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

    O modelo é carregado uma única vez por combinação (model_name, device)
    e reutilizado via cache de classe (_cached_models), evitando
    recarregamentos desnecessários entre chamadas com a mesma configuração.

    Modelos pré-treinados oficiais suportados (AVAILABLE_MODELS):
        htdemucs      - 4 stems (vocals, drums, bass, other), padrão mais recente
        htdemucs_ft   - variante fine-tuned do htdemucs, mais lenta e precisa
        htdemucs_6s   - 6 stems (vocals, drums, bass, guitar, piano, other)
        mdx_extra     - modelo MDX, 4 stems, arquitetura diferente do htdemucs
    """

    _cached_models: dict[tuple[str, str], object] = {}

    AVAILABLE_MODELS: list[str] = ["htdemucs", "htdemucs_ft", "htdemucs_6s", "mdx_extra"]
    MODEL_NAME = "htdemucs_6s"    # mantido por compatibilidade com código existente
    DEFAULT_STEM = "guitar"

    # Limites razoáveis para os parâmetros de qualidade x velocidade,
    # usados para validar entradas vindas da UI
    MIN_SHIFTS, MAX_SHIFTS = 0, 10
    MIN_OVERLAP, MAX_OVERLAP = 0.0, 0.99

    def __init__(
        self,
        output_dir: str = "output",
        model_name: str | None = None,
        device: str | None = None,
        shifts: int = 1,
        overlap: float = 0.25,
    ) -> None:
        """
        Args:
            output_dir: Diretório base onde os stems separados são salvos.
            model_name: Nome do modelo Demucs a usar (ver AVAILABLE_MODELS).
                Se None, usa MODEL_NAME (htdemucs_6s), mantendo o
                comportamento padrão anterior.
            device: "cuda" ou "cpu". Se None, detecta automaticamente
                (usa CUDA se disponível).
            shifts: Número de deslocamentos aleatórios aplicados ao áudio
                durante a inferência (shift trick) — valores maiores
                tendem a melhorar a qualidade da separação ao custo de
                tempo de processamento proporcionalmente maior. 0 desativa
                o truque (mais rápido, qualidade padrão). Default: 1.
            overlap: Sobreposição entre janelas de processamento (0.0–0.99).
                Valores maiores suavizam transições entre blocos ao custo
                de mais tempo de processamento. Default: 0.25 (padrão do
                Demucs).
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.model_name = model_name or self.MODEL_NAME
        if self.model_name not in self.AVAILABLE_MODELS:
            raise ValueError(
                f"Modelo '{self.model_name}' não reconhecido. "
                f"Disponíveis: {self.AVAILABLE_MODELS}"
            )

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Device selecionado: {self.device}")

        self.shifts = self._clamp(shifts, self.MIN_SHIFTS, self.MAX_SHIFTS, "shifts")
        self.overlap = self._clamp(overlap, self.MIN_OVERLAP, self.MAX_OVERLAP, "overlap")

        # Cache por combinação (modelo, device) — permite trocar de
        # modelo/dispositivo entre execuções sem recarregar do zero algo
        # que já foi carregado antes na mesma sessão
        cache_key = (self.model_name, self.device)
        if cache_key not in AudioSeparator._cached_models:
            logger.info(
                f"Carregando modelo Demucs: {self.model_name} (device={self.device})"
            )
            model = get_model(self.model_name)
            model.to(self.device)
            model.eval()
            AudioSeparator._cached_models[cache_key] = model

        self.model = AudioSeparator._cached_models[cache_key]

    @staticmethod
    def _clamp(value: float, low: float, high: float, name: str) -> float:
        """Garante que um parâmetro numérico da UI fique dentro de limites seguros."""
        if value < low or value > high:
            logger.warning(
                f"Parâmetro '{name}'={value} fora do intervalo [{low}, {high}]; "
                f"ajustando para o limite mais próximo."
            )
        return max(low, min(high, value))

    # Separação

    def extract_stem(
        self,
        audio_path: str,
        stem_name: str = DEFAULT_STEM,
        progress_cb: Callable[[str], None] | None = None,
        force_reprocess: bool = False,
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
            force_reprocess: Se True, ignora qualquer cache existente para
                esta combinação (arquivo, modelo) e roda a separação de
                novo, sobrescrevendo os stems já salvos em disco. Útil
                para forçar uma nova execução com os mesmos parâmetros
                (ex.: o usuário desconfia que o cache está corrompido, ou
                quer comparar resultados de execuções diferentes do
                shift trick, que tem componente aleatório).

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
                f"{self.model_name}. Disponíveis: {list(self.model.sources)}"
            )

        logger.info(f"Processando áudio: {audio_path} (stem alvo: {stem_name})")

        out_dir = self._cache_dir_for(audio_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Diretório de cache: {out_dir}")

        target_path = out_dir / f"{stem_name}.wav"

        # Reaproveita stems existentes (todos os stems são salvos juntos,
        # então a existência de qualquer um indica que o cache é válido),
        # a menos que o reprocessamento tenha sido forçado explicitamente
        if target_path.exists() and not force_reprocess:
            logger.info("Stem já existe. Reutilizando cache.")
            self._notify(progress_cb, "Reutilizando cache de stems…")
            return str(target_path.resolve())

        if target_path.exists() and force_reprocess:
            logger.info(
                f"Cache existente em {out_dir} será ignorado "
                f"(force_reprocess=True) — reprocessando do zero."
            )
            self._notify(progress_cb, "Reprocessando (cache ignorado)…")

        # Leitura do áudio
        self._notify(progress_cb, "Carregando áudio…")
        load_start = time.monotonic()

        wav = AudioFile(str(audio_path)).read(
            streams=0,
            samplerate=self.model.samplerate,
            channels=self.model.audio_channels,
        )

        # Evita cópia desnecessária e reduz warnings/overhead
        wav = torch.as_tensor(wav, dtype=torch.float32, device=self.device)

        if wav.dim() == 2:
            wav = wav.unsqueeze(0)

        logger.debug(
            f"Áudio carregado em {time.monotonic() - load_start:.2f}s "
            f"(shape={tuple(wav.shape)})"
        )

        # Inferência
        self._notify(progress_cb, "Executando separação Demucs (IA)…")
        logger.info(
            f"Executando separação Demucs… "
            f"(shifts={self.shifts}, overlap={self.overlap})"
        )
        infer_start = time.monotonic()

        with torch.no_grad():
            sources = apply_model(
                self.model,
                wav,
                device=self.device,
                shifts=self.shifts,
                overlap=self.overlap,
            )

        logger.info(
            f"Inferência Demucs concluída em "
            f"{time.monotonic() - infer_start:.2f}s"
        )

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
        force_reprocess: bool = False,
    ) -> str:
        """Mantido por compatibilidade — equivalente a extract_stem(..., 'guitar')."""
        return self.extract_stem(
            audio_path,
            stem_name="guitar",
            progress_cb=progress_cb,
            force_reprocess=force_reprocess,
        )

    # Utilitários internos

    def _cache_dir_for(self, audio_path: Path) -> Path:
        """
        Gera um diretório de cache único por arquivo de entrada, baseado
        no NOME do arquivo + seu TAMANHO em bytes (não no caminho absoluto).

        Isso garante duas coisas ao mesmo tempo:
          - Evita colisão entre arquivos de mesmo nome mas conteúdo
            diferente (tamanhos diferentes → hash diferente).
          - Sobrevive à movimentação do arquivo entre pastas (ex.: o
            usuário move a música de Downloads/ para Musicas/TCC/), já
            que o caminho absoluto não entra mais no cálculo do hash.

        Se o tamanho do arquivo não puder ser lido (ex.: problema de
        permissão ou volume de rede instável), cai em um fallback seguro
        usando o caminho absoluto, para nunca quebrar a separação.
        """
        try:
            file_size = audio_path.stat().st_size
            hash_input = f"{audio_path.name}_{file_size}"
        except OSError as exc:
            logger.warning(
                f"Não foi possível ler o tamanho de {audio_path}: {exc}. "
                f"Usando caminho absoluto como fallback para o cache."
            )
            hash_input = str(audio_path.resolve())

        digest = hashlib.sha1(hash_input.encode("utf-8")).hexdigest()[:10]
        safe_name = f"{audio_path.stem}_{digest}"
        return self.output_dir / self.model_name / safe_name

    @staticmethod
    def _notify(
        cb: Callable[[str], None] | None,
        msg: str,
    ) -> None:
        """Chama o callback de progresso apenas se ele existir."""
        if cb is not None:
            cb(msg)