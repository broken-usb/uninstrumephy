"""
Mensagens de erro para o usuário.

Os workers (Demucs, Tone Matching, envio para a pedaleira) entregam o erro
como texto: ou uma mensagem já escrita para o usuário (ex.: HardwareLinkError)
ou um traceback completo do Python. Este módulo transforma isso em uma caixa
de diálogo com três níveis:

  * texto principal — o que aconteceu, em português simples;
  * texto informativo — o que fazer a seguir e onde está o log completo;
  * "Mostrar detalhes" — o traceback, para quem for depurar.

    from gui.errors import show_error
    show_error(self, "Falha na separação", err_msg)
"""

from __future__ import annotations

import logging
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox, QWidget

from core import paths

_TRACEBACK_HEADER = "Traceback (most recent call last)"


@dataclass(frozen=True)
class ErrorInfo:
    summary: str             # o que aconteceu
    hint: str | None = None  # o que fazer a seguir
    details: str | None = None  # traceback completo, se houver


def _last_exception_line(text: str) -> tuple[str, str]:
    """('ModuleNotFoundError', "No module named 'torch'") da última linha do traceback."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    match = re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning)?):\s*(.*)$", last)
    if match:
        return match.group(1).rsplit(".", 1)[-1], match.group(2)
    if re.fullmatch(r"[A-Za-z_][\w.]*", last):  # exceção sem mensagem: "MemoryError"
        return last.rsplit(".", 1)[-1], ""
    return "", last


def _quoted_path(message: str) -> str | None:
    match = re.search(r"['\"]([^'\"]+)['\"]\s*$", message)
    return match.group(1) if match else None


def _is_missing_ffmpeg(message: str, details: str | None) -> bool:
    """O FileNotFoundError veio de tentar executar ffmpeg/ffprobe?

    Linux: "[Errno 2] No such file or directory: 'ffprobe'".
    Windows: "[WinError 2] O sistema não pode encontrar o arquivo especificado",
    sem o nome do programa. Nem sempre ele aparece no traceback (o Python 3.12
    mostra só a 1ª linha de uma chamada em várias linhas), então reconhecemos
    pela origem: o módulo de áudio do Demucs, que só executa ffmpeg e ffprobe,
    tentando executar um programa (subprocess).
    """
    if _quoted_path(message) in ("ffmpeg", "ffprobe"):
        return True
    if "WinError 2" not in message or not details:
        return False
    return bool(re.search(r"demucs[\\/]audio\.py", details)) and "subprocess.py" in details


def describe_error(error: str | BaseException) -> ErrorInfo:
    """Converte um erro (texto de worker ou exceção) em uma mensagem amigável."""
    if isinstance(error, BaseException):
        details = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        exc_type, message = type(error).__name__, str(error)
    else:
        text = (error or "").strip()
        if _TRACEBACK_HEADER not in text:
            # Mensagem já escrita para o usuário (ex.: HardwareLinkError).
            return ErrorInfo(text or "Ocorreu um erro inesperado.")
        details = text
        exc_type, message = _last_exception_line(text)

    lowered = message.lower()

    if exc_type in ("ModuleNotFoundError", "ImportError"):
        module = re.search(r"No module named '([^']+)'", message)
        name = module.group(1).split(".")[0] if module else None
        return ErrorInfo(
            f"Uma biblioteca necessária não está instalada{f' ({name})' if name else ''}.",
            "Reinstale as dependências com: pip install -r requirements.txt",
            details,
        )
    if exc_type in ("MemoryError", "OutOfMemoryError") or "out of memory" in lowered:
        return ErrorInfo(
            "Memória insuficiente para processar este áudio.",
            "Feche outros programas pesados e tente de novo, ou use um trecho menor da música.",
            details,
        )
    if exc_type == "FileNotFoundError" and _is_missing_ffmpeg(message, details):
        # O Demucs chama os programas ffmpeg/ffprobe para ler as músicas.
        if sys.platform == "win32":
            how = ("Instale-o (no Prompt de Comando: winget install Gyan.FFmpeg), "
                   "feche e abra o programa de novo e tente outra vez.")
        else:
            how = ("Instale-o (Fedora: sudo dnf install ffmpeg-free; "
                   "Ubuntu/Debian: sudo apt install ffmpeg) e tente de novo.")
        return ErrorInfo(
            "O programa ffmpeg não está instalado.",
            f"Ele é necessário para separar as faixas com o Demucs. {how}",
            details,
        )
    if exc_type == "FileNotFoundError":
        path = _quoted_path(message)
        return ErrorInfo(
            f"Arquivo não encontrado{f': {path}' if path else '.'}",
            "Verifique se o arquivo não foi movido, renomeado ou apagado.",
            details,
        )
    if exc_type == "PermissionError":
        path = _quoted_path(message)
        return ErrorInfo(
            f"Sem permissão para acessar{f': {path}' if path else ' o arquivo.'}",
            "Verifique as permissões da pasta ou escolha outro local.",
            details,
        )
    if "no space left on device" in lowered or "errno 28" in lowered:
        return ErrorInfo(
            "Não há espaço livre em disco.",
            f"Libere espaço (as separações ficam em {paths.stems_dir()}) e tente de novo.",
            details,
        )
    if exc_type == "LibsndfileError" or "format not recognised" in lowered or "error opening" in lowered:
        return ErrorInfo(
            "Não foi possível ler o arquivo de áudio.",
            "O formato pode não ser suportado ou o arquivo pode estar corrompido. "
            "Tente convertê-lo para WAV ou MP3.",
            details,
        )

    summary = message or exc_type or "Ocorreu um erro inesperado."
    return ErrorInfo(summary, None, details)


def log_file_path() -> Path | None:
    """Arquivo de log da sessão atual (configurado em core/logger.py)."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    return None


def show_error(
    parent: QWidget | None,
    title: str,
    error: str | BaseException,
    *,
    headline: str | None = None,
    hint: str | None = None,
) -> None:
    """Mostra o erro em uma caixa de diálogo modal.

    headline — substitui o texto principal (o resumo vai para o informativo);
    hint     — dica usada quando o erro não tem uma dica própria.
    """
    info = describe_error(error)

    informative = []
    if headline:
        informative.append(info.summary)
    if info.hint or hint:
        informative.append(info.hint or hint)
    log_path = log_file_path()
    if info.details and log_path is not None:
        informative.append(f"O registro completo está em:\n{log_path}")

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(headline or info.summary)
    if informative:
        box.setInformativeText("\n\n".join(informative))
    if info.details:
        box.setDetailedText(info.details)
    box.exec()
