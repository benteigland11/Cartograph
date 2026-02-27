"""Terminal-rendered heatmap grids using Unicode blocks and color gradients.

Renders 2D numeric arrays as colored heatmaps in the terminal. Supports
row/column labels, multiple color palettes, value annotations, and
normalization modes. Zero dependencies.
"""

import math
from typing import Sequence

# ─── Block characters for intensity levels ────────────────────────────

BLOCKS = " ░▒▓█"
HALF_BLOCKS = " ▁▂▃▄▅▆▇█"


# ─── Color palettes ──────────────────────────────────────────────────

COLOR_PRESETS: dict[str, list[tuple[int, int, int]]] = {
    "heat":     [(10, 10, 40), (60, 10, 120), (200, 30, 60), (255, 160, 0), (255, 255, 100)],
    "cool":     [(10, 10, 50), (30, 60, 150), (50, 150, 200), (140, 220, 230), (230, 250, 255)],
    "viridis":  [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)],
    "magma":    [(0, 0, 4), (81, 18, 124), (183, 55, 121), (254, 159, 109), (252, 253, 191)],
    "inferno":  [(0, 0, 4), (87, 16, 110), (188, 55, 84), (249, 142, 9), (252, 255, 164)],
    "plasma":   [(13, 8, 135), (126, 3, 168), (204, 71, 120), (248, 149, 64), (240, 249, 33)],
    "greens":   [(0, 30, 15), (0, 80, 40), (16, 150, 70), (80, 200, 120), (180, 240, 200)],
    "reds":     [(30, 0, 0), (100, 10, 10), (180, 30, 20), (230, 80, 50), (255, 180, 150)],
    "blues":    [(5, 5, 30), (15, 30, 100), (30, 80, 180), (80, 150, 230), (180, 215, 255)],
    "grayscale": [(20, 20, 20), (80, 80, 80), (140, 140, 140), (200, 200, 200), (245, 245, 245)],
}


# ─── Color helpers ────────────────────────────────────────────────────

def _lerp_color(
    t: float,
    colors: list[tuple[int, int, int]],
) -> tuple[int, int, int]:
    """Interpolate between color stops at position t in [0, 1]."""
    if len(colors) == 1:
        return colors[0]
    t = max(0.0, min(1.0, t))
    segment = t * (len(colors) - 1)
    idx = int(segment)
    if idx >= len(colors) - 1:
        return colors[-1]
    frac = segment - idx
    c0, c1 = colors[idx], colors[idx + 1]
    return (
        int(c0[0] + (c1[0] - c0[0]) * frac),
        int(c0[1] + (c1[1] - c0[1]) * frac),
        int(c0[2] + (c1[2] - c0[2]) * frac),
    )


def _rgb_fg(r: int, g: int, b: int, text: str) -> str:
    return f"\033[38;2;{r};{g};{b}m{text}\033[0m"


def _rgb_bg(r: int, g: int, b: int, text: str) -> str:
    return f"\033[48;2;{r};{g};{b}m{text}\033[0m"


def _rgb_fg_bg(
    fr: int, fg: int, fb: int,
    br: int, bg_: int, bb: int,
    text: str,
) -> str:
    return f"\033[38;2;{fr};{fg};{fb};48;2;{br};{bg_};{bb}m{text}\033[0m"


def _resolve_colors(
    palette: str | list[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    if isinstance(palette, str):
        return COLOR_PRESETS.get(palette, COLOR_PRESETS["heat"])
    return palette


# ─── Normalization ────────────────────────────────────────────────────

def _normalize_grid(
    data: list[list[float]],
    min_val: float | None = None,
    max_val: float | None = None,
    per_row: bool = False,
) -> list[list[float]]:
    """Normalize a 2D grid to [0, 1] values."""
    if not data or not data[0]:
        return data

    if per_row:
        result: list[list[float]] = []
        for row in data:
            lo = min(row) if min_val is None else min_val
            hi = max(row) if max_val is None else max_val
            span = hi - lo if hi != lo else 1.0
            result.append([(v - lo) / span for v in row])
        return result

    all_vals = [v for row in data for v in row]
    lo = min(all_vals) if min_val is None else min_val
    hi = max(all_vals) if max_val is None else max_val
    span = hi - lo if hi != lo else 1.0

    return [[(v - lo) / span for v in row] for row in data]


# ─── Core rendering ──────────────────────────────────────────────────

def heatmap(
    data: Sequence[Sequence[float | int]],
    *,
    palette: str | list[tuple[int, int, int]] = "heat",
    row_labels: list[str] | None = None,
    col_labels: list[str] | None = None,
    show_values: bool = False,
    value_fmt: str = ".0f",
    cell_width: int = 2,
    min_val: float | None = None,
    max_val: float | None = None,
    per_row: bool = False,
    title: str | None = None,
    show_legend: bool = False,
    legend_width: int = 20,
) -> str:
    """Render a 2D heatmap grid in the terminal.

    Args:
        data: 2D array of numeric values (list of lists).
        palette: Color preset name or list of RGB tuples.
        row_labels: Labels for each row (left side).
        col_labels: Labels for each column (top).
        show_values: Display numeric values inside cells.
        value_fmt: Format string for values (e.g. ".1f", "d").
        cell_width: Character width per cell.
        min_val: Override minimum for normalization.
        max_val: Override maximum for normalization.
        per_row: Normalize each row independently.
        title: Optional title above the heatmap.
        show_legend: Show a color scale legend below.
        legend_width: Character width of the legend bar.

    Returns:
        Multi-line string with ANSI-colored heatmap.
    """
    if not data or not data[0]:
        return ""

    grid = [list(row) for row in data]
    colors = _resolve_colors(palette)
    normed = _normalize_grid(grid, min_val, max_val, per_row)
    num_rows = len(grid)
    num_cols = len(grid[0])

    # Determine cell width
    if show_values:
        max_val_len = 0
        for row in grid:
            for v in row:
                max_val_len = max(max_val_len, len(f"{v:{value_fmt}}"))
        cell_width = max(cell_width, max_val_len + 1)

    # Row label padding
    label_pad = 0
    if row_labels:
        label_pad = max(len(l) for l in row_labels) + 1

    lines: list[str] = []

    # Title
    if title:
        total_w = label_pad + num_cols * cell_width
        lines.append(title.center(total_w))
        lines.append("")

    # Column labels
    if col_labels:
        header = " " * label_pad
        for j, cl in enumerate(col_labels):
            header += cl[:cell_width].center(cell_width)
        lines.append(header)

    # Grid rows
    for i in range(num_rows):
        row_str_parts: list[str] = []

        if row_labels and i < len(row_labels):
            row_str_parts.append(row_labels[i].rjust(label_pad - 1) + " ")
        elif row_labels:
            row_str_parts.append(" " * label_pad)

        for j in range(num_cols):
            t = max(0.0, min(1.0, normed[i][j]))
            r, g, b = _lerp_color(t, colors)

            if show_values:
                val_str = f"{grid[i][j]:{value_fmt}}"
                cell = val_str.center(cell_width)
                # Pick contrasting text color
                brightness = (r * 299 + g * 587 + b * 114) / 1000
                tr, tg, tb = (0, 0, 0) if brightness > 128 else (255, 255, 255)
                row_str_parts.append(_rgb_fg_bg(tr, tg, tb, r, g, b, cell))
            else:
                cell = "█" * cell_width
                row_str_parts.append(_rgb_fg(r, g, b, cell))

        lines.append("".join(row_str_parts))

    # Legend
    if show_legend:
        lines.append("")
        all_vals = [v for row in grid for v in row]
        lo = min(all_vals) if min_val is None else min_val
        hi = max(all_vals) if max_val is None else max_val

        legend_parts: list[str] = []
        legend_parts.append(" " * label_pad)
        for k in range(legend_width):
            t = k / max(legend_width - 1, 1)
            r, g, b = _lerp_color(t, colors)
            legend_parts.append(_rgb_fg(r, g, b, "█"))

        legend_line = "".join(legend_parts)
        lines.append(legend_line)

        lo_str = f"{lo:{value_fmt}}"
        hi_str = f"{hi:{value_fmt}}"
        scale_label = " " * label_pad + lo_str + " " * (legend_width - len(lo_str) - len(hi_str)) + hi_str
        lines.append(scale_label)

    return "\n".join(lines)


# ─── Specialized renderers ───────────────────────────────────────────

def heatmap_compact(
    data: Sequence[Sequence[float | int]],
    *,
    palette: str | list[tuple[int, int, int]] = "heat",
    min_val: float | None = None,
    max_val: float | None = None,
) -> str:
    """Render a minimal 1-char-per-cell heatmap using block characters.

    Args:
        data: 2D array of numeric values.
        palette: Color preset or RGB list.
        min_val: Override minimum for normalization.
        max_val: Override maximum for normalization.

    Returns:
        Multi-line string with colored block characters.
    """
    if not data or not data[0]:
        return ""

    grid = [list(row) for row in data]
    colors = _resolve_colors(palette)
    normed = _normalize_grid(grid, min_val, max_val)

    lines: list[str] = []
    for i, row in enumerate(normed):
        chars: list[str] = []
        for t in row:
            t = max(0.0, min(1.0, t))
            r, g, b = _lerp_color(t, colors)
            block_idx = int(t * (len(BLOCKS) - 1))
            block_idx = min(block_idx, len(BLOCKS) - 1)
            chars.append(_rgb_fg(r, g, b, BLOCKS[block_idx]))
        lines.append("".join(chars))

    return "\n".join(lines)


def calendar_heatmap(
    values: Sequence[float | int],
    *,
    weeks: int | None = None,
    palette: str | list[tuple[int, int, int]] = "greens",
    empty_char: str = "░",
    min_val: float | None = None,
    max_val: float | None = None,
    show_legend: bool = True,
) -> str:
    """Render a GitHub-style contribution calendar heatmap.

    Args:
        values: Flat sequence of daily values (oldest first). Length determines grid size.
        weeks: Override number of weeks (columns). Default: ceil(len(values)/7).
        palette: Color preset or RGB list.
        empty_char: Character for zero/missing values.
        min_val: Override minimum for normalization.
        max_val: Override maximum for normalization.
        show_legend: Show a legend bar below.

    Returns:
        Multi-line string with 7-row calendar heatmap.
    """
    if not values:
        return ""

    vals = list(values)
    n_weeks = weeks or math.ceil(len(vals) / 7)
    total = n_weeks * 7

    # Pad to fill grid
    padded = vals + [0.0] * (total - len(vals))

    colors = _resolve_colors(palette)
    lo = min(padded) if min_val is None else min_val
    hi = max(padded) if max_val is None else max_val
    span = hi - lo if hi != lo else 1.0

    day_labels = ["M", " ", "W", " ", "F", " ", "S"]
    lines: list[str] = []

    for row in range(7):
        parts: list[str] = [day_labels[row] + " "]
        for col in range(n_weeks):
            idx = col * 7 + row
            v = padded[idx] if idx < len(padded) else 0.0
            t = (v - lo) / span
            t = max(0.0, min(1.0, t))

            if v <= lo and min_val is None:
                r, g, b = _lerp_color(0.0, colors)
                parts.append(_rgb_fg(r, g, b, empty_char))
            else:
                r, g, b = _lerp_color(t, colors)
                parts.append(_rgb_fg(r, g, b, "█"))
        lines.append("".join(parts))

    if show_legend:
        lines.append("")
        legend_parts = ["  Less "]
        for k in range(10):
            t = k / 9
            r, g, b = _lerp_color(t, colors)
            legend_parts.append(_rgb_fg(r, g, b, "█"))
        legend_parts.append(" More")
        lines.append("".join(legend_parts))

    return "\n".join(lines)
