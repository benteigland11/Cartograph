import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from sparkline_chart import sparkline, sparkline_multi, sparkbar, _resample, BLOCKS


# ─── sparkline ────────────────────────────────────────────────────────

def test_empty_data():
    assert sparkline([]) == ""


def test_single_value():
    result = sparkline([5])
    assert len(result) == 1
    assert result in BLOCKS


def test_all_same_values():
    result = sparkline([3, 3, 3, 3])
    # All same → all map to same block
    assert len(set(result)) == 1


def test_ascending():
    result = sparkline([0, 1, 2, 3, 4, 5, 6, 7])
    # First char should be lowest block, last should be highest
    assert result[0] == BLOCKS[0] or result[0] == BLOCKS[1]
    assert result[-1] == BLOCKS[-1]


def test_length_matches_data():
    data = [1, 5, 3, 9, 2, 7]
    result = sparkline(data)
    assert len(result) == len(data)


def test_min_max_override():
    result = sparkline([5, 5, 5], min_val=0, max_val=10)
    # All values at 50% → should be mid-range block
    for ch in result:
        assert ch in BLOCKS[3:6]


def test_width_resampling():
    data = list(range(100))
    result = sparkline(data, width=10)
    # strip ANSI if any — no color here so plain
    assert len(result) == 10


def test_label():
    result = sparkline([1, 2, 3], label="CPU")
    assert result.startswith("CPU ")


def test_show_range():
    result = sparkline([1.0, 5.0, 3.0], show_range=True)
    assert "[1.0, 5.0]" in result


def test_show_current():
    result = sparkline([1, 2, 3], show_current=True)
    assert "3.0" in result


def test_color_produces_ansi():
    result = sparkline([1, 5, 9], color="green")
    assert "\033[" in result


def test_color_gradient():
    result = sparkline([0, 5, 10], color="fire")
    assert "\033[38;2;" in result


def test_custom_color_rgb():
    result = sparkline([1, 2, 3], color=[(255, 0, 0), (0, 255, 0)])
    assert "\033[38;2;" in result


def test_markers():
    result = sparkline([5, 1, 9, 3], marker_min=True, marker_max=True)
    # Should contain underline (4) and bold (1) ANSI codes
    assert "\033[4m" in result
    assert "\033[1m" in result


# ─── sparkline_multi ──────────────────────────────────────────────────

def test_multi_empty():
    assert sparkline_multi({}) == ""


def test_multi_basic():
    result = sparkline_multi({
        "CPU": [10, 40, 80, 60],
        "MEM": [20, 30, 50, 90],
    })
    lines = result.split("\n")
    assert len(lines) == 2


def test_multi_aligned_labels():
    result = sparkline_multi({
        "a": [1, 2],
        "long_name": [3, 4],
    }, align_labels=True)
    lines = result.split("\n")
    # Both lines should start at same column
    spark_start_0 = lines[0].index("▁") if "▁" in lines[0] else lines[0].index("█")
    spark_start_1 = lines[1].index("▁") if "▁" in lines[1] else lines[1].index("█")
    # Labels are right-aligned, so sparklines start at same position
    assert abs(spark_start_0 - spark_start_1) <= 1


# ─── sparkbar ─────────────────────────────────────────────────────────

def test_sparkbar_zero():
    result = sparkbar(0, 100, width=10, show_percent=True)
    assert "0%" in result


def test_sparkbar_full():
    result = sparkbar(100, 100, width=10, show_percent=True)
    assert "100%" in result


def test_sparkbar_half():
    result = sparkbar(50, 100, width=20, show_percent=True)
    assert "50%" in result


def test_sparkbar_label():
    result = sparkbar(75, 100, label="Disk")
    assert result.startswith("Disk ")


def test_sparkbar_color():
    result = sparkbar(60, 100, color="fire")
    assert "\033[38;2;" in result


def test_sparkbar_no_percent():
    result = sparkbar(30, 100, show_percent=False)
    assert "%" not in result


# ─── _resample ────────────────────────────────────────────────────────

def test_resample_identity():
    assert _resample([1, 2, 3], 5) == [1, 2, 3]


def test_resample_down():
    result = _resample([1, 2, 3, 4, 5, 6], 3)
    assert len(result) == 3
    assert result[0] == 1.5  # avg of [1, 2]
    assert result[1] == 3.5  # avg of [3, 4]
    assert result[2] == 5.5  # avg of [5, 6]
