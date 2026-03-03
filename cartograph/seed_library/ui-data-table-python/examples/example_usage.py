"""
Example usage of Data Table.

Runs cleanly with no user input, no network calls, no external dependencies.
Shows static table rendering. Run interactively to use the keyboard browser.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.data_table import (
    render_table, interactive_table,
    Column, TableTheme,
    DEFAULT_BOX, ROUNDED_BOX, HEAVY_BOX,
)

EMPLOYEES = [
    {"name": "Alice Chen",    "dept": "Engineering", "level": "Senior",  "salary": 142000, "rating": 4.8},
    {"name": "Bob Martin",    "dept": "Design",       "level": "Mid",     "salary": 95000,  "rating": 4.2},
    {"name": "Carol White",   "dept": "Engineering", "level": "Lead",    "salary": 168000, "rating": 4.9},
    {"name": "Dave Kumar",    "dept": "Product",      "level": "Senior",  "salary": 138000, "rating": 4.5},
    {"name": "Eve Johnson",   "dept": "Engineering", "level": "Junior",  "salary": 82000,  "rating": 3.9},
    {"name": "Frank Lee",     "dept": "Design",       "level": "Senior",  "salary": 112000, "rating": 4.6},
    {"name": "Grace Park",    "dept": "Product",      "level": "Lead",    "salary": 155000, "rating": 4.7},
    {"name": "Henry Adams",   "dept": "Engineering", "level": "Mid",     "salary": 115000, "rating": 4.1},
]

COLUMNS = [
    Column(key="name",   label="Name",       min_width=12),
    Column(key="dept",   label="Department", min_width=12),
    Column(key="level",  label="Level",      align="center"),
    Column(key="salary", label="Salary",     align="right",
           formatter=lambda v: f"${v:,}"),
    Column(key="rating", label="Rating",     align="center",
           formatter=lambda v: "★" * int(v) + f" {v}"),
]

print("=" * 65)
print("  DATA TABLE — DEMO")
print("=" * 65)

# ─── Basic table ──────────────────────────────────────────
print("\n▸ Default style")
print(render_table(EMPLOYEES, COLUMNS, title="Employee Directory"))

# ─── Sorted ───────────────────────────────────────────────
print("\n▸ Sorted by salary (descending)")
print(render_table(
    EMPLOYEES, COLUMNS,
    sort_by="salary", sort_reverse=True,
    show_row_numbers=True,
))

# ─── Filtered ─────────────────────────────────────────────
print("\n▸ Filtered: Engineering only")
print(render_table(
    EMPLOYEES, COLUMNS,
    filter_fn=lambda r: r["dept"] == "Engineering",
    footer="Filter: dept = Engineering",
))

# ─── Rounded box ──────────────────────────────────────────
print("\n▸ Rounded box style")
print(render_table(EMPLOYEES, COLUMNS, box=ROUNDED_BOX, title="Rounded"))

# ─── Heavy box ────────────────────────────────────────────
print("\n▸ Heavy box style")
print(render_table(EMPLOYEES, COLUMNS[:3], box=HEAVY_BOX, title="Heavy"))

# ─── Interactive browser (TTY only) ───────────────────────
if sys.stdin.isatty():
    print("\n▸ Interactive browser (↑↓ navigate, s sort, / filter, Enter select, q quit)")
    result = interactive_table(EMPLOYEES, COLUMNS, title="Employee Browser", page_size=5)
    if result:
        print(f"\n  Selected: {result['name']} — {result['dept']}")
    else:
        print("\n  No selection.")

print("\n" + "=" * 65)
