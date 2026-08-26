from pathlib import Path

from crystal_viewer.ui.theme import application_style


def test_checkbox_style_uses_explicit_checked_indicator_asset() -> None:
    style = application_style()

    assert "QCheckBox::indicator:checked" in style
    marker = "checkmark.svg"
    assert marker in style
    assert (Path(__file__).parents[1] / "src/crystal_viewer/ui/assets" / marker).is_file()


def test_checkbox_style_defines_unchecked_and_checked_states() -> None:
    style = application_style()

    assert "QCheckBox::indicator {" in style
    assert "QCheckBox::indicator:checked" in style
    assert "background: #087cc8" in style
