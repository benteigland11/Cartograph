"""
Example usage of Form Builder.

When run interactively in a terminal, launches a full interactive form.
When run non-interactively (piped, CI, etc.), prints a static demo showing
the field definitions and simulated output.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.form_builder import (
    run_form,
    TextField, PasswordField, NumberField,
    ConfirmField, SelectField, MultiSelectField,
    required, min_length, in_range, matches,
    _ansi,
)

fields = [
    TextField(
        name="username",
        label="Username",
        placeholder="e.g. johndoe",
        validators=[required, min_length(3)],
    ),
    PasswordField(
        name="password",
        label="Password",
        validators=[required, min_length(8)],
    ),
    TextField(
        name="email",
        label="Email",
        placeholder="you@example.com",
        validators=[required, matches(r".+@.+\..+", msg="Enter a valid email.")],
    ),
    NumberField(
        name="age",
        label="Age",
        default=25,
        step=1,
        validators=[in_range(13, 120)],
    ),
    SelectField(
        name="role",
        label="Role",
        options=["Developer", "Designer", "Manager", "Other"],
    ),
    MultiSelectField(
        name="languages",
        label="Languages",
        options=["Python", "TypeScript", "Rust", "Go", "Java"],
        defaults=[0],
        validators=[required],
    ),
    ConfirmField(
        name="agree",
        label="Accept terms?",
        default=False,
    ),
]

if sys.stdin.isatty():
    try:
        results = run_form(fields, title="Create Account")
        print("\n  Results:")
        for k, v in results.items():
            print(f"    {k}: {v}")
        print()
    except KeyboardInterrupt:
        print("\n  Cancelled.")
else:
    # Non-interactive: show what the form looks like after completion
    print("=" * 55)
    print("  FORM BUILDER — DEMO (non-interactive preview)")
    print("=" * 55)
    print()
    print("  Form: Create Account")
    print()

    # Simulate completed form output
    sample = {
        "username": "johndoe",
        "password": "********",
        "email": "john@example.com",
        "age": 28,
        "role": "Developer",
        "languages": "Python, Rust",
        "agree": "Yes",
    }
    for name, val in sample.items():
        print(f"  {_ansi('38;2;34;197;94', '✔')} {_ansi('1;37', name)}  {_ansi('2', str(val))}")

    print()
    print("  Field types supported:")
    print("    TextField, PasswordField, NumberField,")
    print("    ConfirmField, SelectField, MultiSelectField")
    print()
    print("  Validators: required, min_length, max_length, in_range, matches")
    print()
    print("  Run interactively: python examples/example_usage.py")
    print("=" * 55)
