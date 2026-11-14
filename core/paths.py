"""
Onde o programa grava os seus arquivos.

Rodando a partir do código-fonte, tudo continua dentro da pasta do projeto,
como antes (output/ e presets/). Rodando empacotado (AppImage) ou de uma
pasta sem permissão de escrita (ex.: C:\\Program Files), os dados vão para a
pasta padrão do usuário no sistema:

    Linux:   ~/.local/share/uninstrumephy/   (ou $XDG_DATA_HOME/uninstrumephy)
    Windows: %LOCALAPPDATA%\\uninstrumephy\\
        logs/        latest-log.txt, previous-log.txt
        recordings/  gravações da pedaleira/microfone
        presets/     presets do usuário (começa com os presets incluídos)
        <modelo>/    faixas separadas pelo Demucs

A variável de ambiente UNINSTRUMEPHY_DATA_DIR substitui essa pasta (útil para
testes ou para guardar os dados em outro disco).
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "uninstrumephy"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_PRESETS_DIR = PROJECT_ROOT / "presets"


@lru_cache(maxsize=None)
def _project_is_writable() -> bool:
    """Testa de verdade se dá para criar arquivos na pasta do programa.

    os.access(W_OK) não serve: no Windows ele ignora as permissões da pasta
    (ACLs) e diria que C:\\Program Files é gravável para qualquer usuário.
    """
    try:
        with tempfile.TemporaryFile(dir=PROJECT_ROOT):
            return True
    except OSError:
        return False


def is_packaged() -> bool:
    """True se rodando como AppImage/executável empacotado ou de uma pasta sem escrita."""
    return (
        bool(os.environ.get("APPIMAGE"))
        or bool(getattr(sys, "frozen", False))  # PyInstaller e similares
        or not _project_is_writable()
    )


def _user_data_base() -> Path:
    """Pasta-base de dados de aplicativos do usuário, conforme o sistema."""
    if sys.platform == "win32" and not os.environ.get("APPIMAGE"):
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) if local else Path.home() / "AppData" / "Local"
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) if xdg else Path.home() / ".local" / "share"


def data_dir() -> Path:
    """Pasta-base dos dados do usuário (equivale ao antigo output/)."""
    override = os.environ.get("UNINSTRUMEPHY_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if is_packaged():
        return _user_data_base() / APP_NAME
    return PROJECT_ROOT / "output"


def logs_dir() -> Path:
    return data_dir() / "logs"


def recordings_dir() -> Path:
    return data_dir() / "recordings"


def stems_dir() -> Path:
    """Base das faixas separadas pelo Demucs (uma subpasta por modelo)."""
    return data_dir()


def presets_dir() -> Path:
    """Pasta dos presets.

    Do código-fonte: presets/ do projeto (incluídos e do usuário juntos).
    Empacotado: uma pasta do usuário, criada na primeira execução com uma
    cópia dos presets incluídos. Depois disso não é mais recriada, para que
    um preset excluído pelo usuário não volte sozinho.
    """
    if not is_packaged() and not os.environ.get("UNINSTRUMEPHY_DATA_DIR"):
        return BUNDLED_PRESETS_DIR
    user_dir = data_dir() / "presets"
    if not user_dir.exists():
        try:
            user_dir.mkdir(parents=True)
            for preset in BUNDLED_PRESETS_DIR.glob("*.json"):
                shutil.copy2(preset, user_dir / preset.name)
            logger.info("Presets incluídos copiados para %s", user_dir)
        except OSError as exc:
            logger.warning("Não foi possível preparar a pasta de presets %s: %s", user_dir, exc)
    return user_dir
