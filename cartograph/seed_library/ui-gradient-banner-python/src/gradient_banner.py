"""Animated RGB gradient text banners for the terminal.

Renders large text using built-in block fonts with smoothly animated
color gradients. Supports static rendering, looping animations, and
customizable color palettes. Zero dependencies.
"""

import math
import sys
import time
from typing import Sequence

# ─── Built-in block font (6 rows tall) ───────────────────────────────
# Each character is a list of 6 strings, all same width.

_FONT: dict[str, list[str]] = {
    "A": [
        " ██ ",
        "█  █",
        "████",
        "█  █",
        "█  █",
        "    ",
    ],
    "B": [
        "███ ",
        "█  █",
        "███ ",
        "█  █",
        "███ ",
        "    ",
    ],
    "C": [
        " ███",
        "█   ",
        "█   ",
        "█   ",
        " ███",
        "    ",
    ],
    "D": [
        "███ ",
        "█  █",
        "█  █",
        "█  █",
        "███ ",
        "    ",
    ],
    "E": [
        "████",
        "█   ",
        "███ ",
        "█   ",
        "████",
        "    ",
    ],
    "F": [
        "████",
        "█   ",
        "███ ",
        "█   ",
        "█   ",
        "    ",
    ],
    "G": [
        " ███",
        "█   ",
        "█ ██",
        "█  █",
        " ███",
        "    ",
    ],
    "H": [
        "█  █",
        "█  █",
        "████",
        "█  █",
        "█  █",
        "    ",
    ],
    "I": [
        "███",
        " █ ",
        " █ ",
        " █ ",
        "███",
        "   ",
    ],
    "J": [
        " ███",
        "   █",
        "   █",
        "█  █",
        " ██ ",
        "    ",
    ],
    "K": [
        "█  █",
        "█ █ ",
        "██  ",
        "█ █ ",
        "█  █",
        "    ",
    ],
    "L": [
        "█   ",
        "█   ",
        "█   ",
        "█   ",
        "████",
        "    ",
    ],
    "M": [
        "█   █",
        "██ ██",
        "█ █ █",
        "█   █",
        "█   █",
        "     ",
    ],
    "N": [
        "█   █",
        "██  █",
        "█ █ █",
        "█  ██",
        "█   █",
        "     ",
    ],
    "O": [
        " ██ ",
        "█  █",
        "█  █",
        "█  █",
        " ██ ",
        "    ",
    ],
    "P": [
        "███ ",
        "█  █",
        "███ ",
        "█   ",
        "█   ",
        "    ",
    ],
    "Q": [
        " ██ ",
        "█  █",
        "█  █",
        "█ █ ",
        " ██▄",
        "    ",
    ],
    "R": [
        "███ ",
        "█  █",
        "███ ",
        "█ █ ",
        "█  █",
        "    ",
    ],
    "S": [
        " ███",
        "█   ",
        " ██ ",
        "   █",
        "███ ",
        "    ",
    ],
    "T": [
        "█████",
        "  █  ",
        "  █  ",
        "  █  ",
        "  █  ",
        "     ",
    ],
    "U": [
        "█  █",
        "█  █",
        "█  █",
        "█  █",
        " ██ ",
        "    ",
    ],
    "V": [
        "█   █",
        "█   █",
        " █ █ ",
        " █ █ ",
        "  █  ",
        "     ",
    ],
    "W": [
        "█   █",
        "█   █",
        "█ █ █",
        "██ ██",
        "█   █",
        "     ",
    ],
    "X": [
        "█   █",
        " █ █ ",
        "  █  ",
        " █ █ ",
        "█   █",
        "     ",
    ],
    "Y": [
        "█   █",
        " █ █ ",
        "  █  ",
        "  █  ",
        "  █  ",
        "     ",
    ],
    "Z": [
        "█████",
        "   █ ",
        "  █  ",
        " █   ",
        "█████",
        "     ",
    ],
    "0": [
        " ██ ",
        "█  █",
        "█  █",
        "█  █",
        " ██ ",
        "    ",
    ],
    "1": [
        " █ ",
        "██ ",
        " █ ",
        " █ ",
        "███",
        "   ",
    ],
    "2": [
        " ██ ",
        "█  █",
        "  █ ",
        " █  ",
        "████",
        "    ",
    ],
    "3": [
        "███ ",
        "   █",
        " ██ ",
        "   █",
        "███ ",
        "    ",
    ],
    "4": [
        "█  █",
        "█  █",
        "████",
        "   █",
        "   █",
        "    ",
    ],
    "5": [
        "████",
        "█   ",
        "███ ",
        "   █",
        "███ ",
        "    ",
    ],
    "6": [
        " ██ ",
        "█   ",
        "███ ",
        "█  █",
        " ██ ",
        "    ",
    ],
    "7": [
        "████",
        "   █",
        "  █ ",
        " █  ",
        " █  ",
        "    ",
    ],
    "8": [
        " ██ ",
        "█  █",
        " ██ ",
        "█  █",
        " ██ ",
        "    ",
    ],
    "9": [
        " ██ ",
        "█  █",
        " ███",
        "   █",
        " ██ ",
        "    ",
    ],
    " ": [
        "  ",
        "  ",
        "  ",
        "  ",
        "  ",
        "  ",
    ],
    "!": [
        "█",
        "█",
        "█",
        " ",
        "█",
        " ",
    ],
    ".": [
        " ",
        " ",
        " ",
        " ",
        "█",
        " ",
    ],
    ",": [
        " ",
        " ",
        " ",
        " ",
        "█",
        "▀",
    ],
    "-": [
        "   ",
        "   ",
        "███",
        "   ",
        "   ",
        "   ",
    ],
    ":": [
        " ",
        "█",
        " ",
        "█",
        " ",
        " ",
    ],
    "?": [
        " ██ ",
        "█  █",
        "  █ ",
        "    ",
        "  █ ",
        "    ",
    ],
    "/": [
        "   █",
        "  █ ",
        " █  ",
        "█   ",
        "    ",
        "    ",
    ],
    "'": [
        "█",
        "▀",
        " ",
        " ",
        " ",
        " ",
    ],
}

FONT_HEIGHT = 6


# ─── Color presets ────────────────────────────────────────────────────

GRADIENT_PRESETS: dict[str, list[tuple[int, int, int]]] = {
    "rainbow":  [(255, 0, 0), (255, 165, 0), (255, 255, 0), (0, 255, 0), (0, 100, 255), (128, 0, 255)],
    "fire":     [(255, 255, 0), (255, 165, 0), (255, 69, 0), (255, 0, 0), (139, 0, 0)],
    "ice":      [(224, 247, 255), (147, 197, 253), (59, 130, 246), (30, 64, 175), (30, 58, 138)],
    "neon":     [(0, 255, 136), (0, 200, 255), (136, 0, 255), (255, 0, 136)],
    "sunset":   [(255, 94, 77), (255, 154, 0), (255, 206, 0), (255, 94, 77)],
    "ocean":    [(0, 42, 72), (0, 100, 148), (0, 168, 204), (102, 216, 230), (200, 240, 248)],
    "cyber":    [(0, 255, 65), (0, 200, 255), (0, 255, 65)],
    "vapor":    [(255, 113, 206), (185, 103, 255), (1, 205, 254), (5, 255, 161), (185, 103, 255)],
    "gold":     [(139, 90, 0), (218, 165, 32), (255, 223, 0), (255, 236, 139), (255, 223, 0), (218, 165, 32)],
    "matrix":   [(0, 40, 0), (0, 100, 0), (0, 200, 0), (0, 255, 0), (150, 255, 150)],
}


# ─── Color interpolation ─────────────────────────────────────────────

def _lerp_color(
    t: float,
    colors: list[tuple[int, int, int]],
) -> tuple[int, int, int]:
    """Interpolate between color stops at position t ∈ [0, 1]."""
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


def _resolve_colors(
    gradient: str | list[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    if isinstance(gradient, str):
        return GRADIENT_PRESETS.get(gradient, GRADIENT_PRESETS["rainbow"])
    return gradient


# ─── Text to block grid ──────────────────────────────────────────────

def _text_to_grid(text: str) -> list[str]:
    """Convert text to a list of 6 row-strings using the block font."""
    upper = text.upper()
    rows: list[list[str]] = [[] for _ in range(FONT_HEIGHT)]

    for ch in upper:
        glyph = _FONT.get(ch)
        if glyph is None:
            glyph = _FONT[" "]
        for r in range(FONT_HEIGHT):
            rows[r].append(glyph[r])

    return ["".join(row) for row in rows]


# ─── Static gradient rendering ────────────────────────────────────────

def gradient_banner(
    text: str,
    *,
    gradient: str | list[tuple[int, int, int]] = "rainbow",
    direction: str = "horizontal",
    bold: bool = True,
    padding: int = 1,
) -> str:
    """Render text as a large gradient-colored block banner.

    Args:
        text: The text to render.
        gradient: Color preset name or list of RGB tuples.
        direction: "horizontal" or "vertical" gradient direction.
        bold: Apply bold ANSI styling.
        padding: Blank lines above/below the banner.

    Returns:
        Multi-line string with ANSI-colored block text.
    """
    colors = _resolve_colors(gradient)
    grid = _text_to_grid(text)
    if not grid or not grid[0]:
        return ""

    total_cols = len(grid[0])
    total_rows = len(grid)
    lines: list[str] = []

    for _ in range(padding):
        lines.append("")

    for r, row in enumerate(grid):
        chars: list[str] = []
        for c, ch in enumerate(row):
            if ch == " ":
                chars.append(" ")
                continue

            if direction == "vertical":
                t = r / max(total_rows - 1, 1)
            else:
                t = c / max(total_cols - 1, 1)

            red, green, blue = _lerp_color(t, colors)
            styled = _rgb_fg(red, green, blue, ch)
            if bold:
                styled = f"\033[1m{styled}"
            chars.append(styled)
        lines.append("".join(chars))

    for _ in range(padding):
        lines.append("")

    return "\n".join(lines)


# ─── Animated gradient ────────────────────────────────────────────────

def gradient_banner_frame(
    text: str,
    *,
    gradient: str | list[tuple[int, int, int]] = "rainbow",
    direction: str = "horizontal",
    bold: bool = True,
    offset: float = 0.0,
    wave: bool = True,
    wave_amplitude: float = 0.15,
    wave_frequency: float = 0.3,
) -> str:
    """Render a single animation frame with shifted gradient.

    Args:
        text: The text to render.
        gradient: Color preset or RGB list.
        direction: "horizontal" or "vertical".
        bold: Apply bold styling.
        offset: Gradient phase offset (0.0 to 1.0, wraps).
        wave: Add sinusoidal wave distortion to the gradient.
        wave_amplitude: Strength of wave effect.
        wave_frequency: Speed of wave oscillation per column.

    Returns:
        Multi-line string for one animation frame.
    """
    colors = _resolve_colors(gradient)
    grid = _text_to_grid(text)
    if not grid or not grid[0]:
        return ""

    total_cols = len(grid[0])
    total_rows = len(grid)
    lines: list[str] = []

    for r, row in enumerate(grid):
        chars: list[str] = []
        for c, ch in enumerate(row):
            if ch == " ":
                chars.append(" ")
                continue

            if direction == "vertical":
                t = r / max(total_rows - 1, 1)
            else:
                t = c / max(total_cols - 1, 1)

            # Apply offset (shifting gradient)
            t = (t + offset) % 1.0

            # Apply wave
            if wave:
                wave_val = math.sin(c * wave_frequency + offset * math.pi * 2) * wave_amplitude
                t = (t + wave_val) % 1.0

            t = max(0.0, min(1.0, t))
            red, green, blue = _lerp_color(t, colors)
            styled = _rgb_fg(red, green, blue, ch)
            if bold:
                styled = f"\033[1m{styled}"
            chars.append(styled)
        lines.append("".join(chars))

    return "\n".join(lines)


def animate_banner(
    text: str,
    *,
    gradient: str | list[tuple[int, int, int]] = "rainbow",
    direction: str = "horizontal",
    bold: bool = True,
    speed: float = 0.03,
    fps: float = 30.0,
    duration: float | None = None,
    wave: bool = True,
    wave_amplitude: float = 0.15,
    wave_frequency: float = 0.3,
) -> None:
    """Animate a gradient banner in the terminal.

    Args:
        text: The text to render.
        gradient: Color preset or RGB list.
        direction: "horizontal" or "vertical".
        bold: Apply bold styling.
        speed: How fast the gradient shifts per frame.
        fps: Target frames per second.
        duration: Stop after this many seconds (None = run until Ctrl-C).
        wave: Enable wave distortion.
        wave_amplitude: Wave strength.
        wave_frequency: Wave oscillation rate.
    """
    grid = _text_to_grid(text)
    num_rows = len(grid)
    frame_time = 1.0 / fps
    offset = 0.0
    start = time.monotonic()

    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            if duration is not None and (time.monotonic() - start) >= duration:
                break

            frame = gradient_banner_frame(
                text,
                gradient=gradient,
                direction=direction,
                bold=bold,
                offset=offset,
                wave=wave,
                wave_amplitude=wave_amplitude,
                wave_frequency=wave_frequency,
            )
            sys.stdout.write(frame)
            sys.stdout.flush()

            offset = (offset + speed) % 1.0
            time.sleep(frame_time)

            # Move cursor back up to overwrite
            sys.stdout.write(f"\033[{num_rows}A\r")
    except KeyboardInterrupt:
        pass
    finally:
        # Move below the banner and show cursor
        sys.stdout.write(f"\033[{num_rows}B\r")
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


# ─── Convenience ──────────────────────────────────────────────────────

def get_font_chars() -> list[str]:
    """Return all characters supported by the built-in font."""
    return sorted(_FONT.keys())
