from pathlib import Path
from PyQt6 import uic

UI_DIR = Path(__file__).resolve().parent

def load_ui_file(ui_filename: str, base_instance):
    """Carrega dinamicamente o arquivo .ui sobre a instância do widget."""
    ui_path = UI_DIR / ui_filename
    if not ui_path.exists():
        raise FileNotFoundError(f"Arquivo de interface não encontrado: {ui_path}")
    uic.loadUi(str(ui_path), base_instance)