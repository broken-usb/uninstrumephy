"""
Carregamento dos arquivos de interface (.ui) do Qt Designer.

Os arquivos .ui em gui/ são a única fonte da interface: edite-os no Qt
Designer e as mudanças valem na próxima execução, sem gerar código com
pyuic6. Cada widget do arquivo vira um atributo da instância, com o mesmo
nome do seu objectName (ex.: ``self.btn_load``), exatamente como o antigo
``setupUi(self)`` fazia.

    from gui.ui_loader import load_ui_file

    class TabDemucs(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            load_ui_file("tab_demucs.ui", self)
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar
from xml.etree import ElementTree

from PyQt6 import uic
from PyQt6.QtWidgets import QWidget

UI_DIR = Path(__file__).resolve().parent

W = TypeVar("W", bound=QWidget)


class UiLoadError(RuntimeError):
    """O arquivo .ui não pôde ser carregado sobre o widget."""


def _root_widget_class(ui_path: Path) -> str | None:
    """Classe do widget raiz declarada no .ui (ex.: "QDialog")."""
    try:
        root = ElementTree.parse(ui_path).getroot().find("widget")
    except ElementTree.ParseError as exc:
        raise UiLoadError(f"Arquivo de interface inválido ({ui_path.name}): {exc}") from exc
    return root.get("class") if root is not None else None


def load_ui_file(ui_filename: str, base_instance: W) -> W:
    """Carrega ``gui/<ui_filename>`` sobre ``base_instance`` e a devolve.

    Também conecta automaticamente métodos chamados ``on_<objeto>_<sinal>``,
    como o ``setupUi`` gerado pelo pyuic6.
    """
    ui_path = UI_DIR / ui_filename
    if not ui_path.is_file():
        raise FileNotFoundError(f"Arquivo de interface não encontrado: {ui_path}")

    # O uic aplica as propriedades do widget raiz na própria instância; se a
    # classe não for compatível (ex.: .ui de QDialog sobre um QWidget), o erro
    # do Qt é pouco claro. Validamos antes para dar uma mensagem útil.
    expected = _root_widget_class(ui_path)
    if expected and not base_instance.inherits(expected):
        raise UiLoadError(
            f"{ui_path.name} define um {expected}, mas foi carregado sobre "
            f"{type(base_instance).__name__}, que não herda de {expected}."
        )

    try:
        uic.loadUi(str(ui_path), base_instance)
    except Exception as exc:
        raise UiLoadError(f"Falha ao carregar {ui_path.name}: {exc}") from exc
    return base_instance