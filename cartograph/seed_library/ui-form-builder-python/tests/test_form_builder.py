import sys, os
from unittest.mock import patch
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from form_builder import (
    TextField, PasswordField, NumberField, ConfirmField,
    SelectField, MultiSelectField, Theme, DEFAULT_THEME,
    required, min_length, max_length, in_range, matches,
    run_form,
    _run_validators, _ansi, _clear_line, _move_up,
    _hide_cursor, _show_cursor,
    _prompt_text, _prompt_password, _prompt_number,
    _prompt_confirm, _prompt_select, _prompt_multiselect,
)


def _mock_keys(keys: list[str]):
    """Create a mock for _read_key that returns keys in sequence."""
    it = iter(keys)
    def _fake_read_key(stream=None):
        return next(it)
    return _fake_read_key


# ─── Validators ───────────────────────────────────────────────────────

def test_required_rejects_empty():
    assert required("") is not None
    assert required("  ") is not None
    assert required(None) is not None


def test_required_accepts_value():
    assert required("hello") is None
    assert required("x") is None


def test_required_rejects_empty_list():
    assert required([]) is not None


def test_required_accepts_list():
    assert required(["a"]) is None


def test_min_length_rejects_short():
    v = min_length(5)
    assert v("abc") is not None
    assert v("") is not None


def test_min_length_accepts_long():
    v = min_length(5)
    assert v("hello") is None
    assert v("hello world") is None


def test_max_length_rejects_long():
    v = max_length(5)
    assert v("toolong") is not None


def test_max_length_accepts_short():
    v = max_length(5)
    assert v("ok") is None
    assert v("exact") is None


def test_in_range_rejects_outside():
    v = in_range(1, 10)
    assert v(0) is not None
    assert v(11) is not None
    assert v(-5) is not None


def test_in_range_accepts_inside():
    v = in_range(1, 10)
    assert v(1) is None
    assert v(5) is None
    assert v(10) is None


def test_matches_rejects_mismatch():
    v = matches(r"^\d+$")
    assert v("abc") is not None
    assert v("12a") is not None


def test_matches_accepts_match():
    v = matches(r"^\d+$")
    assert v("123") is None
    assert v("0") is None


def test_matches_custom_message():
    v = matches(r"^[a-z]+$", msg="Only lowercase letters.")
    err = v("ABC")
    assert err == "Only lowercase letters."


def test_run_validators_chain():
    validators = [required, min_length(3)]
    assert _run_validators("", validators) is not None
    assert _run_validators("ab", validators) is not None
    assert _run_validators("abc", validators) is None


def test_run_validators_empty_list():
    assert _run_validators("anything", []) is None


# ─── Field construction ───────────────────────────────────────────────

def test_text_field_defaults():
    f = TextField(name="user", label="Username")
    assert f.name == "user"
    assert f.default == ""
    assert f.placeholder == ""
    assert f.validators == []


def test_text_field_with_options():
    f = TextField(
        name="email", label="Email",
        default="a@b.com", placeholder="you@example.com",
        validators=[required],
    )
    assert f.default == "a@b.com"
    assert len(f.validators) == 1


def test_password_field():
    f = PasswordField(name="pw", label="Password", mask="•")
    assert f.mask == "•"


def test_number_field():
    f = NumberField(name="age", label="Age", default=25, step=1)
    assert f.default == 25
    assert f.step == 1


def test_confirm_field():
    f = ConfirmField(name="ok", label="Proceed?", default=True)
    assert f.default is True


def test_select_field():
    f = SelectField(name="color", label="Color", options=["Red", "Blue", "Green"])
    assert len(f.options) == 3
    assert f.default == 0


def test_multiselect_field():
    f = MultiSelectField(
        name="langs", label="Languages",
        options=["Python", "Rust", "Go"],
        defaults=[0, 2],
    )
    assert f.defaults == [0, 2]


# ─── Theme ────────────────────────────────────────────────────────────

def test_default_theme():
    t = DEFAULT_THEME
    assert t.prompt == "1;37"
    assert t.accent == "38;2;99;102;241"


def test_custom_theme():
    t = Theme(prompt="1;33", accent="38;2;255;0;0")
    assert t.prompt == "1;33"


# ─── ANSI helpers ─────────────────────────────────────────────────────

def test_ansi_wraps():
    result = _ansi("1;31", "bold red")
    assert result == "\033[1;31mbold red\033[0m"


def test_clear_line():
    assert _clear_line() == "\033[2K\r"


def test_move_up():
    assert _move_up(3) == "\033[3A"
    assert _move_up(0) == ""


def test_cursor_control():
    assert "\033[?25l" in _hide_cursor()
    assert "\033[?25h" in _show_cursor()


# ─── Interactive prompt tests (mocked _read_key) ─────────────────────

@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_text_basic(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["h", "i", "enter"])
    f = TextField(name="x", label="Name")
    result = _prompt_text(f, DEFAULT_THEME)
    assert result == "hi"


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_text_with_default(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["enter"])
    f = TextField(name="x", label="Name", default="preset")
    result = _prompt_text(f, DEFAULT_THEME)
    assert result == "preset"


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_text_backspace(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["a", "b", "backspace", "c", "enter"])
    f = TextField(name="x", label="Name")
    result = _prompt_text(f, DEFAULT_THEME)
    assert result == "ac"


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_text_validation_retry(mock_key, mock_out):
    # First enter fails (empty), then type valid input
    mock_key.side_effect = _mock_keys(["enter", "a", "b", "c", "enter"])
    f = TextField(name="x", label="Name", validators=[required])
    result = _prompt_text(f, DEFAULT_THEME)
    assert result == "abc"


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_text_placeholder(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["x", "enter"])
    f = TextField(name="x", label="Name", placeholder="type here")
    result = _prompt_text(f, DEFAULT_THEME)
    assert result == "x"


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_text_ctrl_c(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["ctrl-c"])
    f = TextField(name="x", label="Name")
    try:
        _prompt_text(f, DEFAULT_THEME)
        assert False, "Should have raised KeyboardInterrupt"
    except KeyboardInterrupt:
        pass


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_password_basic(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["s", "e", "c", "r", "e", "t", "enter"])
    f = PasswordField(name="pw", label="Password")
    result = _prompt_password(f, DEFAULT_THEME)
    assert result == "secret"


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_password_backspace(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["a", "b", "backspace", "c", "enter"])
    f = PasswordField(name="pw", label="Password")
    result = _prompt_password(f, DEFAULT_THEME)
    assert result == "ac"


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_password_validation(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["enter", "p", "a", "s", "s", "enter"])
    f = PasswordField(name="pw", label="Password", validators=[required])
    result = _prompt_password(f, DEFAULT_THEME)
    assert result == "pass"


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_password_ctrl_c(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["ctrl-c"])
    f = PasswordField(name="pw", label="Password")
    try:
        _prompt_password(f, DEFAULT_THEME)
        assert False
    except KeyboardInterrupt:
        pass


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_number_basic(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["enter"])
    f = NumberField(name="n", label="Count", default=42)
    result = _prompt_number(f, DEFAULT_THEME)
    assert result == 42.0


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_number_typing(mock_key, mock_out):
    # default=42 → buf is ['4','2'], backspace removes '2', then type '7' → '47'
    mock_key.side_effect = _mock_keys(["backspace", "7", "enter"])
    f = NumberField(name="n", label="Count", default=42)
    result = _prompt_number(f, DEFAULT_THEME)
    assert result == 47.0


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_number_arrows(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["up", "up", "up", "enter"])
    f = NumberField(name="n", label="Count", default=10, step=5)
    result = _prompt_number(f, DEFAULT_THEME)
    assert result == 25.0


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_number_down(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["down", "enter"])
    f = NumberField(name="n", label="Count", default=10, step=1)
    result = _prompt_number(f, DEFAULT_THEME)
    assert result == 9.0


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_number_invalid_then_valid(mock_key, mock_out):
    # default=0 → buf is ['0']. Backspace clears, type "." enter (invalid),
    # then type "5" enter (valid)
    mock_key.side_effect = _mock_keys([
        "backspace", ".", "enter",  # invalid: "." alone
        "backspace", "5", "enter",  # valid: "5"
    ])
    f = NumberField(name="n", label="Count", default=0)
    result = _prompt_number(f, DEFAULT_THEME)
    assert result == 5.0


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_number_validation(mock_key, mock_out):
    # default 0, enter fails range, then up to 5, enter passes
    mock_key.side_effect = _mock_keys(["enter", "up", "up", "up", "up", "up", "enter"])
    f = NumberField(name="n", label="Count", default=0, step=1, validators=[in_range(1, 10)])
    result = _prompt_number(f, DEFAULT_THEME)
    assert result == 5.0


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_number_ctrl_c(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["ctrl-c"])
    f = NumberField(name="n", label="Count")
    try:
        _prompt_number(f, DEFAULT_THEME)
        assert False
    except KeyboardInterrupt:
        pass


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_confirm_default_no(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["enter"])
    f = ConfirmField(name="ok", label="Sure?", default=False)
    result = _prompt_confirm(f, DEFAULT_THEME)
    assert result is False


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_confirm_default_yes(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["enter"])
    f = ConfirmField(name="ok", label="Sure?", default=True)
    result = _prompt_confirm(f, DEFAULT_THEME)
    assert result is True


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_confirm_toggle(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["right", "enter"])
    f = ConfirmField(name="ok", label="Sure?", default=False)
    result = _prompt_confirm(f, DEFAULT_THEME)
    assert result is True


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_confirm_y_key(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["y", "enter"])
    f = ConfirmField(name="ok", label="Sure?", default=False)
    result = _prompt_confirm(f, DEFAULT_THEME)
    assert result is True


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_confirm_n_key(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["n", "enter"])
    f = ConfirmField(name="ok", label="Sure?", default=True)
    result = _prompt_confirm(f, DEFAULT_THEME)
    assert result is False


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_confirm_tab_toggle(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["tab", "enter"])
    f = ConfirmField(name="ok", label="Sure?", default=False)
    result = _prompt_confirm(f, DEFAULT_THEME)
    assert result is True


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_confirm_ctrl_c(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["ctrl-c"])
    f = ConfirmField(name="ok", label="Sure?")
    try:
        _prompt_confirm(f, DEFAULT_THEME)
        assert False
    except KeyboardInterrupt:
        pass


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_select_first(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["enter"])
    f = SelectField(name="c", label="Color", options=["Red", "Blue", "Green"])
    result = _prompt_select(f, DEFAULT_THEME)
    assert result == "Red"


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_select_navigate(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["down", "down", "enter"])
    f = SelectField(name="c", label="Color", options=["Red", "Blue", "Green"])
    result = _prompt_select(f, DEFAULT_THEME)
    assert result == "Green"


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_select_wrap_around(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["up", "enter"])
    f = SelectField(name="c", label="Color", options=["Red", "Blue", "Green"])
    result = _prompt_select(f, DEFAULT_THEME)
    assert result == "Green"


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_select_ctrl_c(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["ctrl-c"])
    f = SelectField(name="c", label="Color", options=["Red", "Blue"])
    try:
        _prompt_select(f, DEFAULT_THEME)
        assert False
    except KeyboardInterrupt:
        pass


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_multiselect_defaults(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["enter"])
    f = MultiSelectField(
        name="l", label="Langs",
        options=["Python", "Rust", "Go"],
        defaults=[0, 2],
    )
    result = _prompt_multiselect(f, DEFAULT_THEME)
    assert result == ["Python", "Go"]


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_multiselect_toggle(mock_key, mock_out):
    # Start with defaults [0], toggle off 0, toggle on 1
    mock_key.side_effect = _mock_keys(["space", "down", "space", "enter"])
    f = MultiSelectField(
        name="l", label="Langs",
        options=["Python", "Rust", "Go"],
        defaults=[0],
    )
    result = _prompt_multiselect(f, DEFAULT_THEME)
    assert result == ["Rust"]


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_multiselect_validation(mock_key, mock_out):
    # Enter with nothing selected fails, then select first, enter passes
    mock_key.side_effect = _mock_keys(["enter", "space", "enter"])
    f = MultiSelectField(
        name="l", label="Langs",
        options=["Python", "Rust"],
        validators=[required],
    )
    result = _prompt_multiselect(f, DEFAULT_THEME)
    assert result == ["Python"]


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_prompt_multiselect_ctrl_c(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["ctrl-c"])
    f = MultiSelectField(name="l", label="Langs", options=["A", "B"])
    try:
        _prompt_multiselect(f, DEFAULT_THEME)
        assert False
    except KeyboardInterrupt:
        pass


# ─── run_form integration ─────────────────────────────────────────────

@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_run_form_basic(mock_key, mock_out):
    mock_key.side_effect = _mock_keys([
        "h", "i", "enter",   # text
        "y", "enter",        # confirm
    ])
    fields = [
        TextField(name="name", label="Name"),
        ConfirmField(name="ok", label="OK?"),
    ]
    result = run_form(fields)
    assert result == {"name": "hi", "ok": True}


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_run_form_with_title(mock_key, mock_out):
    mock_key.side_effect = _mock_keys(["enter"])
    fields = [ConfirmField(name="ok", label="OK?")]
    result = run_form(fields, title="My Form")
    assert result == {"ok": False}
    assert "My Form" in mock_out.getvalue()


@patch('sys.stdout', new_callable=StringIO)
@patch('form_builder._read_key')
def test_run_form_unknown_field_type(mock_key, mock_out):
    try:
        run_form(["not a field"])
        assert False
    except TypeError as e:
        assert "Unknown field type" in str(e)
