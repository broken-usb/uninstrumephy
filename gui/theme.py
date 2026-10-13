"""
Tema visual da aplicação.

Inspirado nas diretrizes de interface do GNOME (https://developer.gnome.org/hig/),
adaptado ao Qt: superfícies planas, cantos arredondados, espaçamento em múltiplos
de 6 px, uma única cor de destaque, estilos claro/escuro que seguem o sistema e
o mínimo possível de estilo "customizado" espalhado pelos widgets.

Uso (em main_gui.py):

    from gui import theme
    theme.install(app)

Os widgets não devem chamar `setStyleSheet` por conta própria. Em vez disso:
  * use `objectName` já existente (ex.: `#frameHeader`), ou
  * marque o widget com a propriedade dinâmica `role`:
        widget.setProperty("role", "caption")      # texto secundário pequeno
        button.setProperty("role", "suggested")    # ação principal da tela
        button.setProperty("role", "destructive")  # ação destrutiva
        button.setProperty("role", "flat")         # botão sem moldura
        button.setProperty("role", "circular")     # botão redondo (ícone)
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PyQt6.QtWidgets import QApplication


# --------------------------------------------------------------------------- #
# Tokens de cor (nomes genéricos, por função)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Tokens:
    window: str          # fundo da janela / área de conteúdo
    surface: str         # fundo de cartões, campos e áreas elevadas
    chrome: str          # barra superior, barra lateral e barra inferior
    border: str          # bordas e separadores sutis
    text: str            # texto principal
    text_dim: str        # texto secundário
    accent: str          # cor de destaque (seleção, ação principal, controles ativos)
    accent_text: str     # texto sobre a cor de destaque
    danger: str          # ações destrutivas e erros
    success: str         # confirmações
    warning: str         # avisos
    hover: str           # sobreposição ao passar o mouse (rgba)
    pressed: str         # sobreposição ao pressionar (rgba)
    disabled_text: str
    # Cores de dados para os gráficos (diferenciadas também por forma/rótulo)
    series_a: str
    series_b: str
    series_c: str


LIGHT = Tokens(
    window="#fafafa",
    surface="#ffffff",
    chrome="#ebebeb",
    border="#d6d6d6",
    text="#2e2e32",
    text_dim="#6a6a72",
    accent="#3584e4",
    accent_text="#ffffff",
    danger="#c01c28",
    success="#26a269",
    warning="#cd9309",
    hover="rgba(0, 0, 0, 0.06)",
    pressed="rgba(0, 0, 0, 0.12)",
    disabled_text="#a0a0a6",
    series_a="#3584e4",
    series_b="#e5731a",
    series_c="#9141ac",
)

DARK = Tokens(
    window="#242428",
    surface="#303034",
    chrome="#1d1d20",
    border="#444449",
    text="#f2f2f4",
    text_dim="#a8a8b0",
    accent="#78aeed",
    accent_text="#102a4c",
    danger="#ff7b63",
    success="#57e389",
    warning="#f8e45c",
    hover="rgba(255, 255, 255, 0.08)",
    pressed="rgba(255, 255, 255, 0.15)",
    disabled_text="#6c6c74",
    series_a="#78aeed",
    series_b="#ffa348",
    series_c="#dc8add",
)

RADIUS = 6          # controles
RADIUS_CARD = 12    # cartões e painéis
UNIT = 6            # unidade base de espaçamento

_current: Tokens = LIGHT


def tokens() -> Tokens:
    """Tokens do esquema atualmente aplicado (útil para gráficos)."""
    return _current


def is_dark() -> bool:
    return _current is DARK


# --------------------------------------------------------------------------- #
# Aplicação do tema
# --------------------------------------------------------------------------- #
def _build_palette(t: Tokens) -> QPalette:
    p = QPalette()
    R = QPalette.ColorRole
    G = QPalette.ColorGroup
    c = QColor

    p.setColor(R.Window, c(t.window))
    p.setColor(R.WindowText, c(t.text))
    p.setColor(R.Base, c(t.surface))
    p.setColor(R.AlternateBase, c(t.window))
    p.setColor(R.Text, c(t.text))
    p.setColor(R.Button, c(t.surface))
    p.setColor(R.ButtonText, c(t.text))
    p.setColor(R.BrightText, c(t.danger))
    p.setColor(R.ToolTipBase, c(t.chrome))
    p.setColor(R.ToolTipText, c(t.text))
    p.setColor(R.PlaceholderText, c(t.text_dim))
    p.setColor(R.Highlight, c(t.accent))
    p.setColor(R.HighlightedText, c(t.accent_text))
    p.setColor(R.Link, c(t.accent))
    p.setColor(R.Light, c(t.surface))
    p.setColor(R.Midlight, c(t.chrome))
    p.setColor(R.Mid, c(t.border))
    p.setColor(R.Dark, c(t.border))
    p.setColor(R.Shadow, c("#000000"))

    for role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(G.Disabled, role, c(t.disabled_text))
    return p


def _write_icons(t: Tokens) -> dict[str, str]:
    """
    Gera pequenos ícones SVG com as cores do esquema atual (o QSS não desenha
    setas nem marcas de seleção sozinho). Retorna {nome: caminho com "/"}.
    """
    folder = Path(tempfile.gettempdir()) / "uninstrumephy_theme" / ("dark" if t is DARK else "light")
    folder.mkdir(parents=True, exist_ok=True)

    def svg(name: str, body: str, size: int = 16) -> str:
        path = folder / f"{name}.svg"
        path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}" fill="none" stroke-linecap="round" '
            f'stroke-linejoin="round">{body}</svg>',
            encoding="utf-8",
        )
        return path.as_posix()

    dim, txt, on = t.text_dim, t.text, t.accent_text
    return {
        "down": svg("down", f'<path d="M3.5 6l4.5 4.5L12.5 6" stroke="{txt}" stroke-width="1.8"/>'),
        "down_dis": svg("down_dis", f'<path d="M3.5 6l4.5 4.5L12.5 6" stroke="{t.disabled_text}" stroke-width="1.8"/>'),
        "up_s": svg("up_s", f'<path d="M3.5 10l4.5-4.5L12.5 10" stroke="{txt}" stroke-width="1.8"/>'),
        "down_s": svg("down_s", f'<path d="M3.5 6l4.5 4.5L12.5 6" stroke="{txt}" stroke-width="1.8"/>'),
        "check": svg("check", f'<path d="M3.5 8.5l3 3 6-6.5" stroke="{on}" stroke-width="2"/>'),
        "dot": svg("dot", f'<circle cx="8" cy="8" r="3" fill="{on}"/>'),
    }


def _stylesheet(t: Tokens, caption_pt: float) -> str:
    ic = _write_icons(t)
    return f"""
/* ---------- base ---------- */
QDialog, QMainWindow {{ background: {t.window}; }}
QToolTip {{
    background: {t.chrome}; color: {t.text};
    border: 1px solid {t.border}; border-radius: {RADIUS}px; padding: 4px 8px;
}}

/* ---------- estrutura da janela principal ---------- */
#frameHeader   {{ background: {t.chrome}; border-bottom: 1px solid {t.border}; }}
#frameLeft     {{ background: {t.chrome}; border-right: 1px solid {t.border}; }}
#framePlayback {{ background: {t.chrome}; border-top: 1px solid {t.border}; }}
#frameInfo     {{ background: {t.window}; }}

#lbl_cover {{
    background: {t.surface}; color: {t.text_dim};
    border: 1px solid {t.border}; border-radius: {RADIUS_CARD}px;
    font-size: 18pt;
}}
#lbl_filepath {{ color: {t.text_dim}; }}
#lbl_info     {{ font-weight: bold; }}
#lbl_section_orig, #lbl_section_stem {{ font-weight: bold; }}
#lbl_status   {{ font-weight: bold; }}

QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color: {t.border}; }}  /* HLine/VLine */

/* ---------- texto secundário ---------- */
*[role="caption"],
#lbl_hardware_hint, #lbl_gate_source, #lbl_demucs_options_hint,
#lbl_analyzed_stem {{
    color: {t.text_dim}; font-size: {caption_pt:.1f}pt;
}}
*[role="heading"], #lbl_hardware_title {{ font-weight: bold; font-size: {caption_pt * 1.35:.1f}pt; }}

/* ---------- botões ---------- */
QPushButton {{
    background: {t.surface}; color: {t.text};
    border: 1px solid {t.border}; border-radius: {RADIUS}px;
    padding: 6px 14px; min-height: 20px;
}}
QPushButton:hover    {{ background: {t.chrome}; }}
QPushButton:pressed  {{ background: {t.border}; }}
QPushButton:focus    {{ border: 2px solid {t.accent}; padding: 5px 13px; }}
QPushButton:disabled {{ color: {t.disabled_text}; background: {t.window}; border-color: {t.border}; }}

QPushButton[role="suggested"] {{
    background: {t.accent}; color: {t.accent_text}; border: 1px solid {t.accent};
}}
QPushButton[role="suggested"]:hover   {{ background: {t.accent}; border-color: {t.text}; }}
QPushButton[role="suggested"]:pressed {{ background: {t.accent}; }}
QPushButton[role="suggested"]:disabled {{ background: {t.chrome}; color: {t.disabled_text}; border-color: {t.border}; }}

QPushButton[role="destructive"] {{ color: {t.danger}; }}
QPushButton[role="destructive"]:hover {{ background: {t.danger}; color: {t.window}; border-color: {t.danger}; }}
QPushButton[role="destructive"]:disabled {{ color: {t.disabled_text}; }}

QPushButton[role="flat"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[role="flat"]:hover   {{ background: {t.hover}; }}
QPushButton[role="flat"]:pressed {{ background: {t.pressed}; }}

QPushButton[role="circular"] {{
    min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px;
    padding: 0; border-radius: 17px;
}}
QPushButton[role="circular"]:focus {{ padding: 0; }}

/* ---------- campos ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {t.surface}; color: {t.text};
    border: 1px solid {t.border}; border-radius: {RADIUS}px; padding: 5px 8px;
    selection-background-color: {t.accent}; selection-color: {t.accent_text};
}}
QSpinBox, QDoubleSpinBox {{ padding-right: 28px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 24px; border: none; border-left: 1px solid {t.border};
    border-top-right-radius: {RADIUS}px; background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 24px; border: none; border-left: 1px solid {t.border};
    border-bottom-right-radius: {RADIUS}px; background: transparent;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: {t.hover}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({ic['up_s']}); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({ic['down_s']}); width: 10px; height: 10px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border: 2px solid {t.accent}; }}

QComboBox {{
    background: {t.surface}; color: {t.text};
    border: 1px solid {t.border}; border-radius: {RADIUS}px;
    padding: 5px 10px; min-height: 20px;
}}
QComboBox:hover {{ background: {t.chrome}; }}
QComboBox:focus {{ border: 2px solid {t.accent}; padding: 4px 9px; }}
QComboBox::drop-down {{ border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url({ic['down']}); width: 14px; height: 14px; }}
QComboBox::down-arrow:disabled {{ image: url({ic['down_dis']}); }}
QComboBox QAbstractItemView {{
    background: {t.surface}; color: {t.text};
    border: 1px solid {t.border}; border-radius: {RADIUS}px; padding: 4px;
    selection-background-color: {t.accent}; selection-color: {t.accent_text};
    outline: none;
}}

/* ---------- caixas de seleção e opções ---------- */
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid {t.border}; background: {t.surface};
}}
QCheckBox::indicator   {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {t.accent}; border-color: {t.accent};
}}
QCheckBox::indicator:checked   {{ image: url({ic['check']}); }}
QRadioButton::indicator:checked {{ image: url({ic['dot']}); }}
QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border: 2px solid {t.accent}; }}

/* ---------- controles deslizantes ---------- */
QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
QSlider::add-page:horizontal {{ background: {t.border}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -6px 0; border-radius: 8px;
    background: {t.surface}; border: 1px solid {t.text_dim};
}}
QSlider::handle:horizontal:hover {{ border-color: {t.accent}; }}
QSlider::handle:horizontal:focus {{ border: 2px solid {t.accent}; }}
QSlider::groove:horizontal:disabled, QSlider::sub-page:horizontal:disabled {{ background: {t.border}; }}

/* ---------- progresso ---------- */
QProgressBar {{
    background: {t.border}; border: none; border-radius: 3px; text-align: center;
}}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}

QProgressBar[role="meter"] {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 4px;
}}
QProgressBar[role="meter"]::chunk {{
    border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {t.success}, stop:0.75 {t.warning}, stop:0.95 {t.danger});
}}
QCheckBox[role="emphasis"] {{ font-weight: bold; }}

/* ---------- abas ---------- */
QTabWidget::pane {{ border: none; border-top: 1px solid {t.border}; background: {t.window}; top: -1px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {t.text_dim};
    padding: 9px 16px; margin: 0 2px; border: none; border-bottom: 3px solid transparent;
}}
QTabBar::tab:hover    {{ color: {t.text}; background: {t.hover}; }}
QTabBar::tab:selected {{ color: {t.text}; border-bottom: 3px solid {t.accent}; font-weight: bold; }}
QTabBar::tab:focus    {{ background: {t.hover}; }}

/* ---------- listas, tabelas e rolagem ---------- */
QAbstractItemView {{
    background: {t.surface}; color: {t.text};
    border: 1px solid {t.border}; border-radius: {RADIUS}px;
    selection-background-color: {t.accent}; selection-color: {t.accent_text};
    alternate-background-color: {t.window};
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QScrollBar:vertical   {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {t.border}; border-radius: 4px; min-height: 28px; min-width: 28px;
}}
QScrollBar::handle:hover {{ background: {t.text_dim}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- agrupamentos ---------- */
QGroupBox {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: {RADIUS_CARD}px;
    margin-top: 18px; padding: 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 12px; padding: 0 4px; color: {t.text_dim}; font-weight: bold;
}}

/* ---------- cartão de efeito ---------- */
EffectWidget {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: {RADIUS_CARD}px;
}}
EffectWidget QLabel {{ background: transparent; }}
EffectWidget QLabel[role="value"] {{ color: {t.text}; font-weight: bold; }}
EffectWidget QLabel[role="param"] {{ color: {t.text_dim}; }}
EffectWidget QLabel[role="title"] {{ font-weight: bold; }}

/* ---------- caixas de diálogo ---------- */
QMessageBox {{ background: {t.window}; }}
QMenu {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
    border-radius: {RADIUS_CARD}px; padding: 6px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: {RADIUS}px; }}
QMenu::item:selected {{ background: {t.hover}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 6px; }}
"""


def _resolve_dark(app: QApplication, scheme: str) -> bool:
    if scheme == "dark":
        return True
    if scheme == "light":
        return False
    return app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def apply(app: QApplication, scheme: str = "system") -> None:
    """Aplica o tema. `scheme`: "system" (padrão), "light" ou "dark"."""
    global _current
    _current = DARK if _resolve_dark(app, scheme) else LIGHT

    app.setStyle("Fusion")
    app.setPalette(_build_palette(_current))

    base: QFont = app.font()
    base_pt = base.pointSizeF() if base.pointSizeF() > 0 else 10.0
    app.setStyleSheet(_stylesheet(_current, caption_pt=round(base_pt * 0.85, 1)))

    # Gráficos e outros widgets que não usam QSS podem reagir a este sinal.
    _notify()


def install(app: QApplication, scheme: str = "system") -> None:
    """Aplica o tema e passa a acompanhar a preferência claro/escuro do sistema."""
    apply(app, scheme)
    if scheme == "system":
        app.styleHints().colorSchemeChanged.connect(lambda _s: apply(app, "system"))


# --------------------------------------------------------------------------- #
# Notificação simples para widgets que precisam redesenhar (ex.: gráficos)
# --------------------------------------------------------------------------- #
_listeners: list = []


def on_change(callback) -> None:
    _listeners.append(callback)


def _notify() -> None:
    for cb in list(_listeners):
        try:
            cb()
        except RuntimeError:
            # widget já destruído
            _listeners.remove(cb)
