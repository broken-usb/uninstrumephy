"""Pastas de dados (core/paths.py) e presets (core/presets.py)."""

import pytest

from core import paths


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv("UNINSTRUMEPHY_DATA_DIR", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    return tmp_path


def test_codigo_fonte_usa_pastas_do_projeto(clean_env):
    assert not paths.is_packaged()
    assert paths.data_dir() == paths.PROJECT_ROOT / "output"
    assert paths.presets_dir() == paths.BUNDLED_PRESETS_DIR


def test_appimage_usa_pasta_do_usuario(clean_env, monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/tmp/Uninstrumephy.AppImage")
    assert paths.is_packaged()
    assert paths.data_dir() == clean_env / "xdg" / "uninstrumephy"
    assert paths.logs_dir().parent == paths.data_dir()


def test_appimage_copia_presets_incluidos_uma_vez(clean_env, monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/tmp/Uninstrumephy.AppImage")
    bundled = sorted(p.name for p in paths.BUNDLED_PRESETS_DIR.glob("*.json"))
    user_dir = paths.presets_dir()
    assert user_dir != paths.BUNDLED_PRESETS_DIR
    assert sorted(p.name for p in user_dir.glob("*.json")) == bundled

    # Um preset excluído pelo usuário não volta na próxima execução.
    (user_dir / bundled[0]).unlink()
    paths.presets_dir()
    assert not (user_dir / bundled[0]).exists()


def test_variavel_de_ambiente_substitui_a_pasta(clean_env, monkeypatch):
    monkeypatch.setenv("UNINSTRUMEPHY_DATA_DIR", str(clean_env / "meus-dados"))
    assert paths.data_dir() == clean_env / "meus-dados"
    assert paths.recordings_dir() == clean_env / "meus-dados" / "recordings"


def test_presets_incluidos_carregam_na_aba_real(qapp):
    from core import presets
    from gui.tab_hardware import TabHardware

    tab = TabHardware()
    names = presets.list_presets(paths.BUNDLED_PRESETS_DIR)
    assert {"Ambient Phaser", "Blues Drive", "Clean Chorus", "Lo-Fi Tremolo"} <= set(names)
    for name in names:
        assert presets.load_preset(name, tab.effect_widgets, paths.BUNDLED_PRESETS_DIR) == []


def test_salvar_carregar_e_excluir_preset(qapp, tmp_path):
    from core import presets
    from gui.tab_hardware import TabHardware

    tab = TabHardware()
    tab.effect_widgets["overdrive"].set_param_value("dist_drive", 77)
    presets.save_preset("Meu Som", tab.effect_widgets, tmp_path)
    tab.effect_widgets["overdrive"].set_param_value("dist_drive", 10)
    presets.load_preset("Meu Som", tab.effect_widgets, tmp_path)
    assert tab.effect_widgets["overdrive"].get_param_value("dist_drive") == 77
    presets.delete_preset("Meu Som", tmp_path)
    assert presets.list_presets(tmp_path) == []
    with pytest.raises(presets.PresetError):
        presets.save_preset("nome/inválido", tab.effect_widgets, tmp_path)
