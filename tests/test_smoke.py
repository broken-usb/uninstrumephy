"""Testes básicos de fumaça para validar importações e carregamento dos módulos."""

def test_core_imports():
    import core.analyzer
    import core.effects_spec
    import core.hardware
    import core.presets
    assert True

def test_gui_imports():
    # Testa se os módulos da interface importam sem erros de sintaxe
    from gui.tab_demucs import TabDemucs
    from gui.tab_tonematching import TabToneMatching
    from gui.tab_hardware import TabHardware
    assert TabDemucs is not None
    assert TabToneMatching is not None
    assert TabHardware is not None