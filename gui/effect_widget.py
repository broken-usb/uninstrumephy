from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QCheckBox,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.effects_spec import EffectSpec, ParamSpec


class EffectWidget(QFrame):
    """
    Widget que renderiza um efeito completo (checkbox "ativo" + um slider
    por parâmetro, cada um com seu label de nome e de valor atual) a
    partir de uma única EffectSpec.

    Este widget é a peça central da modularidade da aba de Hardware:
    adicionar um novo efeito ao pedal não exige criar um novo widget,
    nem editar o .ui — basta acrescentar uma EffectSpec em
    core/effects_spec.py, e um EffectWidget correspondente é criado
    dinamicamente pela aba de Hardware (ver TabHardware._build_effect_widgets).

    Emite `changed` sempre que o usuário altera o estado ativo ou
    qualquer parâmetro, para quem quiser reagir a mudanças em tempo real
    (não usado hoje, mas disponível para uso futuro, ex.: preview ao vivo).
    """

    changed = pyqtSignal()

    def __init__(self, spec: EffectSpec, parent=None) -> None:
        super().__init__(parent)
        self.spec = spec
        self._sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}

        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self.checkbox_active = QCheckBox(spec.name)
        layout.addWidget(self.checkbox_active)
        self.checkbox_active.toggled.connect(self.changed.emit)

        for param in spec.params:
            layout.addLayout(self._build_param_row(param))

    def _build_param_row(self, param: ParamSpec) -> QHBoxLayout:
        row = QHBoxLayout()

        name_label = QLabel(f"{param.label}:")
        name_label.setMinimumWidth(90)
        row.addWidget(name_label)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(param.min_value)
        slider.setMaximum(param.max_value)
        slider.setValue(param.default)
        slider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        row.addWidget(slider)

        value_label = QLabel(f"{param.default}{param.unit}")
        value_label.setMinimumWidth(60)
        row.addWidget(value_label)

        slider.valueChanged.connect(
            lambda v, u=param.unit, lbl=value_label: lbl.setText(f"{v}{u}")
        )
        slider.valueChanged.connect(self.changed.emit)

        self._sliders[param.field_name] = slider
        self._value_labels[param.field_name] = value_label

        return row

    # API pública

    def is_active(self) -> bool:
        return self.checkbox_active.isChecked()

    def set_active(self, active: bool) -> None:
        self.checkbox_active.setChecked(active)

    def get_param_value(self, field_name: str) -> int:
        """Retorna o valor de exibição atual (ex.: 21, em % ou dB) de um parâmetro."""
        return self._sliders[field_name].value()

    def set_param_value(self, field_name: str, value: int) -> None:
        """Define o valor de exibição de um parâmetro, respeitando os limites do slider."""
        slider = self._sliders[field_name]
        clamped = max(slider.minimum(), min(slider.maximum(), value))
        slider.setValue(clamped)

    def to_struct_fields(self) -> dict:
        """
        Retorna um dicionário {nome_do_campo_na_struct: valor} pronto
        para popular um PedalState, já convertendo cada parâmetro de
        exibição para o valor real via ParamSpec.to_struct.
        """
        fields = {self.spec.active_field: self.is_active()}
        for param in self.spec.params:
            ui_value = self.get_param_value(param.field_name)
            fields[param.field_name] = param.to_struct(ui_value)
        return fields

    def from_struct_fields(self, state) -> None:
        """
        Popula o widget a partir de um PedalState existente (ou qualquer
        objeto com os atributos correspondentes), convertendo os valores
        reais da struct de volta para valores de exibição via
        ParamSpec.from_struct.
        """
        self.set_active(bool(getattr(state, self.spec.active_field)))
        for param in self.spec.params:
            struct_value = getattr(state, param.field_name)
            ui_value = param.from_struct(struct_value)
            self.set_param_value(param.field_name, ui_value)
