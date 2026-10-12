"""
Ícones da interface.

Os arquivos SVG ficam em gui/icons/ e usam `currentColor`. Aqui eles são
recoloridos conforme o tema (claro/escuro) e o estado do botão, e atualizados
automaticamente quando o usuário troca o esquema do sistema.

    from gui import icons
    icons.bind(button.setIcon, "play")                       # ícone de botão normal
    icons.bind(button.setIcon, "upload", "accent")           # sobre botão de destaque
    icons.bind(lambda i: tabs.setTabIcon(0, i), "equalizer")
    icons.bind_pixmap(label, "music-note", 72)               # ícone grande em um QLabel
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QLabel

from gui import theme

ICON_DIR = Path(__file__).resolve().parent / "icons"
_SIZES = (16, 20, 24, 32, 48, 64)
_svg_cache: dict[str, str] = {}


def _svg_text(name: str) -> str:
    if name not in _svg_cache:
        path = ICON_DIR / f"{name}.svg"
        if not path.exists():
            raise FileNotFoundError(f"Ícone não encontrado: {path}")
        _svg_cache[name] = path.read_text(encoding="utf-8")
    return _svg_cache[name]


def _render(name: str, color: str, size: int, dpr: float = 1.0) -> QPixmap:
    data = _svg_text(name).replace("currentColor", color).encode("utf-8")
    renderer = QSvgRenderer(QByteArray(data))
    px = int(size * dpr)
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def pixmap(name: str, size: int = 24, color: str | None = None) -> QPixmap:
    """Pixmap do ícone na cor pedida (padrão: cor do texto secundário do tema)."""
    t = theme.tokens()
    return _render(name, color or t.text_dim, size, dpr=2.0)


def icon(name: str, tone: str = "normal") -> QIcon:
    """
    QIcon (normal, ativo ao passar o mouse, desativado) conforme o tema atual.

    tone:
      "normal" - cor do texto (botões comuns, abas)
      "accent" - sobre botão de destaque (cor de texto do destaque)
      "danger" - botão destrutivo (vermelho; branco ao passar o mouse)
      "record" - vermelho fixo (ex.: botão de gravar)
    """
    t = theme.tokens()
    normal = {"normal": t.text, "accent": t.accent_text, "danger": t.danger, "record": t.danger}[tone]
    active = t.window if tone == "danger" else normal
    qicon = QIcon()
    for size in _SIZES:
        qicon.addPixmap(_render(name, normal, size), QIcon.Mode.Normal, QIcon.State.Off)
        qicon.addPixmap(_render(name, active, size), QIcon.Mode.Active, QIcon.State.Off)
        qicon.addPixmap(_render(name, t.disabled_text, size), QIcon.Mode.Disabled, QIcon.State.Off)
    return qicon


def bind(setter: Callable[[QIcon], None], name: str, tone: str = "normal") -> None:
    """Aplica o ícone agora e o reaplica sempre que o tema mudar."""
    setter(icon(name, tone))
    theme.on_change(lambda: setter(icon(name, tone)))


def bind_pixmap(label: QLabel, name: str, size: int = 64) -> None:
    """Mostra um ícone grande em um QLabel (ex.: capa sem imagem)."""
    label.setText("")
    label.setPixmap(pixmap(name, size))
    label.setProperty("icon_name", name)
    label.setProperty("icon_size", size)
    if not label.property("icon_listener"):  # registra o ouvinte só uma vez por rótulo
        label.setProperty("icon_listener", True)
        theme.on_change(lambda: _refresh_label(label))


def _refresh_label(label: QLabel) -> None:
    # Só redesenha se o rótulo ainda mostra um ícone (e não uma capa real).
    name = label.property("icon_name")
    if name:
        label.setPixmap(pixmap(name, int(label.property("icon_size") or 64)))


def clear_label_icon(label: QLabel) -> None:
    """Chame antes de colocar uma capa real, para o tema não sobrescrevê-la."""
    label.setProperty("icon_name", None)


def button_icon_size(button, px: int = 18) -> None:
    button.setIconSize(QSize(px, px))
