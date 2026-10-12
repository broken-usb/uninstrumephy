from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.effects_spec import EffectSpec, ParamSpec
from gui.widgets import Switch


class EffectWidget(QFrame):
    """
    Widget modular e compacto para representação de cada efeito.
    Otimizado com margens reduzidas para alta densidade em telas 1280x720.
    """

    changed = pyqtSignal()

    def __init__(self, spec: EffectSpec, parent=None) -> None:
        super().__init__(parent)
        self.spec = spec
        self._sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}

        # Visual do cartão definido em gui/theme.py (seletor `EffectWidget`).
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel(spec.name)
        title.setProperty("role", "title")
        header.addWidget(title)
        header.addStretch(1)

        # Mantém o nome `checkbox_active` por compatibilidade: o Switch tem a
        # mesma API (isChecked / setChecked / toggled).
        self.checkbox_active = Switch()
        self.checkbox_active.setToolTip(f"Ativar ou desativar: {spec.name}")
        self.checkbox_active.setAccessibleName(f"{spec.name} ativo")
        header.addWidget(self.checkbox_active)
        layout.addLayout(header)
        self.checkbox_active.toggled.connect(self.changed.emit)

        for param in spec.params:
            layout.addLayout(self._build_param_row(param))

    def _format_value(self, param: ParamSpec, value: int) -> str:
        if param.format_display is not None:
            return param.format_display(value)
        return f"{value}{param.unit}"

    def _build_param_row(self, param: ParamSpec) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        name_label = QLabel(param.label)
        name_label.setMinimumWidth(100)
        name_label.setProperty("role", "param")
        row.addWidget(name_label)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(param.min_value)
        slider.setMaximum(param.max_value)
        slider.setValue(param.default)
        slider.setFixedHeight(22)
        slider.setAccessibleName(param.label)
        slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(slider)

        value_label = QLabel(self._format_value(param, param.default))
        value_label.setMinimumWidth(65)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_label.setProperty("role", "value")
        row.addWidget(value_label)

        slider.valueChanged.connect(
            lambda v, p=param, lbl=value_label: lbl.setText(self._format_value(p, v))
        )
        slider.valueChanged.connect(self.changed.emit)

        self._sliders[param.field_name] = slider
        self._value_labels[param.field_name] = value_label

        return row

    def is_active(self) -> bool:
        return self.checkbox_active.isChecked()

    def set_active(self, active: bool) -> None:
        self.checkbox_active.setChecked(active)

    def get_param_value(self, field_name: str) -> int:
        return self._sliders[field_name].value()

    def set_param_value(self, field_name: str, value: int) -> None:
        slider = self._sliders[field_name]
        clamped = max(slider.minimum(), min(slider.maximum(), value))
        slider.setValue(clamped)

    def to_struct_fields(self) -> dict:
        fields = {self.spec.active_field: self.is_active()}
        for param in self.spec.params:
            ui_value = self.get_param_value(param.field_name)
            fields[param.field_name] = param.to_struct(ui_value)
        return fields

    def from_struct_fields(self, state) -> None:
        self.set_active(bool(getattr(state, self.spec.active_field)))
        for param in self.spec.params:
            struct_value = getattr(state, param.field_name)
            ui_value = param.from_struct(struct_value)
            self.set_param_value(param.field_name, ui_value)