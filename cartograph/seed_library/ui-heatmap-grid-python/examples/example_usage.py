"""
Example usage of Heatmap Grid.

This file runs cleanly with no user input, no network calls,
and no external dependencies.
"""
import sys, os
import math
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.heatmap_grid import heatmap, heatmap_compact, calendar_heatmap, COLOR_PRESETS

print("=" * 60)
print("  HEATMAP GRID — DEMO")
print("=" * 60)

# ─── Basic heatmap ────────────────────────────────────────
print("\n▸ Basic 5x8 heatmap (heat palette)")
data = [
    [2, 4, 6, 8, 10, 12, 14, 16],
    [3, 6, 9, 12, 15, 18, 21, 24],
    [1, 3, 7, 15, 31, 15, 7, 3],
    [16, 14, 12, 10, 8, 6, 4, 2],
    [8, 8, 8, 20, 20, 8, 8, 8],
]
print(heatmap(data))

# ─── With labels and values ───────────────────────────────
print("\n▸ Labeled heatmap with values (viridis)")
corr = [
    [1.00, 0.85, 0.30, -0.10],
    [0.85, 1.00, 0.50, 0.05],
    [0.30, 0.50, 1.00, 0.70],
    [-0.10, 0.05, 0.70, 1.00],
]
labels = ["Temp", "Humid", "Wind", "Rain"]
print(heatmap(
    corr,
    palette="viridis",
    row_labels=labels,
    col_labels=labels,
    show_values=True,
    value_fmt=".2f",
    cell_width=6,
    title="Correlation Matrix",
))

# ─── Compact heatmap ──────────────────────────────────────
print("\n▸ Compact heatmap (1 char per cell, plasma)")
wave = []
for y in range(10):
    row = []
    for x in range(40):
        row.append(math.sin(x * 0.3) * math.cos(y * 0.4) + 1)
    wave.append(row)
print(heatmap_compact(wave, palette="plasma"))

# ─── All color presets ────────────────────────────────────
print("\n▸ Color presets comparison (same data)")
sample = [[i + j * 3 for i in range(12)] for j in range(3)]
for name in ["heat", "cool", "viridis", "magma", "inferno", "greens", "blues", "grayscale"]:
    print(f"  {name:>10}  ", end="")
    # Inline compact
    lines = heatmap_compact(sample, palette=name).split("\n")
    print(lines[0])  # just first row for comparison

# ─── Heatmap with legend ──────────────────────────────────
print("\n▸ With legend (magma)")
print(heatmap(
    [[i * j for j in range(8)] for i in range(5)],
    palette="magma",
    show_legend=True,
    value_fmt=".0f",
))

# ─── Calendar heatmap ─────────────────────────────────────
print("\n▸ GitHub-style calendar heatmap (52 weeks)")
random.seed(42)
contributions = [0] * 364
for i in range(364):
    if random.random() > 0.3:
        contributions[i] = int(random.paretovariate(1.5))
print(calendar_heatmap(contributions, palette="greens"))

# ─── Per-row normalization ────────────────────────────────
print("\n▸ Per-row normalization (different scales)")
multi_scale = [
    [1, 2, 3, 4, 5],
    [100, 200, 300, 400, 500],
    [0.01, 0.02, 0.03, 0.04, 0.05],
]
print(heatmap(
    multi_scale,
    palette="cool",
    row_labels=["Small", "Big", "Tiny"],
    per_row=True,
    show_values=True,
    value_fmt=".2f",
    cell_width=7,
))

print("\n" + "=" * 60)
