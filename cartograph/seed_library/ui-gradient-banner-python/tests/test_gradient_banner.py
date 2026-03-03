import sys, os
from unittest.mock import patch
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.gradient_banner import (
    gradient_banner, gradient_banner_frame, animate_banner,
    get_font_chars, GRADIENT_PRESETS, FONT_HEIGHT,
    _lerp_color, _rgb_fg, _resolve_colors, _text_to_grid, _FONT,
)


# ─── Color helpers ────────────────────────────────────────────────────

def test_lerp_single_color():
    assert _lerp_color(0.5, [(255, 0, 0)]) == (255, 0, 0)


def test_lerp_two_colors_midpoint():
    r, g, b = _lerp_color(0.5, [(0, 0, 0), (100, 200, 100)])
    assert r == 50
    assert g == 100
    assert b == 50


def test_lerp_boundaries():
    assert _lerp_color(0.0, [(10, 20, 30), (100, 200, 255)]) == (10, 20, 30)
    assert _lerp_color(1.0, [(10, 20, 30), (100, 200, 255)]) == (100, 200, 255)


def test_lerp_clamps():
    assert _lerp_color(-1.0, [(0, 0, 0), (255, 255, 255)]) == (0, 0, 0)
    assert _lerp_color(2.0, [(0, 0, 0), (255, 255, 255)]) == (255, 255, 255)


def test_lerp_three_colors():
    r, g, b = _lerp_color(0.5, [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    assert (r, g, b) == (0, 255, 0)  # midpoint is exactly the second color


def test_rgb_fg():
    result = _rgb_fg(255, 0, 128, "X")
    assert "\033[38;2;255;0;128m" in result
    assert "X" in result
    assert "\033[0m" in result


def test_resolve_preset():
    colors = _resolve_colors("rainbow")
    assert colors == GRADIENT_PRESETS["rainbow"]


def test_resolve_unknown_preset_falls_back():
    colors = _resolve_colors("nonexistent")
    assert colors == GRADIENT_PRESETS["rainbow"]


def test_resolve_custom_list():
    custom = [(1, 2, 3), (4, 5, 6)]
    assert _resolve_colors(custom) == custom


# ─── Font / grid ──────────────────────────────────────────────────────

def test_text_to_grid_basic():
    grid = _text_to_grid("A")
    assert len(grid) == FONT_HEIGHT
    assert all(len(row) == len(_FONT["A"][0]) for row in grid)


def test_text_to_grid_multi_char():
    grid = _text_to_grid("AB")
    assert len(grid) == FONT_HEIGHT
    expected_width = len(_FONT["A"][0]) + len(_FONT["B"][0])
    assert all(len(row) == expected_width for row in grid)


def test_text_to_grid_lowercase_uppercased():
    grid_lower = _text_to_grid("a")
    grid_upper = _text_to_grid("A")
    assert grid_lower == grid_upper


def test_text_to_grid_unknown_char_uses_space():
    grid = _text_to_grid("@")  # not in font
    # Should be same as space
    space_grid = _text_to_grid(" ")
    assert grid == space_grid


def test_text_to_grid_empty():
    grid = _text_to_grid("")
    assert len(grid) == FONT_HEIGHT
    assert all(row == "" for row in grid)


def test_get_font_chars():
    chars = get_font_chars()
    assert "A" in chars
    assert "Z" in chars
    assert "0" in chars
    assert " " in chars
    assert len(chars) > 30


def test_font_height_consistent():
    for ch, glyph in _FONT.items():
        assert len(glyph) == FONT_HEIGHT, f"Font char '{ch}' has {len(glyph)} rows"


def test_font_width_consistent():
    for ch, glyph in _FONT.items():
        widths = [len(row) for row in glyph]
        assert len(set(widths)) == 1, f"Font char '{ch}' has inconsistent row widths: {widths}"


# ─── Static banner ────────────────────────────────────────────────────

def test_gradient_banner_produces_output():
    result = gradient_banner("HI")
    assert len(result) > 0
    assert "\n" in result


def test_gradient_banner_has_ansi():
    result = gradient_banner("AB", gradient="fire")
    assert "\033[38;2;" in result


def test_gradient_banner_horizontal():
    result = gradient_banner("OK", direction="horizontal")
    assert "\033[" in result


def test_gradient_banner_vertical():
    result = gradient_banner("OK", direction="vertical")
    assert "\033[" in result


def test_gradient_banner_no_bold():
    result = gradient_banner("X", bold=False)
    assert "\033[1m" not in result


def test_gradient_banner_bold():
    result = gradient_banner("X", bold=True)
    assert "\033[1m" in result


def test_gradient_banner_padding():
    result_0 = gradient_banner("A", padding=0)
    result_2 = gradient_banner("A", padding=2)
    lines_0 = result_0.split("\n")
    lines_2 = result_2.split("\n")
    assert len(lines_2) == len(lines_0) + 4  # 2 above + 2 below


def test_gradient_banner_custom_colors():
    result = gradient_banner("X", gradient=[(255, 0, 0), (0, 0, 255)])
    assert "\033[38;2;" in result


def test_gradient_banner_empty():
    result = gradient_banner("")
    assert result == ""


# ─── Animated frame ───────────────────────────────────────────────────

def test_frame_basic():
    frame = gradient_banner_frame("HI", offset=0.0)
    assert "\033[" in frame
    assert len(frame) > 0


def test_frame_offset_changes_output():
    f1 = gradient_banner_frame("AB", offset=0.0, wave=False)
    f2 = gradient_banner_frame("AB", offset=0.5, wave=False)
    assert f1 != f2


def test_frame_wave_off():
    frame = gradient_banner_frame("X", wave=False)
    assert len(frame) > 0


def test_frame_wave_on():
    frame = gradient_banner_frame("X", wave=True, wave_amplitude=0.2, wave_frequency=0.5)
    assert len(frame) > 0


def test_frame_vertical():
    frame = gradient_banner_frame("AB", direction="vertical", offset=0.3)
    assert "\033[" in frame


def test_frame_empty():
    assert gradient_banner_frame("") == ""


# ─── Animate (short duration) ────────────────────────────────────────

@patch('sys.stdout', new_callable=StringIO)
def test_animate_runs_and_stops(mock_out):
    animate_banner("HI", duration=0.1, fps=10)
    output = mock_out.getvalue()
    assert len(output) > 0
    # Should have hidden then shown cursor
    assert "\033[?25l" in output
    assert "\033[?25h" in output


@patch('sys.stdout', new_callable=StringIO)
def test_animate_keyboard_interrupt(mock_out):
    with patch('time.sleep', side_effect=KeyboardInterrupt):
        animate_banner("HI", fps=10)
    output = mock_out.getvalue()
    assert "\033[?25h" in output  # cursor restored


# ─── Presets ──────────────────────────────────────────────────────────

def test_all_presets_render():
    for name in GRADIENT_PRESETS:
        result = gradient_banner("OK", gradient=name)
        assert len(result) > 0, f"Preset '{name}' produced empty output"
