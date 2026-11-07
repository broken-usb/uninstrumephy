"""
Onde o programa grava os seus arquivos.

Rodando a partir do código-fonte, tudo continua dentro da pasta do projeto,
como antes (output/ e presets/). Rodando empacotado (AppImage), a pasta do
programa é somente leitura, então os dados vão para as pastas padrão do
usuário no Linux:

    ~/.local/share/uninstrumephy/          (ou $XDG_DATA_HOME/uninstrumephy)
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
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "uninstrumephy"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_PRESETS_DIR = PROJECT_ROOT / "presets"


def is_packaged() -> bool:
    """True se rodando como AppImage (ou de uma pasta sem permissão de escrita)."""
    return bool(os.environ.get("APPIMAGE")) or not os.access(PROJECT_ROOT, os.W_OK)


def data_dir() -> Path:
    """Pasta-base dos dados do usuário (equivale ao antigo output/)."""
    override = os.environ.get("UNINSTRUMEPHY_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if is_packaged():
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return Path(xdg) / APP_NAME
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
