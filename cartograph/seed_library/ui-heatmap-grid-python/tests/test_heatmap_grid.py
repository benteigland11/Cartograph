import sys, os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from heatmap_grid import (
    heatmap, heatmap_compact, calendar_heatmap,
    COLOR_PRESETS, BLOCKS,
    _lerp_color, _rgb_fg, _rgb_bg, _rgb_fg_bg,
    _resolve_colors, _normalize_grid,
)


# ─── Color helpers ────────────────────────────────────────────────────

def test_lerp_single():
    assert _lerp_color(0.5, [(100, 200, 50)]) == (100, 200, 50)


def test_lerp_midpoint():
    r, g, b = _lerp_color(0.5, [(0, 0, 0), (100, 200, 100)])
    assert (r, g, b) == (50, 100, 50)


def test_lerp_boundaries():
    assert _lerp_color(0.0, [(10, 20, 30), (90, 80, 70)]) == (10, 20, 30)
    assert _lerp_color(1.0, [(10, 20, 30), (90, 80, 70)]) == (90, 80, 70)


def test_lerp_clamps():
    assert _lerp_color(-1.0, [(0, 0, 0), (255, 255, 255)]) == (0, 0, 0)
    assert _lerp_color(2.0, [(0, 0, 0), (255, 255, 255)]) == (255, 255, 255)


def test_rgb_fg():
    r = _rgb_fg(255, 0, 0, "X")
    assert "\033[38;2;255;0;0m" in r
    assert "X" in r


def test_rgb_bg():
    r = _rgb_bg(0, 255, 0, " ")
    assert "\033[48;2;0;255;0m" in r


def test_rgb_fg_bg():
    r = _rgb_fg_bg(255, 255, 255, 0, 0, 0, "A")
    assert "38;2;255;255;255" in r
    assert "48;2;0;0;0" in r


def test_resolve_preset():
    assert _resolve_colors("heat") == COLOR_PRESETS["heat"]


def test_resolve_unknown_falls_back():
    assert _resolve_colors("nonexistent") == COLOR_PRESETS["heat"]


def test_resolve_custom():
    custom = [(1, 2, 3)]
    assert _resolve_colors(custom) == custom


# ─── Normalization ────────────────────────────────────────────────────

def test_normalize_basic():
    data = [[0, 5, 10]]
    normed = _normalize_grid(data)
    assert normed[0][0] == 0.0
    assert normed[0][1] == 0.5
    assert normed[0][2] == 1.0


def test_normalize_all_same():
    data = [[5, 5, 5]]
    normed = _normalize_grid(data)
    assert all(v == 0.0 for v in normed[0])


def test_normalize_override_min_max():
    data = [[5, 10]]
    normed = _normalize_grid(data, min_val=0, max_val=20)
    assert normed[0][0] == 0.25
    assert normed[0][1] == 0.5


def test_normalize_per_row():
    data = [[0, 10], [0, 100]]
    normed = _normalize_grid(data, per_row=True)
    assert normed[0] == [0.0, 1.0]
    assert normed[1] == [0.0, 1.0]


def test_normalize_empty():
    assert _normalize_grid([]) == []
    assert _normalize_grid([[]]) == [[]]


# ─── heatmap ──────────────────────────────────────────────────────────

def test_heatmap_basic():
    data = [[1, 2], [3, 4]]
    result = heatmap(data)
    assert len(result) > 0
    assert "\033[" in result
    lines = result.strip().split("\n")
    assert len(lines) == 2


def test_heatmap_empty():
    assert heatmap([]) == ""
    assert heatmap([[]]) == ""


def test_heatmap_with_row_labels():
    data = [[1, 2], [3, 4]]
    result = heatmap(data, row_labels=["A", "B"])
    assert "A" in result
    assert "B" in result


def test_heatmap_with_col_labels():
    data = [[1, 2], [3, 4]]
    result = heatmap(data, col_labels=["X", "Y"])
    assert "X" in result
    assert "Y" in result


def test_heatmap_show_values():
    data = [[10, 20], [30, 40]]
    result = heatmap(data, show_values=True)
    assert "10" in result
    assert "40" in result


def test_heatmap_value_fmt():
    data = [[1.5, 2.7]]
    result = heatmap(data, show_values=True, value_fmt=".1f")
    assert "1.5" in result
    assert "2.7" in result


def test_heatmap_title():
    result = heatmap([[1, 2]], title="My Heatmap")
    assert "My Heatmap" in result


def test_heatmap_legend():
    result = heatmap([[0, 5, 10]], show_legend=True)
    lines = result.split("\n")
    assert len(lines) > 2  # grid + blank + legend + scale


def test_heatmap_custom_palette():
    data = [[1, 2, 3]]
    result = heatmap(data, palette=[(0, 0, 0), (255, 255, 255)])
    assert "\033[38;2;" in result


def test_heatmap_per_row():
    data = [[0, 100], [0, 1]]
    result = heatmap(data, per_row=True)
    assert len(result) > 0


def test_heatmap_all_presets():
    data = [[1, 2], [3, 4]]
    for name in COLOR_PRESETS:
        result = heatmap(data, palette=name)
        assert len(result) > 0, f"Preset '{name}' empty"


def test_heatmap_cell_width():
    data = [[1, 2]]
    r2 = heatmap(data, cell_width=2)
    r4 = heatmap(data, cell_width=4)
    # Wider cells → longer lines
    assert len(r4.split("\n")[0]) > len(r2.split("\n")[0])


def test_heatmap_row_labels_padding():
    data = [[1], [2], [3]]
    result = heatmap(data, row_labels=["short", "very long label", "x"])
    lines = result.strip().split("\n")
    # All data should start at same column
    assert len(lines) == 3


# ─── heatmap_compact ──────────────────────────────────────────────────

def test_compact_basic():
    data = [[0, 5, 10], [10, 5, 0]]
    result = heatmap_compact(data)
    lines = result.split("\n")
    assert len(lines) == 2
    assert "\033[" in result


def test_compact_empty():
    assert heatmap_compact([]) == ""
    assert heatmap_compact([[]]) == ""


def test_compact_single_cell():
    result = heatmap_compact([[5]], min_val=0, max_val=10)
    assert len(result) > 0


def test_compact_custom_palette():
    result = heatmap_compact([[1, 2, 3]], palette="viridis")
    assert "\033[" in result


# ─── calendar_heatmap ─────────────────────────────────────────────────

def test_calendar_basic():
    values = [i % 5 for i in range(56)]  # 8 weeks
    result = calendar_heatmap(values)
    lines = result.split("\n")
    # 7 day rows + blank + legend
    assert len(lines) == 9


def test_calendar_empty():
    assert calendar_heatmap([]) == ""


def test_calendar_no_legend():
    values = [1, 2, 3, 4, 5, 6, 7]
    result = calendar_heatmap(values, show_legend=False)
    lines = result.split("\n")
    assert len(lines) == 7  # just the 7 day rows


def test_calendar_custom_weeks():
    values = [1] * 70
    result = calendar_heatmap(values, weeks=10)
    lines = [l for l in result.split("\n") if l.strip()]
    # Should have day rows starting with M, W, F, S
    assert lines[0].startswith("M")


def test_calendar_custom_palette():
    values = list(range(28))
    result = calendar_heatmap(values, palette="blues")
    assert "\033[" in result


def test_calendar_day_labels():
    values = list(range(7))
    result = calendar_heatmap(values, show_legend=False)
    lines = result.split("\n")
    assert lines[0].startswith("M")
    assert lines[2].startswith("W")
    assert lines[4].startswith("F")
    assert lines[6].startswith("S")
