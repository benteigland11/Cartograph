"""Terminal sparkline charts using Unicode block characters.

Renders compact, inline sparkline visualizations from numeric data series.
Supports color gradients, multi-line compositions, labels, and min/max markers.
"""

from typing import Sequence

BLOCKS = " ▁▂▃▄▅▆▇█"

# ANSI color helpers
def _ansi(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def _rgb_fg(r: int, g: int, b: int, text: str) -> str:
    return f"\033[38;2;{r};{g};{b}m{text}\033[0m"


def _lerp_color(
    t: float,
    colors: list[tuple[int, int, int]],
) -> tuple[int, int, int]:
    """Linearly interpolate between a list of RGB color stops."""
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


# ─── Presets ──────────────────────────────────────────────────────────
COLOR_PRESETS: dict[str, list[tuple[int, int, int]]] = {
    "green":   [(34, 197, 94)],
    "red":     [(239, 68, 68)],
    "blue":    [(59, 130, 246)],
    "cyan":    [(6, 182, 212)],
    "yellow":  [(234, 179, 8)],
    "fire":    [(59, 130, 246), (234, 179, 8), (239, 68, 68)],
    "ice":     [(147, 197, 253), (59, 130, 246), (30, 58, 138)],
    "emerald": [(167, 243, 208), (16, 185, 129), (6, 78, 59)],
    "sunset":  [(253, 186, 116), (239, 68, 68), (127, 29, 29)],
    "plasma":  [(13, 8, 135), (126, 3, 168), (240, 249, 33)],
}


def _resolve_colors(
    color: str | list[tuple[int, int, int]] | None,
) -> list[tuple[int, int, int]] | None:
    if color is None:
        return None
    if isinstance(color, str):
        return COLOR_PRESETS.get(color)
    return color


# ─── Core ─────────────────────────────────────────────────────────────
def sparkline(
    data: Sequence[float | int],
    *,
    color: str | list[tuple[int, int, int]] | None = None,
    min_val: float | None = None,
    max_val: float | None = None,
    width: int | None = None,
    label: str | None = None,
    show_range: bool = False,
    show_current: bool = False,
    marker_min: bool = False,
    marker_max: bool = False,
) -> str:
    """Render a sparkline string from a numeric data series.

    Args:
        data: Sequence of numbers to visualize.
        color: Color preset name (e.g. "fire", "green") or list of RGB tuples.
        min_val: Override the minimum value for scaling.
        max_val: Override the maximum value for scaling.
        width: Resample data to fit this many columns.
        label: Prefix label shown before the sparkline.
        show_range: Append [min, max] after the sparkline.
        show_current: Append the last value after the sparkline.
        marker_min: Highlight the minimum value position.
        marker_max: Highlight the maximum value position.

    Returns:
        A string containing the rendered sparkline (with ANSI codes if colored).
    """
    if not data:
        return ""

    values = list(data)

    # Resample to target width via averaging
    if width and width < len(values):
        values = _resample(values, width)

    lo = min_val if min_val is not None else min(values)
    hi = max_val if max_val is not None else max(values)
    span = hi - lo if hi != lo else 1.0

    colors = _resolve_colors(color)
    num_blocks = len(BLOCKS) - 1

    min_idx = values.index(min(values))
    max_idx = values.index(max(values))

    chars: list[str] = []
    for i, v in enumerate(values):
        t = (v - lo) / span
        t = max(0.0, min(1.0, t))
        idx = int(t * num_blocks)
        idx = min(idx, num_blocks)
        ch = BLOCKS[idx]

        # Apply color
        if colors:
            r, g, b = _lerp_color(t, colors)
            ch = _rgb_fg(r, g, b, ch)

        # Markers: underline min, bold max
        if marker_min and i == min_idx:
            ch = _ansi("4", ch)  # underline
        if marker_max and i == max_idx:
            ch = _ansi("1", ch)  # bold

        chars.append(ch)

    line = "".join(chars)

    # Compose final string
    parts: list[str] = []
    if label:
        parts.append(f"{label} ")
    parts.append(line)
    if show_range:
        parts.append(f" [{min(values):.1f}, {max(values):.1f}]")
    if show_current:
        parts.append(f" {values[-1]:.1f}")

    return "".join(parts)


def sparkline_multi(
    series: dict[str, Sequence[float | int]],
    *,
    color: str | list[tuple[int, int, int]] | None = None,
    width: int | None = None,
    show_range: bool = False,
    align_labels: bool = True,
) -> str:
    """Render multiple labeled sparklines, vertically stacked.

    Args:
        series: Mapping of label -> data sequence.
        color: Shared color preset or RGB list for all lines.
        width: Resample all series to this width.
        show_range: Show [min, max] on each line.
        align_labels: Right-align labels to the longest name.

    Returns:
        Multi-line string with one sparkline per series.
    """
    if not series:
        return ""

    max_label = max(len(k) for k in series) if align_labels else 0

    lines: list[str] = []
    for name, data in series.items():
        padded = name.rjust(max_label) if align_labels else name
        line = sparkline(
            data,
            color=color,
            width=width,
            label=padded,
            show_range=show_range,
        )
        lines.append(line)

    return "\n".join(lines)


def sparkbar(
    value: float,
    max_value: float = 100.0,
    *,
    width: int = 20,
    color: str | list[tuple[int, int, int]] | None = None,
    label: str | None = None,
    show_percent: bool = True,
) -> str:
    """Render a single-value bar using block characters.

    Args:
        value: Current value.
        max_value: The value that represents a full bar.
        width: Total character width of the bar.
        color: Color preset or RGB list.
        label: Prefix label.
        show_percent: Append percentage after the bar.

    Returns:
        A string containing the rendered bar.
    """
    t = max(0.0, min(1.0, value / max_value)) if max_value else 0.0
    filled = int(t * width)
    remainder = (t * width) - filled

    colors = _resolve_colors(color)
    num_blocks = len(BLOCKS) - 1

    chars: list[str] = []
    for i in range(width):
        if i < filled:
            ch = BLOCKS[-1]  # full block
            ct = i / max(width - 1, 1)
        elif i == filled and remainder > 0:
            idx = int(remainder * num_blocks)
            ch = BLOCKS[max(idx, 1)]
            ct = i / max(width - 1, 1)
        else:
            ch = " "
            ct = 0.0

        if colors and ch != " ":
            r, g, b = _lerp_color(ct, colors)
            ch = _rgb_fg(r, g, b, ch)
        chars.append(ch)

    bar = "".join(chars)
    parts: list[str] = []
    if label:
        parts.append(f"{label} ")
    parts.append(f"▕{bar}▏")
    if show_percent:
        parts.append(f" {t * 100:.0f}%")

    return "".join(parts)


# ─── Helpers ──────────────────────────────────────────────────────────
def _resample(values: list[float], target: int) -> list[float]:
    """Downsample a list to target length by averaging buckets."""
    n = len(values)
    if target >= n:
        return values
    bucket_size = n / target
    result: list[float] = []
    for i in range(target):
        start = int(i * bucket_size)
        end = int((i + 1) * bucket_size)
        end = min(end, n)
        bucket = values[start:end]
        result.append(sum(bucket) / len(bucket) if bucket else 0.0)
    return result
