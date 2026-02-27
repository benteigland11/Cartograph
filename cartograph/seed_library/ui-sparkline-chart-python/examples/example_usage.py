"""
Example usage of Sparkline Chart.

This file must run cleanly with no external dependencies or network calls.
Use fake/hardcoded data to demonstrate the widget's logic.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from sparkline_chart import sparkline, sparkline_multi, sparkbar, COLOR_PRESETS
import math

print("=" * 60)
print("  SPARKLINE CHART — DEMO")
print("=" * 60)

# ─── Basic sparkline ──────────────────────────────────────
print("\n▸ Basic sparkline (no color)")
data = [4, 2, 7, 1, 8, 3, 6, 5, 9, 2, 4, 7]
print(f"  {sparkline(data)}")

# ─── With color presets ───────────────────────────────────
print("\n▸ Color presets")
for name in ["green", "fire", "ice", "plasma", "sunset", "emerald"]:
    print(f"  {name:>8}  {sparkline(data, color=name)}")

# ─── Sine wave ────────────────────────────────────────────
print("\n▸ Sine wave (50 points, 'plasma' gradient)")
sine = [math.sin(x * 0.2) for x in range(50)]
print(f"  {sparkline(sine, color='plasma')}")

# ─── With labels and stats ────────────────────────────────
print("\n▸ Labeled with range and current value")
cpu = [12, 28, 45, 62, 38, 71, 55, 83, 67, 44, 29, 56, 72, 61, 48]
print(f"  {sparkline(cpu, color='fire', label='CPU', show_range=True, show_current=True)}")

# ─── Markers ──────────────────────────────────────────────
print("\n▸ Min/max markers (underline=min, bold=max)")
print(f"  {sparkline(cpu, color='cyan', marker_min=True, marker_max=True)}")

# ─── Width resampling ─────────────────────────────────────
print("\n▸ 200 data points resampled to width=40")
big_data = [math.sin(x * 0.05) * 50 + math.cos(x * 0.13) * 30 for x in range(200)]
print(f"  {sparkline(big_data, color='emerald', width=40)}")

# ─── Multi-line dashboard ─────────────────────────────────
print("\n▸ Multi-line dashboard")
dashboard = {
    "CPU":    [12, 28, 45, 62, 38, 71, 55, 83, 67, 44, 29, 56],
    "Memory": [65, 66, 68, 71, 73, 72, 74, 76, 78, 77, 79, 80],
    "Disk":   [40, 40, 41, 41, 42, 42, 43, 43, 44, 44, 45, 45],
    "Net":    [5, 82, 14, 67, 3, 91, 22, 55, 8, 73, 31, 48],
}
print(sparkline_multi(dashboard, color="fire", show_range=True))

# ─── Sparkbars ────────────────────────────────────────────
print("\n▸ Sparkbars (single-value progress bars)")
metrics = [("CPU", 73), ("Memory", 86), ("Disk", 42), ("GPU", 95)]
for name, val in metrics:
    print(f"  {sparkbar(val, 100, color='fire', label=f'{name:>6}', width=30)}")

# ─── Custom RGB colors ────────────────────────────────────
print("\n▸ Custom RGB gradient (pink → purple → indigo)")
custom_colors = [(236, 72, 153), (168, 85, 247), (99, 102, 241)]
print(f"  {sparkline(sine, color=custom_colors)}")

print("\n" + "=" * 60)
