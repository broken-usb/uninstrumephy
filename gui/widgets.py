"""Widgets de uso geral com visual próprio (ver gui/theme.py)."""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy

from gui import theme


class Switch(QAbstractButton):
    """
    Interruptor liga/desliga. Mesma API de um QCheckBox para quem usa
    (`isChecked`, `setChecked`, `toggled`), então pode substituí-lo diretamente.
    Use para ativar/desativar algo imediatamente (ex.: um efeito).
    """

    _W, _H, _PAD = 40, 22, 3

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knobPosition", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(self._W, self._H)

    def _get_pos(self) -> float:
        return self._pos

    def _set_pos(self, value: float) -> None:
        self._pos = value
        self.update()

    knobPosition = pyqtProperty(float, _get_pos, _set_pos)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 (API do Qt)
        super().setChecked(checked)
        self._pos = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        enabled = self.isEnabled()
        off, on = QColor(t.border), QColor(t.accent)
        if not enabled:
            on = QColor(t.border)
        mix = self._pos
        track = QColor(
            int(off.red() + (on.red() - off.red()) * mix),
            int(off.green() + (on.green() - off.green()) * mix),
            int(off.blue() + (on.blue() - off.blue()) * mix),
        )

        r = QRectF(0.5, 0.5, self._W - 1, self._H - 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)

        d = self._H - 2 * self._PAD
        x = self._PAD + (self._W - 2 * self._PAD - d) * self._pos
        p.setBrush(QColor(t.accent_text if self.isChecked() and enabled else t.surface))
        if not self.isChecked():
            p.setPen(QColor(t.text_dim))
        p.drawEllipse(QRectF(x, self._PAD, d, d))

        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor(t.accent))
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), self._H / 2 + 1, self._H / 2 + 1)
