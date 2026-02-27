"""Interactive terminal data table with sorting, filtering, and pagination.

Renders tabular data with box-drawing borders, column alignment, color themes,
and optional interactive keyboard navigation. Supports both static rendering
and interactive browsing. Zero dependencies.
"""

import re
import sys
import tty
import termios
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

# ─── ANSI helpers ─────────────────────────────────────────────────────

def _ansi(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[^m]*m", "", text)


def _visible_len(text: str) -> int:
    return len(_strip_ansi(text))


def _pad(text: str, width: int, align: str = "left") -> str:
    """Pad text to width, respecting ANSI codes."""
    vlen = _visible_len(text)
    diff = max(0, width - vlen)
    if align == "right":
        return " " * diff + text
    if align == "center":
        left = diff // 2
        right = diff - left
        return " " * left + text + " " * right
    return text + " " * diff


def _hide_cursor() -> str:
    return "\033[?25l"


def _show_cursor() -> str:
    return "\033[?25h"


def _clear_line() -> str:
    return "\033[2K\r"


def _move_up(n: int = 1) -> str:
    return f"\033[{n}A" if n > 0 else ""


# ─── Theme ────────────────────────────────────────────────────────────

@dataclass
class TableTheme:
    """Color and border theme for tables."""
    border: str = "38;2;100;116;139"       # slate
    header_bg: str = "48;2;30;41;59"       # dark slate bg
    header_fg: str = "1;37"                # bold white
    row_fg: str = "37"                     # white
    row_alt_bg: str = "48;2;20;27;38"      # very dark alt row
    highlight_bg: str = "48;2;55;65;81"    # selected row
    highlight_fg: str = "1;37"             # bold white
    accent: str = "38;2;99;102;241"        # indigo
    dim: str = "2"                         # dim
    sort_indicator: str = "38;2;99;102;241"


@dataclass
class BoxChars:
    """Box-drawing characters for table borders."""
    h: str = "─"
    v: str = "│"
    tl: str = "┌"
    tr: str = "┐"
    bl: str = "└"
    br: str = "┘"
    tj: str = "┬"
    bj: str = "┴"
    lj: str = "├"
    rj: str = "┤"
    cross: str = "┼"


DEFAULT_THEME = TableTheme()
DEFAULT_BOX = BoxChars()
ROUNDED_BOX = BoxChars(tl="╭", tr="╮", bl="╰", br="╯")
HEAVY_BOX = BoxChars(h="━", v="┃", tl="┏", tr="┓", bl="┗", br="┛",
                     tj="┳", bj="┻", lj="┣", rj="┫", cross="╋")


# ─── Column definition ───────────────────────────────────────────────

@dataclass
class Column:
    """Column configuration for the data table."""
    key: str
    label: str | None = None
    width: int | None = None
    min_width: int = 3
    max_width: int = 50
    align: str = "left"  # left, right, center
    formatter: Callable[[Any], str] | None = None


# ─── Core static rendering ────────────────────────────────────────────

def _compute_col_widths(
    columns: list[Column],
    rows: list[dict[str, Any]],
) -> list[int]:
    """Compute column widths based on content."""
    widths: list[int] = []
    for col in columns:
        if col.width:
            widths.append(col.width)
            continue
        label = col.label or col.key
        max_w = len(label)
        for row in rows:
            val = _format_cell(row.get(col.key, ""), col)
            max_w = max(max_w, _visible_len(val))
        max_w = max(col.min_width, min(col.max_width, max_w))
        widths.append(max_w)
    return widths


def _format_cell(value: Any, col: Column) -> str:
    """Format a cell value using the column's formatter."""
    if col.formatter:
        return col.formatter(value)
    if value is None:
        return ""
    return str(value)


def _make_separator(
    widths: list[int],
    box: BoxChars,
    left: str,
    mid: str,
    right: str,
    theme: TableTheme,
) -> str:
    """Build a horizontal separator line."""
    parts = [left]
    for i, w in enumerate(widths):
        parts.append(box.h * (w + 2))
        parts.append(mid if i < len(widths) - 1 else right)
    return _ansi(theme.border, "".join(parts))


def _make_row(
    cells: list[str],
    widths: list[int],
    aligns: list[str],
    box: BoxChars,
    theme: TableTheme,
    row_style: str = "",
) -> str:
    """Build a data row with borders."""
    parts: list[str] = []
    parts.append(_ansi(theme.border, box.v))
    for i, (cell, w, align) in enumerate(zip(cells, widths, aligns)):
        padded = _pad(cell, w, align)
        content = f" {padded} "
        if row_style:
            content = _ansi(row_style, content)
        parts.append(content)
        parts.append(_ansi(theme.border, box.v))
    return "".join(parts)


def render_table(
    rows: Sequence[dict[str, Any]],
    columns: Sequence[Column | str] | None = None,
    *,
    theme: TableTheme | None = None,
    box: BoxChars | None = None,
    title: str | None = None,
    show_row_numbers: bool = False,
    striped: bool = True,
    max_rows: int | None = None,
    sort_by: str | None = None,
    sort_reverse: bool = False,
    filter_fn: Callable[[dict[str, Any]], bool] | None = None,
    footer: str | None = None,
) -> str:
    """Render a static data table.

    Args:
        rows: List of dicts, each representing a row.
        columns: Column definitions. If None, inferred from first row keys.
            Can be Column objects or plain strings (used as key+label).
        theme: Visual theme. Defaults to DEFAULT_THEME.
        box: Box-drawing character set.
        title: Optional title above the table.
        show_row_numbers: Prepend a "#" column.
        striped: Alternate row background colors.
        max_rows: Limit displayed rows.
        sort_by: Column key to sort by.
        sort_reverse: Reverse sort order.
        filter_fn: Predicate to filter rows.
        footer: Optional footer text below the table.

    Returns:
        Multi-line string with ANSI-styled table.
    """
    t = theme or DEFAULT_THEME
    b = box or DEFAULT_BOX

    if not rows:
        return ""

    # Normalize columns
    cols = _normalize_columns(columns, rows)

    # Row numbers
    if show_row_numbers:
        cols = [Column(key="__rownum__", label="#", align="right", width=4)] + cols

    # Filter
    filtered = list(rows)
    if filter_fn:
        filtered = [r for r in filtered if filter_fn(r)]

    # Sort
    if sort_by:
        filtered = _sort_rows(filtered, sort_by, sort_reverse)

    # Truncate
    total_count = len(filtered)
    if max_rows and max_rows < total_count:
        filtered = filtered[:max_rows]

    # Add row numbers
    if show_row_numbers:
        for i, row in enumerate(filtered):
            row = dict(row)
            row["__rownum__"] = i + 1
            filtered[i] = row

    widths = _compute_col_widths(cols, filtered)
    aligns = [c.align for c in cols]
    labels = [c.label or c.key for c in cols]

    lines: list[str] = []

    # Title
    if title:
        total_w = sum(w + 3 for w in widths) + 1
        lines.append(_ansi(f"{t.accent};1", title.center(total_w)))

    # Top border
    lines.append(_make_separator(widths, b, b.tl, b.tj, b.tr, t))

    # Header row
    header_cells = []
    for label, w in zip(labels, widths):
        header_cells.append(label)
    header_line = _make_row(header_cells, widths, aligns, b, t, f"{t.header_bg};{t.header_fg}")
    lines.append(header_line)

    # Header separator
    lines.append(_make_separator(widths, b, b.lj, b.cross, b.rj, t))

    # Data rows
    for idx, row in enumerate(filtered):
        cells = [_format_cell(row.get(c.key, ""), c) for c in cols]
        style = t.row_alt_bg if striped and idx % 2 == 1 else ""
        lines.append(_make_row(cells, widths, aligns, b, t, style))

    # Bottom border
    lines.append(_make_separator(widths, b, b.bl, b.bj, b.br, t))

    # Footer
    if footer:
        total_w = sum(w + 3 for w in widths) + 1
        lines.append(_ansi(t.dim, footer.center(total_w)))
    elif max_rows and max_rows < total_count:
        total_w = sum(w + 3 for w in widths) + 1
        lines.append(_ansi(t.dim, f"Showing {len(filtered)} of {total_count} rows".center(total_w)))

    return "\n".join(lines)


# ─── Interactive table ────────────────────────────────────────────────

def _read_key(stream=None) -> str:
    """Read a single keypress."""
    stream = stream or sys.stdin
    fd = stream.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = stream.read(1)
        if ch == "\x1b":
            seq = stream.read(1)
            if seq == "[":
                code = stream.read(1)
                return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(code, "unknown")
            return "escape"
        if ch in ("\r", "\n"):
            return "enter"
        if ch in ("\x7f", "\x08"):
            return "backspace"
        if ch == "\t":
            return "tab"
        if ch == " ":
            return "space"
        if ch == "\x03":
            return "ctrl-c"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def interactive_table(
    rows: Sequence[dict[str, Any]],
    columns: Sequence[Column | str] | None = None,
    *,
    theme: TableTheme | None = None,
    box: BoxChars | None = None,
    title: str | None = None,
    page_size: int = 15,
    show_row_numbers: bool = True,
    striped: bool = True,
) -> dict[str, Any] | None:
    """Run an interactive browsable table in the terminal.

    Supports: arrow keys to navigate, s to cycle sort, / to filter,
    q or Escape to quit, Enter to select a row.

    Args:
        rows: List of row dicts.
        columns: Column definitions.
        theme: Visual theme.
        box: Box-drawing characters.
        title: Title above the table.
        page_size: Rows per page.
        show_row_numbers: Show row number column.
        striped: Alternate row backgrounds.

    Returns:
        The selected row dict, or None if quit.
    """
    t = theme or DEFAULT_THEME
    b = box or DEFAULT_BOX
    cols = _normalize_columns(columns, rows)

    all_rows = list(rows)
    filtered = all_rows
    cursor = 0
    page = 0
    sort_col: str | None = None
    sort_rev = False
    filter_text = ""
    filter_mode = False
    last_render_lines = 0

    def _apply_filter() -> list[dict[str, Any]]:
        if not filter_text:
            return all_rows
        pattern = filter_text.lower()
        return [
            r for r in all_rows
            if any(pattern in str(v).lower() for v in r.values())
        ]

    def _render() -> int:
        nonlocal filtered
        filtered = _apply_filter()
        if sort_col:
            filtered = _sort_rows(filtered, sort_col, sort_rev)

        total = len(filtered)
        total_pages = max(1, (total + page_size - 1) // page_size)
        start = page * page_size
        end = min(start + page_size, total)
        page_rows = filtered[start:end]

        # Build columns with row nums
        render_cols = list(cols)
        if show_row_numbers:
            render_cols = [Column(key="__rownum__", label="#", align="right", width=4)] + render_cols

        # Add row numbers
        numbered = []
        for i, row in enumerate(page_rows):
            row = dict(row)
            if show_row_numbers:
                row["__rownum__"] = start + i + 1
            numbered.append(row)

        widths = _compute_col_widths(render_cols, numbered)
        aligns = [c.align for c in render_cols]
        labels = [c.label or c.key for c in render_cols]
        total_w = sum(w + 3 for w in widths) + 1

        output: list[str] = []

        # Title
        if title:
            output.append(_ansi(f"{t.accent};1", title.center(total_w)))

        # Top border
        output.append(_make_separator(widths, b, b.tl, b.tj, b.tr, t))

        # Header with sort indicators
        header_cells = []
        for c, label in zip(render_cols, labels):
            if sort_col and c.key == sort_col:
                indicator = " ▲" if not sort_rev else " ▼"
                header_cells.append(label + _ansi(t.sort_indicator, indicator))
            else:
                header_cells.append(label)
        output.append(_make_row(header_cells, widths, aligns, b, t, f"{t.header_bg};{t.header_fg}"))
        output.append(_make_separator(widths, b, b.lj, b.cross, b.rj, t))

        # Rows
        for idx, row in enumerate(numbered):
            cells = [_format_cell(row.get(c.key, ""), c) for c in render_cols]
            is_cursor = (idx == cursor - start) if start <= cursor < end else False
            if is_cursor:
                style = f"{t.highlight_bg};{t.highlight_fg}"
            elif striped and idx % 2 == 1:
                style = t.row_alt_bg
            else:
                style = ""
            output.append(_make_row(cells, widths, aligns, b, t, style))

        # Bottom border
        output.append(_make_separator(widths, b, b.bl, b.bj, b.br, t))

        # Status bar
        status_parts = [
            f"Page {page + 1}/{total_pages}",
            f"{total} rows",
        ]
        if filter_text:
            status_parts.append(f"filter: \"{filter_text}\"")
        if sort_col:
            direction = "asc" if not sort_rev else "desc"
            status_parts.append(f"sort: {sort_col} {direction}")
        status = " │ ".join(status_parts)
        output.append(_ansi(t.dim, status.center(total_w)))

        # Help bar
        if filter_mode:
            help_text = "Type to filter │ Enter to apply │ Esc to cancel"
        else:
            help_text = "↑↓ navigate │ ←→ page │ s sort │ / filter │ Enter select │ q quit"
        output.append(_ansi(t.dim, help_text.center(total_w)))

        rendered = "\n".join(output)
        sys.stdout.write(rendered)
        sys.stdout.flush()
        return rendered.count("\n") + 1

    sys.stdout.write(_hide_cursor())
    try:
        last_render_lines = _render()

        while True:
            key = _read_key()

            # Clear previous render
            if last_render_lines > 1:
                sys.stdout.write(_move_up(last_render_lines - 1))
            sys.stdout.write("\r")
            for _ in range(last_render_lines):
                sys.stdout.write(_clear_line() + "\n")
            if last_render_lines > 1:
                sys.stdout.write(_move_up(last_render_lines))
            sys.stdout.write("\r")

            if filter_mode:
                if key == "enter" or key == "escape":
                    if key == "escape":
                        filter_text = ""
                    filter_mode = False
                    cursor = 0
                    page = 0
                elif key == "backspace":
                    filter_text = filter_text[:-1]
                elif key == "ctrl-c":
                    break
                elif len(key) == 1:
                    filter_text += key
                last_render_lines = _render()
                continue

            if key == "ctrl-c" or key == "q" or key == "escape":
                sys.stdout.write("\n")
                return None
            elif key == "enter":
                if filtered and 0 <= cursor < len(filtered):
                    sys.stdout.write("\n")
                    return filtered[cursor]
                sys.stdout.write("\n")
                return None
            elif key == "up":
                cursor = max(0, cursor - 1)
                total = len(filtered)
                page = cursor // page_size
            elif key == "down":
                total = len(filtered)
                cursor = min(total - 1, cursor + 1)
                page = cursor // page_size
            elif key == "left":
                total = len(filtered)
                total_pages = max(1, (total + page_size - 1) // page_size)
                page = max(0, page - 1)
                cursor = page * page_size
            elif key == "right":
                total = len(filtered)
                total_pages = max(1, (total + page_size - 1) // page_size)
                page = min(total_pages - 1, page + 1)
                cursor = page * page_size
            elif key == "s":
                sortable_keys = [c.key for c in cols]
                if sort_col is None:
                    sort_col = sortable_keys[0]
                    sort_rev = False
                elif not sort_rev:
                    sort_rev = True
                else:
                    idx = sortable_keys.index(sort_col)
                    if idx + 1 < len(sortable_keys):
                        sort_col = sortable_keys[idx + 1]
                        sort_rev = False
                    else:
                        sort_col = None
                        sort_rev = False
                cursor = 0
                page = 0
            elif key == "/":
                filter_mode = True

            last_render_lines = _render()

    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(_show_cursor())
        sys.stdout.flush()

    return None


# ─── Helpers ──────────────────────────────────────────────────────────

def _normalize_columns(
    columns: Sequence[Column | str] | None,
    rows: Sequence[dict[str, Any]],
) -> list[Column]:
    """Normalize column specs to Column objects."""
    if columns:
        result: list[Column] = []
        for c in columns:
            if isinstance(c, str):
                result.append(Column(key=c, label=c))
            else:
                result.append(c)
        return result

    if rows:
        keys = list(rows[0].keys())
        return [Column(key=k, label=k) for k in keys]

    return []


def _sort_rows(
    rows: list[dict[str, Any]],
    key: str,
    reverse: bool = False,
) -> list[dict[str, Any]]:
    """Sort rows by a column key, handling mixed types."""
    def sort_key(row: dict) -> tuple:
        val = row.get(key)
        if val is None:
            return (1, "")
        if isinstance(val, (int, float)):
            return (0, val)
        return (0, str(val).lower())

    return sorted(rows, key=sort_key, reverse=reverse)
