from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class ParamSpec:
    field_name: str
    label: str
    min_value: int
    max_value: int
    default: int
    unit: str = ""
    to_struct: Callable[[int], float] = lambda v: float(v)
    from_struct: Callable[[float], int] = lambda v: round(v)
    format_display: Callable[[int], str] | None = None


@dataclass(frozen=True)
class EffectSpec:
    key: str
    name: str
    active_field: str
    params: list[ParamSpec] = field(default_factory=list)


# Fórmulas de conversão técnica entre UI e DSP
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


def _db_to_linear(db: int) -> float:
    return float(10.0 ** (db / 20.0))


def _linear_to_db(v: float) -> int:
    return round(20.0 * math.log10(max(1e-4, v)))


CAB_NAMES = [
    "Deluxe Oxford (Big)",
    "Deluxe Oxford (Lean)",
    "EV Mix B",
    "EV Mix D",
    "Mesa OS 4x12 (57+160)",
]


EFFECT_SPECS: list[EffectSpec] = [
    # 1. Noise Gate
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
                unit=" dB",
                to_struct=_db_to_linear,
                from_struct=_linear_to_db,
            ),
        ],
    ),
    # 2. Compressor
    EffectSpec(
        key="comp",
        name="Compressor",
        active_field="comp_active",
        params=[
            ParamSpec(
                field_name="comp_threshold",
                label="Threshold",
                min_value=5,
                max_value=95,
                default=40,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
            ParamSpec(
                field_name="comp_ratio",
                label="Ratio",
                min_value=10,
                max_value=100,
                default=30,
                to_struct=lambda v: v / 10.0,
                from_struct=lambda v: round(v * 10.0),
                format_display=lambda v: f"{v / 10.0:.1f}:1",
            ),
            ParamSpec(
                field_name="comp_makeup_gain",
                label="Makeup Gain",
                min_value=10,
                max_value=40,
                default=10,
                to_struct=lambda v: v / 10.0,
                from_struct=lambda v: round(v * 10.0),
                format_display=lambda v: f"{v / 10.0:.1f}x",
            ),
        ],
    ),
    # 3. Auto-Wah
    EffectSpec(
        key="wah",
        name="Auto-Wah",
        active_field="wah_active",
        params=[
            ParamSpec(
                field_name="wah_sensitivity",
                label="Sensibilidade",
                min_value=0,
                max_value=100,
                default=50,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
            ParamSpec(
                field_name="wah_base_freq",
                label="Freq. Base",
                min_value=100,
                max_value=1000,
                default=350,
                unit=" Hz",
            ),
            ParamSpec(
                field_name="wah_resonance",
                label="Ressonância",
                min_value=10,
                max_value=95,
                default=60,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
        ],
    ),
    # 4. Overdrive
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
                unit=" %",
                to_struct=_drive_to_struct,
                from_struct=_drive_from_struct,
            ),
            ParamSpec(
                field_name="dist_tone",
                label="Tone",
                min_value=0,
                max_value=100,
                default=50,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
            ParamSpec(
                field_name="dist_level",
                label="Level",
                min_value=0,
                max_value=100,
                default=80,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
        ],
    ),
    # 5. Equalizador Paramétrico (4 Bandas)
    EffectSpec(
        key="eq",
        name="Equalizador (4 Bandas)",
        active_field="eq_active",
        params=[
            ParamSpec(
                field_name="eq_low_gain",
                label="Graves (100 Hz)",
                min_value=-12,
                max_value=12,
                default=0,
                format_display=lambda v: f"{v:+d} dB",
            ),
            ParamSpec(
                field_name="eq_mid1_gain",
                label="Médios 1 (500 Hz)",
                min_value=-12,
                max_value=12,
                default=0,
                format_display=lambda v: f"{v:+d} dB",
            ),
            ParamSpec(
                field_name="eq_mid2_gain",
                label="Médios 2 (1.5 kHz)",
                min_value=-12,
                max_value=12,
                default=0,
                format_display=lambda v: f"{v:+d} dB",
            ),
            ParamSpec(
                field_name="eq_high_gain",
                label="Agudos (4.5 kHz)",
                min_value=-12,
                max_value=12,
                default=0,
                format_display=lambda v: f"{v:+d} dB",
            ),
        ],
    ),
    # 6. Modulação (Chorus)
    EffectSpec(
        key="mod",
        name="Chorus / Modulação",
        active_field="mod_active",
        params=[
            ParamSpec(
                field_name="mod_rate_hz",
                label="Rate",
                min_value=2,
                max_value=50,
                default=15,
                to_struct=lambda v: v / 10.0,
                from_struct=lambda v: round(v * 10.0),
                format_display=lambda v: f"{v / 10.0:.1f} Hz",
            ),
            ParamSpec(
                field_name="mod_depth",
                label="Depth",
                min_value=0,
                max_value=100,
                default=60,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
            ParamSpec(
                field_name="mod_mix",
                label="Mix",
                min_value=0,
                max_value=100,
                default=50,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
        ],
    ),
    # 7. Tape Delay
    EffectSpec(
        key="delay",
        name="Tape Delay",
        active_field="delay_active",
        params=[
            ParamSpec(
                field_name="delay_time_samples",
                label="Time",
                min_value=20,
                max_value=1200,
                default=340,
                unit=" ms",
                to_struct=_ms_to_samples,
                from_struct=_samples_to_ms,
            ),
            ParamSpec(
                field_name="delay_feedback",
                label="Feedback",
                min_value=0,
                max_value=100,
                default=42,
                unit=" %",
                to_struct=_feedback_to_struct,
                from_struct=_feedback_from_struct,
            ),
            ParamSpec(
                field_name="delay_mix",
                label="Mix",
                min_value=0,
                max_value=100,
                default=30,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
        ],
    ),
    # 8. Reverb Dattorro Plate
    EffectSpec(
        key="reverb",
        name="Reverb Plate",
        active_field="reverb_active",
        params=[
            ParamSpec(
                field_name="reverb_decay",
                label="Decay",
                min_value=10,
                max_value=95,
                default=50,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
            ParamSpec(
                field_name="reverb_damping",
                label="Damping",
                min_value=0,
                max_value=80,
                default=30,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
            ParamSpec(
                field_name="reverb_mix",
                label="Mix",
                min_value=0,
                max_value=100,
                default=25,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
        ],
    ),
    # 9. Cab Sim / IR
    EffectSpec(
        key="cab",
        name="Simulador de Gabinete (IR)",
        active_field="cab_active",
        params=[
            ParamSpec(
                field_name="cab_index",
                label="Modelo IR",
                min_value=0,
                max_value=4,
                default=0,
                format_display=lambda v: CAB_NAMES[v] if 0 <= v < len(CAB_NAMES) else f"Slot {v}",
            ),
        ],
    ),
    # 10. Bitcrusher
    EffectSpec(
        key="bitcrusher",
        name="Bitcrusher",
        active_field="bitcrusher_active",
        params=[
            ParamSpec(
                field_name="bitcrusher_bits",
                label="Resolução",
                min_value=4,
                max_value=16,
                default=8,
                unit=" bits",
            ),
            ParamSpec(
                field_name="bitcrusher_hold",
                label="Hold",
                min_value=1,
                max_value=16,
                default=4,
                unit=" amos.",
            ),
            ParamSpec(
                field_name="bitcrusher_mix",
                label="Mix",
                min_value=0,
                max_value=100,
                default=50,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
        ],
    ),
    # 11. Tremolo
    EffectSpec(
        key="tremolo",
        name="Tremolo",
        active_field="tremolo_active",
        params=[
            ParamSpec(
                field_name="tremolo_rate_hz",
                label="Rate",
                min_value=1,
                max_value=120,
                default=40,
                to_struct=lambda v: v / 10.0,
                from_struct=lambda v: round(v * 10.0),
                format_display=lambda v: f"{v / 10.0:.1f} Hz",
            ),
            ParamSpec(
                field_name="tremolo_depth",
                label="Depth",
                min_value=0,
                max_value=100,
                default=50,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
            ParamSpec(
                field_name="tremolo_shape",
                label="Forma LFO",
                min_value=0,
                max_value=1,
                default=0,
                format_display=lambda v: "Senoide" if v == 0 else "Triangular",
            ),
            ParamSpec(
                field_name="tremolo_mix",
                label="Mix",
                min_value=0,
                max_value=100,
                default=100,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
        ],
    ),
    # 12. Phaser
    EffectSpec(
        key="phaser",
        name="Phaser (4 Estágios)",
        active_field="phaser_active",
        params=[
            ParamSpec(
                field_name="phaser_rate_hz",
                label="Rate",
                min_value=5,
                max_value=400,
                default=60,
                to_struct=lambda v: v / 100.0,
                from_struct=lambda v: round(v * 100.0),
                format_display=lambda v: f"{v / 100.0:.2f} Hz",
            ),
            ParamSpec(
                field_name="phaser_depth",
                label="Depth",
                min_value=0,
                max_value=100,
                default=70,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
            ParamSpec(
                field_name="phaser_feedback",
                label="Feedback",
                min_value=0,
                max_value=70,
                default=30,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
            ParamSpec(
                field_name="phaser_mix",
                label="Mix",
                min_value=0,
                max_value=100,
                default=50,
                unit=" %",
                to_struct=_percent_to_struct,
                from_struct=_percent_from_struct,
            ),
        ],
    ),
]