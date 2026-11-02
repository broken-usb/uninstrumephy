from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QLabel, QSlider, QWidget
from PyQt6.QtCore import pyqtSignal

from core.effects_spec import EffectSpec, ParamSpec
from gui.ui_loader import load_ui_file


class EffectWidget(QFrame):
    """
    Widget modular e compacto para representação de cada efeito.
    Otimizado com margens reduzidas para alta densidade em telas 1280x720.

    Layout em gui/effect_widget.ui (cabeçalho com título e interruptor) e
    gui/effect_param_row.ui (uma linha por parâmetro do EffectSpec). Visual
    do cartão em gui/theme.py (seletor `EffectWidget`).
    """

    changed = pyqtSignal()

    def __init__(self, spec: EffectSpec, parent=None) -> None:
        super().__init__(parent)
        load_ui_file("effect_widget.ui", self)
        self.spec = spec
        self._sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}

        self.lbl_title.setText(spec.name)

        # Mantém o nome `checkbox_active` por compatibilidade: o Switch tem a
        # mesma API (isChecked / setChecked / toggled).
        self.checkbox_active.setToolTip(f"Ativar ou desativar: {spec.name}")
        self.checkbox_active.setAccessibleName(f"{spec.name} ativo")
        self.checkbox_active.toggled.connect(self.changed.emit)

        for param in spec.params:
            self.layout_root.addWidget(self._build_param_row(param))

    def _format_value(self, param: ParamSpec, value: int) -> str:
        if param.format_display is not None:
            return param.format_display(value)
        return f"{value}{param.unit}"

    def _build_param_row(self, param: ParamSpec) -> QWidget:
        row = load_ui_file("effect_param_row.ui", QWidget(self))
        row.setObjectName(f"row_{param.field_name}")

        row.lbl_name.setText(param.label)

        slider: QSlider = row.slider
        slider.setMinimum(param.min_value)
        slider.setMaximum(param.max_value)
        slider.setValue(param.default)
        slider.setAccessibleName(param.label)

        value_label: QLabel = row.lbl_value
        value_label.setText(self._format_value(param, param.default))

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