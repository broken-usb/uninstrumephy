from __future__ import annotations

import json
import logging
from pathlib import Path

from core.effects_spec import EFFECT_SPECS

logger = logging.getLogger(__name__)

# Diretório padrão onde os presets são salvos. Fica dentro da pasta do
# projeto por padrão, para não exigir permissões especiais nem depender
# de convenções de "pasta de config" por sistema operacional.
DEFAULT_PRESETS_DIR = Path("presets")

# Versão do formato do arquivo de preset. Incrementar se o layout do
# JSON mudar de forma incompatível no futuro (ex.: campos renomeados).
PRESET_FORMAT_VERSION = 1


class PresetError(Exception):
    """Erro ao salvar, carregar ou validar um preset."""


def _known_param_fields(effect_key: str) -> set[str]:
    for spec in EFFECT_SPECS:
        if spec.key == effect_key:
            return {p.field_name for p in spec.params}
    return set()


def build_preset_dict(effect_widgets: dict) -> dict:
    """
    Monta o dicionário de preset a partir do estado atual dos
    EffectWidgets da aba de Hardware.

    Os valores salvos são "de exibição" (o que aparece nos sliders,
    ex.: 21 para 21%), não os valores já convertidos para a struct —
    isso mantém o preset legível/editável manualmente e resiliente a
    mudanças futuras nas fórmulas de conversão em effects_spec.py.

    Args:
        effect_widgets: dict {key: EffectWidget}, como mantido por
            TabHardware.effect_widgets.

    Returns:
        {
            "format_version": 1,
            "effects": {
                "gate": {"active": True, "params": {"gate_threshold": -46}},
                "overdrive": {"active": False, "params": {"dist_drive": 21, "dist_level": 80}},
                ...
            }
        }
    """
    effects_data = {}
    for key, widget in effect_widgets.items():
        params = {
            param.field_name: widget.get_param_value(param.field_name)
            for param in widget.spec.params
        }
        effects_data[key] = {
            "active": widget.is_active(),
            "params": params,
        }

    return {
        "format_version": PRESET_FORMAT_VERSION,
        "effects": effects_data,
    }


def apply_preset_dict(preset: dict, effect_widgets: dict) -> list[str]:
    """
    Aplica um dicionário de preset (no formato de build_preset_dict) aos
    EffectWidgets fornecidos.

    Efeitos ou parâmetros presentes no preset mas que não existem mais
    nos EffectWidgets atuais (ex.: preset salvo de uma versão com mais
    efeitos do que a atual) são ignorados silenciosamente — apenas
    registrados no log e devolvidos como avisos, sem interromper a
    aplicação do restante do preset.

    Returns:
        Lista de mensagens de aviso (vazia se tudo foi aplicado sem
        problemas), útil para exibir ao usuário caso o preset seja
        parcialmente compatível.
    """
    warnings: list[str] = []
    effects_data = preset.get("effects", {})

    if not isinstance(effects_data, dict):
        msg = "Campo 'effects' do preset está malformado (esperava um objeto) — nenhum efeito foi aplicado."
        logger.warning(msg)
        return [msg]

    for key, effect_state in effects_data.items():
        widget = effect_widgets.get(key)
        if widget is None:
            msg = f"Efeito '{key}' do preset não existe na versão atual — ignorado."
            logger.warning(msg)
            warnings.append(msg)
            continue

        if not isinstance(effect_state, dict):
            msg = f"Estado do efeito '{key}' no preset está malformado — ignorado."
            logger.warning(msg)
            warnings.append(msg)
            continue

        widget.set_active(bool(effect_state.get("active", False)))

        params = effect_state.get("params", {})
        if not isinstance(params, dict):
            msg = f"Parâmetros do efeito '{key}' no preset estão malformados — ignorados."
            logger.warning(msg)
            warnings.append(msg)
            continue

        for field_name, value in params.items():
            if field_name not in _known_param_fields(key):
                msg = (
                    f"Parâmetro '{field_name}' do efeito '{key}' não existe "
                    f"na versão atual — ignorado."
                )
                logger.warning(msg)
                warnings.append(msg)
                continue
            try:
                widget.set_param_value(field_name, int(value))
            except (TypeError, ValueError):
                msg = (
                    f"Valor inválido para o parâmetro '{field_name}' do "
                    f"efeito '{key}' no preset — ignorado."
                )
                logger.warning(msg)
                warnings.append(msg)

    return warnings


def list_presets(presets_dir: Path = DEFAULT_PRESETS_DIR) -> list[str]:
    """Lista os nomes (sem extensão) dos presets salvos em presets_dir."""
    if not presets_dir.exists():
        return []
    return sorted(p.stem for p in presets_dir.glob("*.json"))


def save_preset(
    name: str,
    effect_widgets: dict,
    presets_dir: Path = DEFAULT_PRESETS_DIR,
) -> Path:
    """
    Salva o estado atual dos EffectWidgets como um preset nomeado.

    Args:
        name: Nome do preset (usado como nome do arquivo, sem extensão).
        effect_widgets: dict {key: EffectWidget}.
        presets_dir: Diretório onde o preset será salvo.

    Returns:
        Caminho do arquivo salvo.

    Raises:
        PresetError: Se o nome for inválido ou a escrita falhar.
    """
    safe_name = name.strip()
    if not safe_name:
        raise PresetError("O nome do preset não pode ser vazio.")

    # Remove caracteres problemáticos para nome de arquivo, mantendo o
    # preset legível (evita surpresas em diferentes sistemas de arquivos)
    invalid_chars = '/\\:*?"<>|'
    if any(c in safe_name for c in invalid_chars):
        raise PresetError(
            f"O nome do preset não pode conter os caracteres: {invalid_chars}"
        )

    presets_dir.mkdir(parents=True, exist_ok=True)
    file_path = presets_dir / f"{safe_name}.json"

    preset_dict = build_preset_dict(effect_widgets)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(preset_dict, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        raise PresetError(f"Falha ao salvar o preset em {file_path}: {exc}") from exc

    logger.info(f"Preset '{safe_name}' salvo em {file_path}")
    return file_path


def load_preset(
    name: str,
    effect_widgets: dict,
    presets_dir: Path = DEFAULT_PRESETS_DIR,
) -> list[str]:
    """
    Carrega um preset salvo e aplica seus valores aos EffectWidgets.

    Returns:
        Lista de avisos sobre efeitos/parâmetros do preset que não
        existem na versão atual (ver apply_preset_dict). Vazia se o
        preset foi aplicado sem ressalvas.

    Raises:
        PresetError: Se o arquivo não existir ou estiver malformado.
    """
    file_path = presets_dir / f"{name}.json"

    if not file_path.exists():
        raise PresetError(f"Preset '{name}' não encontrado em {presets_dir}.")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            preset_dict = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise PresetError(f"Falha ao ler o preset '{name}': {exc}") from exc

    if preset_dict.get("format_version") != PRESET_FORMAT_VERSION:
        logger.warning(
            f"Preset '{name}' tem format_version="
            f"{preset_dict.get('format_version')!r}, esperado "
            f"{PRESET_FORMAT_VERSION}. Tentando aplicar mesmo assim."
        )

    warnings = apply_preset_dict(preset_dict, effect_widgets)
    logger.info(f"Preset '{name}' carregado de {file_path}")
    return warnings


def delete_preset(name: str, presets_dir: Path = DEFAULT_PRESETS_DIR) -> None:
    """Remove um preset salvo. Não lança erro se ele não existir."""
    file_path = presets_dir / f"{name}.json"
    if file_path.exists():
        file_path.unlink()
        logger.info(f"Preset '{name}' removido ({file_path}).")
