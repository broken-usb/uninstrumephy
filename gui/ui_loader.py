"""
Carregamento dos arquivos de interface (.ui) do Qt Designer.

Os arquivos .ui em gui/ são a única fonte da interface: edite-os no Qt
Designer e as mudanças valem na próxima execução, sem gerar código com
pyuic6. Cada widget do arquivo vira um atributo da instância, com o mesmo
nome do seu objectName (ex.: ``self.btn_load``).

    from gui.ui_loader import load_ui_file

    class TabDemucs(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            load_ui_file("tab_demucs.ui", self)

Desempenho: cada .ui é lido e compilado uma única vez por execução
(``uic.loadUiType``) e mantido em cache. As instâncias seguintes só executam
o código já compilado, cerca de 10x mais rápido que reler o XML. Isso importa
para widgets criados muitas vezes, como os cartões de efeito.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TypeVar

from PyQt6 import uic
from PyQt6.QtWidgets import QWidget

UI_DIR = Path(__file__).resolve().parent

W = TypeVar("W", bound=QWidget)


class UiLoadError(RuntimeError):
    """O arquivo .ui não pôde ser carregado sobre o widget."""


@lru_cache(maxsize=None)
def _compiled_form(ui_path: Path) -> tuple[type, type]:
    """(classe do formulário, classe Qt do widget raiz), compilados uma vez."""
    try:
        return uic.loadUiType(str(ui_path))
    except Exception as exc:  # XML inválido, widget customizado não encontrado…
        raise UiLoadError(f"Falha ao carregar {ui_path.name}: {exc}") from exc


def load_ui_file(ui_filename: str, base_instance: W) -> W:
    """Monta ``gui/<ui_filename>`` sobre ``base_instance`` e a devolve.

    Também conecta automaticamente métodos chamados ``on_<objeto>_<sinal>``.
    """
    ui_path = UI_DIR / ui_filename
    if not ui_path.is_file():
        raise FileNotFoundError(f"Arquivo de interface não encontrado: {ui_path}")

    form_class, root_class = _compiled_form(ui_path)

    # O formulário aplica as propriedades do widget raiz na própria instância;
    # com a classe errada (ex.: .ui de QDialog sobre um QWidget) o erro do Qt
    # seria pouco claro. Validamos antes para dar uma mensagem útil.
    if not isinstance(base_instance, root_class):
        raise UiLoadError(
            f"{ui_path.name} define um {root_class.__name__}, mas foi carregado "
            f"sobre {type(base_instance).__name__}, que não herda de {root_class.__name__}."
        )

    form = form_class()
    form.setupUi(base_instance)
    # Expõe os widgets como atributos da própria instância (self.btn_load…).
    for name, obj in vars(form).items():
        setattr(base_instance, name, obj)
    return base_instance