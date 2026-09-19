from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class ParamSpec:
    """
    Descreve um único parâmetro numérico de um efeito (ex.: "Threshold"
    do Noise Gate, "Drive" do Overdrive).

    O par (to_struct / from_struct) isola a UI do formato de armazenamento
    da struct PedalState: a UI sempre trabalha com o valor "de exibição"
    (o que aparece no slider, ex.: 21 para 21%), e essas funções convertem
    para/do valor real gravado no campo da struct (ex.: dist_drive=4.99).

    Attributes:
        field_name: Nome do atributo correspondente em PedalState.
        label: Rótulo exibido na UI (ex.: "Threshold").
        min_value / max_value: Limites do slider, em unidades de exibição.
        default: Valor inicial de exibição.
        unit: Sufixo exibido ao lado do valor (ex.: "dB", "%", "ms").
        to_struct: Converte o valor de exibição (int) para o valor real
            gravado no campo da struct. Padrão: identidade (float).
        from_struct: Converte o valor real da struct de volta para o
            valor de exibição (int), usado ao popular a UI a partir de um
            PedalState existente (ex.: state recebido, ou vindo do Tone
            Matching). Padrão: identidade (round).
    """

    field_name: str
    label: str
    min_value: int
    max_value: int
    default: int
    unit: str = ""
    to_struct: Callable[[int], float] = lambda v: float(v)
    from_struct: Callable[[float], int] = lambda v: round(v)


@dataclass(frozen=True)
class EffectSpec:
    """
    Descreve um efeito completo do pedal: seu campo "ativo" na struct e
    a lista de parâmetros que ele expõe.

    Adicionar um novo efeito ao pedal (quando o campo correspondente for
    incluído em PedalState.h pelo firmware) deve exigir apenas uma nova
    entrada em EFFECT_SPECS — nem gui/tab_hardware.py, nem
    gui/effect_widget.py, nem o .ui precisam ser tocados.
    """

    key: str                    # identificador interno único (ex.: "gate")
    name: str                   # nome exibido (ex.: "Noise Gate")
    active_field: str           # nome do campo bool em PedalState (ex.: "gate_active")
    params: list[ParamSpec] = field(default_factory=list)


# Fórmulas de conversão replicadas de sendStateToDSP() no firmware da
# Board B (UI física) — mantidas aqui para que o software desktop envie
# valores compatíveis com o que o firmware espera nesses campos.

def _drive_to_struct(pct: int) -> float:
    return 1.0 + (pct / 100.0) * 19.0


def _drive_from_struct(value: float) -> int:
    return round((value - 1.0) / 19.0 * 100.0)


def _percent_to_struct(pct: int) -> float:
    return pct / 100.0


def _percent_from_struct(value: float) -> int:
    return round(value * 100.0)


def _feedback_to_struct(pct: int) -> float:
    return (pct / 100.0) * 0.95


def _feedback_from_struct(value: float) -> int:
    return round(value / 0.95 * 100.0)


def _ms_to_samples(ms: int, sample_rate: int = 44100) -> int:
    return round((ms * sample_rate) / 1000.0)


def _samples_to_ms(samples: float, sample_rate: int = 44100) -> int:
    return round((samples * 1000.0) / sample_rate)


# Especificação de todos os efeitos atualmente suportados pelo firmware.
# Baseada nos limites (min/max/step) definidos no array `effects[]` do
# código da Board B (UI física), para manter a UI do software desktop
# consistente com a UI física do pedal.
#
# Para adicionar um novo efeito no futuro (ex.: quando o Equalizador for
# habilitado no firmware), basta acrescentar uma nova EffectSpec aqui —
# ela aparecerá automaticamente na aba de Hardware.
EFFECT_SPECS: list[EffectSpec] = [
    EffectSpec(
        key="gate",
        name="Noise Gate",
        active_field="gate_active",
        params=[
            ParamSpec(
                field_name="gate_threshold",
                label="Threshold",
                min_value=-80,
                max_value=0,
                default=-46,
                unit="dB",
                to_struct=lambda v: float(v),
                from_struct=lambda v: round(v),
            ),
        ],
    ),
    EffectSpec(
        key="overdrive",
        name="Overdrive",
        active_field="dist_active",
        params=[
            ParamSpec(
                field_name="dist_drive",
                label="Drive",
                min_value=0,
                max_value=100,
                default=21,
                unit="%",
                to_struct=_drive_to_struct,
                from_struct=_drive_from_struct,
            ),
            ParamSpec(
                field_name="dist_level",
                label="Level",
                min_value=0,
                max_value=100,
                default=80,
                unit="%",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
        ],
    ),
    EffectSpec(
        key="delay",
        name="Delay",
        active_field="delay_active",
        params=[
            ParamSpec(
                field_name="delay_time_samples",
                label="Time",
                min_value=20,
                max_value=1200,
                default=340,
                unit="ms",
                to_struct=_ms_to_samples,
                from_struct=_samples_to_ms,
            ),
            ParamSpec(
                field_name="delay_feedback",
                label="Feedback",
                min_value=0,
                max_value=100,
                default=42,
                unit="%",
                to_struct=_feedback_to_struct,
                from_struct=_feedback_from_struct,
            ),
            ParamSpec(
                field_name="delay_mix",
                label="Mix",
                min_value=0,
                max_value=100,
                default=30,
                unit="%",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
        ],
    ),
]
