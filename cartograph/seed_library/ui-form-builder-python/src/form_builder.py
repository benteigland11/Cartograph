"""Declarative terminal form builder with validation.

Build interactive terminal forms from a simple field definition.
Supports text, password, number, confirm, select, and multiselect fields
with built-in and custom validation, color themes, and keyboard navigation.
"""

import sys
import tty
import termios
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

# ─── ANSI helpers ─────────────────────────────────────────────────────

def _ansi(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def _move_up(n: int = 1) -> str:
    return f"\033[{n}A" if n > 0 else ""


def _clear_line() -> str:
    return "\033[2K\r"


def _hide_cursor() -> str:
    return "\033[?25l"


def _show_cursor() -> str:
    return "\033[?25h"


# ─── Theme ────────────────────────────────────────────────────────────

@dataclass
class Theme:
    """Color theme for form rendering."""
    prompt: str = "1;37"       # bold white
    accent: str = "38;2;99;102;241"  # indigo
    success: str = "38;2;34;197;94"  # green
    error: str = "38;2;239;68;68"    # red
    dim: str = "2"             # dim
    highlight_bg: str = "48;2;55;65;81"  # slate bg
    pointer: str = "38;2;99;102;241"  # indigo


DEFAULT_THEME = Theme()


# ─── Validators ───────────────────────────────────────────────────────

def required(value: Any) -> str | None:
    """Reject empty values."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "This field is required."
    if isinstance(value, list) and len(value) == 0:
        return "Select at least one option."
    return None


def min_length(n: int) -> Callable[[str], str | None]:
    """Require at least n characters."""
    def _validate(value: str) -> str | None:
        if len(value.strip()) < n:
            return f"Must be at least {n} characters."
        return None
    return _validate


def max_length(n: int) -> Callable[[str], str | None]:
    """Allow at most n characters."""
    def _validate(value: str) -> str | None:
        if len(value.strip()) > n:
            return f"Must be at most {n} characters."
        return None
    return _validate


def in_range(lo: float, hi: float) -> Callable[[float], str | None]:
    """Require a number within [lo, hi]."""
    def _validate(value: float) -> str | None:
        if value < lo or value > hi:
            return f"Must be between {lo} and {hi}."
        return None
    return _validate


def matches(pattern: str, msg: str | None = None) -> Callable[[str], str | None]:
    """Require value to match a regex pattern."""
    import re
    compiled = re.compile(pattern)
    def _validate(value: str) -> str | None:
        if not compiled.match(value):
            return msg or f"Must match pattern: {pattern}"
        return None
    return _validate


# ─── Field definitions ────────────────────────────────────────────────

@dataclass
class TextField:
    """Single-line text input."""
    name: str
    label: str
    default: str = ""
    placeholder: str = ""
    validators: list[Callable] = field(default_factory=list)


@dataclass
class PasswordField:
    """Masked text input."""
    name: str
    label: str
    mask: str = "*"
    validators: list[Callable] = field(default_factory=list)


@dataclass
class NumberField:
    """Numeric input with optional step."""
    name: str
    label: str
    default: float = 0.0
    step: float = 1.0
    validators: list[Callable] = field(default_factory=list)


@dataclass
class ConfirmField:
    """Yes/No confirmation."""
    name: str
    label: str
    default: bool = False


@dataclass
class SelectField:
    """Single-choice selection from a list."""
    name: str
    label: str
    options: list[str] = field(default_factory=list)
    default: int = 0


@dataclass
class MultiSelectField:
    """Multiple-choice selection from a list."""
    name: str
    label: str
    options: list[str] = field(default_factory=list)
    defaults: list[int] = field(default_factory=list)
    validators: list[Callable] = field(default_factory=list)


FieldType = TextField | PasswordField | NumberField | ConfirmField | SelectField | MultiSelectField


# ─── Raw input ────────────────────────────────────────────────────────

def _read_key(stream=None) -> str:
    """Read a single keypress, handling arrow keys and special keys."""
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
                return {
                    "A": "up", "B": "down", "C": "right", "D": "left",
                }.get(code, "unknown")
            return "escape"
        if ch == "\r" or ch == "\n":
            return "enter"
        if ch == "\x7f" or ch == "\x08":
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


# ─── Field runners ────────────────────────────────────────────────────

def _run_validators(value: Any, validators: list[Callable]) -> str | None:
    for v in validators:
        err = v(value)
        if err:
            return err
    return None


def _prompt_text(f: TextField, theme: Theme, stream=None) -> str:
    """Run a text field prompt. Returns the entered string."""
    buf = list(f.default)
    error: str | None = None

    while True:
        # Render
        line = _clear_line()
        line += _ansi(theme.accent, "? ")
        line += _ansi(theme.prompt, f.label + " ")
        if buf:
            line += "".join(buf)
        elif f.placeholder:
            line += _ansi(theme.dim, f.placeholder)
        sys.stdout.write(line)
        if error:
            sys.stdout.write(f"\n{_clear_line()}{_ansi(theme.error, '  ✗ ' + error)}")
            sys.stdout.write(_move_up(1))
        sys.stdout.flush()

        key = _read_key(stream)
        if key == "ctrl-c":
            sys.stdout.write("\n" + _show_cursor())
            raise KeyboardInterrupt
        if key == "enter":
            val = "".join(buf)
            err = _run_validators(val, f.validators)
            if err:
                error = err
                continue
            # Finalize
            sys.stdout.write(_clear_line())
            sys.stdout.write(_ansi(theme.success, "✔ "))
            sys.stdout.write(_ansi(theme.prompt, f.label + " "))
            sys.stdout.write(_ansi(theme.dim, val or "(empty)"))
            if error:
                sys.stdout.write(f"\n{_clear_line()}")
                sys.stdout.write(_move_up(1))
            sys.stdout.write("\n")
            sys.stdout.flush()
            return val
        if key == "backspace":
            if buf:
                buf.pop()
                error = None
        elif len(key) == 1:
            buf.append(key)
            error = None


def _prompt_password(f: PasswordField, theme: Theme, stream=None) -> str:
    """Run a password field prompt. Returns the entered string."""
    buf: list[str] = []
    error: str | None = None

    while True:
        line = _clear_line()
        line += _ansi(theme.accent, "? ")
        line += _ansi(theme.prompt, f.label + " ")
        line += f.mask * len(buf) if buf else _ansi(theme.dim, "(hidden)")
        sys.stdout.write(line)
        if error:
            sys.stdout.write(f"\n{_clear_line()}{_ansi(theme.error, '  ✗ ' + error)}")
            sys.stdout.write(_move_up(1))
        sys.stdout.flush()

        key = _read_key(stream)
        if key == "ctrl-c":
            sys.stdout.write("\n" + _show_cursor())
            raise KeyboardInterrupt
        if key == "enter":
            val = "".join(buf)
            err = _run_validators(val, f.validators)
            if err:
                error = err
                continue
            sys.stdout.write(_clear_line())
            sys.stdout.write(_ansi(theme.success, "✔ "))
            sys.stdout.write(_ansi(theme.prompt, f.label + " "))
            sys.stdout.write(_ansi(theme.dim, f.mask * len(buf)))
            if error:
                sys.stdout.write(f"\n{_clear_line()}")
                sys.stdout.write(_move_up(1))
            sys.stdout.write("\n")
            sys.stdout.flush()
            return val
        if key == "backspace":
            if buf:
                buf.pop()
                error = None
        elif len(key) == 1:
            buf.append(key)
            error = None


def _prompt_number(f: NumberField, theme: Theme, stream=None) -> float:
    """Run a number field prompt. Returns the entered number."""
    buf = list(str(f.default) if f.default else "")
    error: str | None = None

    while True:
        line = _clear_line()
        line += _ansi(theme.accent, "? ")
        line += _ansi(theme.prompt, f.label + " ")
        line += "".join(buf) if buf else _ansi(theme.dim, "0")
        line += _ansi(theme.dim, f"  (↑/↓ step {f.step})")
        sys.stdout.write(line)
        if error:
            sys.stdout.write(f"\n{_clear_line()}{_ansi(theme.error, '  ✗ ' + error)}")
            sys.stdout.write(_move_up(1))
        sys.stdout.flush()

        key = _read_key(stream)
        if key == "ctrl-c":
            sys.stdout.write("\n" + _show_cursor())
            raise KeyboardInterrupt
        if key == "enter":
            raw = "".join(buf).strip() or "0"
            try:
                val = float(raw)
            except ValueError:
                error = "Not a valid number."
                continue
            err = _run_validators(val, f.validators)
            if err:
                error = err
                continue
            sys.stdout.write(_clear_line())
            sys.stdout.write(_ansi(theme.success, "✔ "))
            sys.stdout.write(_ansi(theme.prompt, f.label + " "))
            display = int(val) if val == int(val) else val
            sys.stdout.write(_ansi(theme.dim, str(display)))
            if error:
                sys.stdout.write(f"\n{_clear_line()}")
                sys.stdout.write(_move_up(1))
            sys.stdout.write("\n")
            sys.stdout.flush()
            return val
        if key == "up":
            raw = "".join(buf).strip() or "0"
            try:
                val = float(raw) + f.step
            except ValueError:
                val = f.step
            buf = list(str(int(val) if val == int(val) else val))
            error = None
        elif key == "down":
            raw = "".join(buf).strip() or "0"
            try:
                val = float(raw) - f.step
            except ValueError:
                val = -f.step
            buf = list(str(int(val) if val == int(val) else val))
            error = None
        elif key == "backspace":
            if buf:
                buf.pop()
                error = None
        elif key in "0123456789.-":
            buf.append(key)
            error = None


def _prompt_confirm(f: ConfirmField, theme: Theme, stream=None) -> bool:
    """Run a confirm field prompt. Returns True or False."""
    choice = f.default

    while True:
        line = _clear_line()
        line += _ansi(theme.accent, "? ")
        line += _ansi(theme.prompt, f.label + " ")
        if choice:
            line += _ansi(theme.accent, "Yes") + _ansi(theme.dim, " / No")
        else:
            line += _ansi(theme.dim, "Yes / ") + _ansi(theme.accent, "No")
        line += _ansi(theme.dim, "  (←/→)")
        sys.stdout.write(line)
        sys.stdout.flush()

        key = _read_key(stream)
        if key == "ctrl-c":
            sys.stdout.write("\n" + _show_cursor())
            raise KeyboardInterrupt
        if key == "enter":
            sys.stdout.write(_clear_line())
            sys.stdout.write(_ansi(theme.success, "✔ "))
            sys.stdout.write(_ansi(theme.prompt, f.label + " "))
            sys.stdout.write(_ansi(theme.dim, "Yes" if choice else "No"))
            sys.stdout.write("\n")
            sys.stdout.flush()
            return choice
        if key in ("left", "right", "tab"):
            choice = not choice
        if key == "y":
            choice = True
        if key == "n":
            choice = False


def _prompt_select(f: SelectField, theme: Theme, stream=None) -> str:
    """Run a select field prompt. Returns the selected option string."""
    cursor = f.default
    num = len(f.options)

    def _render() -> None:
        sys.stdout.write(_clear_line())
        sys.stdout.write(_ansi(theme.accent, "? "))
        sys.stdout.write(_ansi(theme.prompt, f.label))
        sys.stdout.write(_ansi(theme.dim, "  (↑/↓ to move, enter to select)"))
        sys.stdout.write("\n")
        for i, opt in enumerate(f.options):
            sys.stdout.write(_clear_line())
            if i == cursor:
                sys.stdout.write(_ansi(theme.pointer, "  ❯ "))
                sys.stdout.write(_ansi(f"{theme.highlight_bg};1", opt))
            else:
                sys.stdout.write(_ansi(theme.dim, "    " + opt))
            if i < num - 1:
                sys.stdout.write("\n")
        sys.stdout.flush()

    _render()

    while True:
        key = _read_key(stream)
        if key == "ctrl-c":
            sys.stdout.write("\n" + _show_cursor())
            raise KeyboardInterrupt
        if key == "enter":
            # Clear options, show final
            sys.stdout.write(_move_up(num - 1) if num > 1 else "")
            for _ in range(num):
                sys.stdout.write(_clear_line() + "\n")
            sys.stdout.write(_move_up(num))
            sys.stdout.write(_clear_line())
            sys.stdout.write(_ansi(theme.success, "✔ "))
            sys.stdout.write(_ansi(theme.prompt, f.label + " "))
            sys.stdout.write(_ansi(theme.dim, f.options[cursor]))
            sys.stdout.write("\n")
            sys.stdout.flush()
            return f.options[cursor]
        if key == "up":
            cursor = (cursor - 1) % num
        elif key == "down":
            cursor = (cursor + 1) % num
        # Redraw
        sys.stdout.write(_move_up(num - 1) if num > 1 else "")
        sys.stdout.write("\r")
        _render()


def _prompt_multiselect(f: MultiSelectField, theme: Theme, stream=None) -> list[str]:
    """Run a multiselect field prompt. Returns list of selected option strings."""
    cursor = 0
    selected = set(f.defaults)
    num = len(f.options)
    error: str | None = None

    def _render() -> None:
        sys.stdout.write(_clear_line())
        sys.stdout.write(_ansi(theme.accent, "? "))
        sys.stdout.write(_ansi(theme.prompt, f.label))
        sys.stdout.write(_ansi(theme.dim, "  (space to toggle, enter to confirm)"))
        sys.stdout.write("\n")
        for i, opt in enumerate(f.options):
            sys.stdout.write(_clear_line())
            check = _ansi(theme.success, "◉") if i in selected else _ansi(theme.dim, "○")
            if i == cursor:
                sys.stdout.write(_ansi(theme.pointer, "  ❯ "))
                sys.stdout.write(f"{check} ")
                sys.stdout.write(_ansi(f"{theme.highlight_bg};1", opt))
            else:
                sys.stdout.write(f"    {check} ")
                sys.stdout.write(_ansi(theme.dim, opt))
            if i < num - 1:
                sys.stdout.write("\n")
        if error:
            sys.stdout.write(f"\n{_clear_line()}{_ansi(theme.error, '  ✗ ' + error)}")
        sys.stdout.flush()

    _render()

    while True:
        key = _read_key(stream)
        if key == "ctrl-c":
            sys.stdout.write("\n" + _show_cursor())
            raise KeyboardInterrupt
        if key == "enter":
            result = [f.options[i] for i in sorted(selected)]
            err = _run_validators(result, f.validators)
            if err:
                error = err
                total_lines = num + (1 if error else 0)
                sys.stdout.write(_move_up(total_lines - 1) if total_lines > 1 else "")
                sys.stdout.write("\r")
                _render()
                continue
            # Clear and show final
            total_lines = num + (1 if error else 0)
            sys.stdout.write(_move_up(total_lines - 1) if total_lines > 1 else "")
            for _ in range(total_lines):
                sys.stdout.write(_clear_line() + "\n")
            sys.stdout.write(_move_up(total_lines))
            sys.stdout.write(_clear_line())
            sys.stdout.write(_ansi(theme.success, "✔ "))
            sys.stdout.write(_ansi(theme.prompt, f.label + " "))
            sys.stdout.write(_ansi(theme.dim, ", ".join(result) if result else "(none)"))
            sys.stdout.write("\n")
            sys.stdout.flush()
            return result
        if key == "space":
            if cursor in selected:
                selected.discard(cursor)
            else:
                selected.add(cursor)
            error = None
        elif key == "up":
            cursor = (cursor - 1) % num
        elif key == "down":
            cursor = (cursor + 1) % num
        # Redraw
        total_lines = num + (1 if error else 0)
        sys.stdout.write(_move_up(total_lines - 1) if total_lines > 1 else "")
        sys.stdout.write("\r")
        error = None
        _render()


# ─── Form runner ──────────────────────────────────────────────────────

_RUNNERS: dict[type, Callable] = {
    TextField: _prompt_text,
    PasswordField: _prompt_password,
    NumberField: _prompt_number,
    ConfirmField: _prompt_confirm,
    SelectField: _prompt_select,
    MultiSelectField: _prompt_multiselect,
}


def run_form(
    fields: Sequence[FieldType],
    *,
    theme: Theme | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Run an interactive form in the terminal.

    Args:
        fields: Sequence of field definitions to prompt.
        theme: Optional color theme override.
        title: Optional title displayed above the form.

    Returns:
        Dict mapping field names to their entered values.
    """
    t = theme or DEFAULT_THEME
    results: dict[str, Any] = {}

    sys.stdout.write(_hide_cursor())
    try:
        if title:
            sys.stdout.write("\n")
            sys.stdout.write(_ansi(f"{t.accent};1", f"  {title}"))
            sys.stdout.write("\n\n")
            sys.stdout.flush()

        for f in fields:
            runner = _RUNNERS.get(type(f))
            if runner is None:
                raise TypeError(f"Unknown field type: {type(f).__name__}")
            results[f.name] = runner(f, t)
    finally:
        sys.stdout.write(_show_cursor())
        sys.stdout.flush()

    return results
