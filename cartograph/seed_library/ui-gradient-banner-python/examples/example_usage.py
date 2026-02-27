"""
Example usage of Gradient Banner.

When run interactively, shows animated gradient banners.
When run non-interactively (piped), shows static demos.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from gradient_banner import gradient_banner, animate_banner, GRADIENT_PRESETS

print("=" * 60)
print("  GRADIENT BANNER — DEMO")
print("=" * 60)

# Static banners with different presets
for name in ["rainbow", "fire", "neon", "cyber", "vapor"]:
    print(f"\n  Preset: {name}")
    print(gradient_banner("HELLO", gradient=name, padding=0))

# Vertical gradient
print("\n  Vertical gradient (ice):")
print(gradient_banner("COOL", gradient="ice", direction="vertical", padding=0))

# Custom colors
print("\n  Custom gradient (pink to cyan):")
print(gradient_banner("WOW", gradient=[(255, 105, 180), (0, 255, 255)], padding=0))

# Animation (only in interactive terminal)
if sys.stdin.isatty():
    print("\n  Animated (3 seconds, Ctrl-C to skip):")
    try:
        animate_banner("HELLO WORLD", gradient="rainbow", duration=3.0, fps=24)
    except KeyboardInterrupt:
        pass
    print()

print("=" * 60)
