import sys, os
from unittest.mock import patch
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.data_table import (
    render_table, interactive_table,
    Column, TableTheme, BoxChars,
    DEFAULT_THEME, DEFAULT_BOX, ROUNDED_BOX, HEAVY_BOX,
    _ansi, _strip_ansi, _visible_len, _pad,
    _normalize_columns, _sort_rows, _compute_col_widths,
    _format_cell, _make_separator, _make_row,
)

SAMPLE = [
    {"name": "Alice", "age": 30, "city": "New York"},
    {"name": "Bob",   "age": 25, "city": "London"},
    {"name": "Carol", "age": 35, "city": "Tokyo"},
    {"name": "Dave",  "age": 28, "city": "Berlin"},
]


# ─── ANSI helpers ─────────────────────────────────────────────────────

def test_ansi_wraps():
    assert _ansi("1;31", "bold") == "\033[1;31mbold\033[0m"


def test_strip_ansi():
    colored = _ansi("1;32", "hello")
    assert _strip_ansi(colored) == "hello"


def test_strip_ansi_plain():
    assert _strip_ansi("plain") == "plain"


def test_visible_len_plain():
    assert _visible_len("hello") == 5


def test_visible_len_colored():
    colored = _ansi("1;31", "hello")
    assert _visible_len(colored) == 5


def test_pad_left():
    assert _pad("ab", 5) == "ab   "


def test_pad_right():
    assert _pad("ab", 5, "right") == "   ab"


def test_pad_center():
    result = _pad("ab", 6, "center")
    assert result == "  ab  "


def test_pad_no_truncation():
    # Longer than width — no truncation, just return as-is
    assert _pad("abcdefgh", 3) == "abcdefgh"


# ─── Column helpers ───────────────────────────────────────────────────

def test_normalize_columns_from_strings():
    cols = _normalize_columns(["name", "age"], SAMPLE)
    assert len(cols) == 2
    assert cols[0].key == "name"
    assert cols[0].label == "name"


def test_normalize_columns_from_column_objects():
    col = Column(key="name", label="Full Name")
    cols = _normalize_columns([col], SAMPLE)
    assert cols[0].label == "Full Name"


def test_normalize_columns_inferred():
    cols = _normalize_columns(None, SAMPLE)
    assert len(cols) == 3
    assert cols[0].key == "name"


def test_normalize_columns_empty_rows():
    cols = _normalize_columns(None, [])
    assert cols == []


def test_compute_col_widths_basic():
    cols = [Column(key="name"), Column(key="age")]
    widths = _compute_col_widths(cols, SAMPLE)
    assert widths[0] >= len("Alice")
    assert widths[1] >= len("age")


def test_compute_col_widths_fixed():
    cols = [Column(key="name", width=10)]
    widths = _compute_col_widths(cols, SAMPLE)
    assert widths[0] == 10


def test_compute_col_widths_min():
    cols = [Column(key="name", min_width=20)]
    widths = _compute_col_widths(cols, SAMPLE)
    assert widths[0] >= 20


def test_compute_col_widths_max():
    cols = [Column(key="name", max_width=3)]
    widths = _compute_col_widths(cols, SAMPLE)
    assert widths[0] == 3


def test_format_cell_basic():
    col = Column(key="name")
    assert _format_cell("Alice", col) == "Alice"


def test_format_cell_none():
    col = Column(key="x")
    assert _format_cell(None, col) == ""


def test_format_cell_formatter():
    col = Column(key="age", formatter=lambda v: f"{v} yrs")
    assert _format_cell(28, col) == "28 yrs"


def test_format_cell_int():
    col = Column(key="age")
    assert _format_cell(42, col) == "42"


# ─── Sort ─────────────────────────────────────────────────────────────

def test_sort_ascending():
    result = _sort_rows(SAMPLE, "age")
    ages = [r["age"] for r in result]
    assert ages == sorted(ages)


def test_sort_descending():
    result = _sort_rows(SAMPLE, "age", reverse=True)
    ages = [r["age"] for r in result]
    assert ages == sorted(ages, reverse=True)


def test_sort_string():
    result = _sort_rows(SAMPLE, "name")
    names = [r["name"] for r in result]
    assert names == sorted(names, key=str.lower)


def test_sort_with_none():
    rows = [{"v": None}, {"v": 1}, {"v": 2}]
    result = _sort_rows(rows, "v")
    # None sorts last
    assert result[-1]["v"] is None


# ─── render_table ─────────────────────────────────────────────────────

def test_render_basic():
    result = render_table(SAMPLE)
    assert "Alice" in _strip_ansi(result)
    assert "Bob" in _strip_ansi(result)
    assert "┌" in _strip_ansi(result)
    assert "└" in _strip_ansi(result)


def test_render_empty():
    assert render_table([]) == ""


def test_render_explicit_columns():
    result = render_table(SAMPLE, ["name", "age"])
    plain = _strip_ansi(result)
    assert "name" in plain
    assert "age" in plain
    assert "city" not in plain


def test_render_column_objects():
    cols = [Column(key="name", label="Full Name", align="center")]
    result = render_table(SAMPLE, cols)
    assert "Full Name" in _strip_ansi(result)


def test_render_title():
    result = render_table(SAMPLE, title="My Table")
    assert "My Table" in _strip_ansi(result)


def test_render_row_numbers():
    result = render_table(SAMPLE, show_row_numbers=True)
    plain = _strip_ansi(result)
    assert "#" in plain
    assert "1" in plain


def test_render_sort():
    result = render_table(SAMPLE, sort_by="age")
    plain = _strip_ansi(result)
    # Bob (25) should appear before Alice (30)
    assert plain.index("Bob") < plain.index("Alice")


def test_render_sort_reverse():
    result = render_table(SAMPLE, sort_by="age", sort_reverse=True)
    plain = _strip_ansi(result)
    # Carol (35) should appear first
    assert plain.index("Carol") < plain.index("Bob")


def test_render_filter():
    result = render_table(SAMPLE, filter_fn=lambda r: r["age"] > 28)
    plain = _strip_ansi(result)
    assert "Alice" in plain
    assert "Bob" not in plain


def test_render_max_rows():
    result = render_table(SAMPLE, max_rows=2)
    plain = _strip_ansi(result)
    # Footer should mention total count
    assert "4" in plain


def test_render_footer():
    result = render_table(SAMPLE, footer="Custom footer")
    assert "Custom footer" in _strip_ansi(result)


def test_render_striped():
    # Just ensure it doesn't crash and produces output
    result = render_table(SAMPLE, striped=True)
    assert len(result) > 0


def test_render_rounded_box():
    result = render_table(SAMPLE, box=ROUNDED_BOX)
    assert "╭" in _strip_ansi(result)
    assert "╯" in _strip_ansi(result)


def test_render_heavy_box():
    result = render_table(SAMPLE, box=HEAVY_BOX)
    assert "┏" in _strip_ansi(result)
    assert "┛" in _strip_ansi(result)


def test_render_custom_theme():
    theme = TableTheme(header_fg="1;33")
    result = render_table(SAMPLE, theme=theme)
    assert len(result) > 0


def test_render_formatter():
    cols = [Column(key="age", formatter=lambda v: f"age:{v}")]
    result = render_table(SAMPLE, cols)
    assert "age:30" in _strip_ansi(result)


def test_render_right_align():
    cols = [Column(key="age", align="right")]
    result = render_table(SAMPLE, cols)
    assert len(result) > 0


def test_render_missing_key():
    rows = [{"name": "X"}, {"name": "Y", "extra": "E"}]
    result = render_table(rows, ["name", "extra"])
    assert "X" in _strip_ansi(result)


# ─── Border helpers ───────────────────────────────────────────────────

def test_make_separator():
    sep = _make_separator([5, 8], DEFAULT_BOX, "┌", "┬", "┐", DEFAULT_THEME)
    plain = _strip_ansi(sep)
    assert plain.startswith("┌")
    assert plain.endswith("┐")
    assert "┬" in plain


def test_make_row_basic():
    row = _make_row(["Alice", "30"], [6, 4], ["left", "right"], DEFAULT_BOX, DEFAULT_THEME)
    plain = _strip_ansi(row)
    assert "Alice" in plain
    assert "30" in plain
    assert plain.startswith("│")
    assert plain.endswith("│")


# ─── interactive_table (mocked _read_key) ─────────────────────────────

def _mock_keys(keys):
    it = iter(keys)
    def _fake(stream=None):
        return next(it)
    return _fake


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_quit(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["q"])
    result = interactive_table(SAMPLE)
    assert result is None


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_escape(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["escape"])
    result = interactive_table(SAMPLE)
    assert result is None


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_ctrl_c(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["ctrl-c"])
    result = interactive_table(SAMPLE)
    assert result is None


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_select_first(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["enter"])
    result = interactive_table(SAMPLE)
    assert result == SAMPLE[0]


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_navigate_down_select(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["down", "enter"])
    result = interactive_table(SAMPLE)
    assert result == SAMPLE[1]


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_navigate_up(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["down", "down", "up", "enter"])
    result = interactive_table(SAMPLE)
    assert result == SAMPLE[1]


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_navigate_down_clamps(mock_key, mock_out):
    # Down past last row, then select
    keys = ["down"] * 10 + ["enter"]
    mock_key.side_effect = _mock_keys(keys)
    result = interactive_table(SAMPLE)
    assert result == SAMPLE[-1]


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_sort_cycle(mock_key, mock_out):
    # s to sort first col asc, s again for desc, s again for next col, q to quit
    mock_key.side_effect = _mock_keys(["s", "s", "s", "q"])
    result = interactive_table(SAMPLE)
    assert result is None


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_filter_and_select(mock_key, mock_out):
    # '/' enter filter mode, type "alice", enter to apply, enter to select
    mock_key.side_effect = _mock_keys(["/", "a", "l", "i", "c", "e", "enter", "enter"])
    result = interactive_table(SAMPLE)
    assert result is not None
    assert result["name"] == "Alice"


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_filter_escape_clears(mock_key, mock_out):
    # '/' enter filter, type something, escape to cancel, q to quit
    mock_key.side_effect = _mock_keys(["/", "x", "y", "z", "escape", "q"])
    result = interactive_table(SAMPLE)
    assert result is None


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_filter_backspace(mock_key, mock_out):
    # Type in filter, backspace, enter to apply, q to quit
    mock_key.side_effect = _mock_keys(["/", "a", "b", "backspace", "enter", "q"])
    result = interactive_table(SAMPLE)
    assert result is None


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_paging(mock_key, mock_out):
    big_rows = [{"id": i, "val": f"item-{i}"} for i in range(30)]
    # right to go to page 2, left back, enter to select
    mock_key.side_effect = _mock_keys(["right", "left", "enter"])
    result = interactive_table(big_rows, page_size=10)
    assert result == big_rows[0]


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_empty_rows_enter(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["enter"])
    result = interactive_table([])
    assert result is None


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_with_title(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["q"])
    result = interactive_table(SAMPLE, title="My Table")
    assert result is None
    assert "My Table" in mock_out.getvalue()


@patch('sys.stdout', new_callable=StringIO)
@patch('data_table._read_key')
def test_interactive_filter_ctrl_c(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["/", "ctrl-c"])
    result = interactive_table(SAMPLE)
    assert result is None
