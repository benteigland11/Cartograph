"""
Interactive pending-widget review workflow.
"""

import json
import os
import shutil


def review_pending_widgets(carto):
    from cartographer import PENDING_WIDGETS_PATH

    if not os.path.exists(PENDING_WIDGETS_PATH):
        print("✅ No pending widgets to review!")
        return

    pending = []
    for item in os.listdir(PENDING_WIDGETS_PATH):
        widget_path = os.path.join(PENDING_WIDGETS_PATH, item)
        manifest_path = os.path.join(widget_path, "widget.json")
        if os.path.isdir(widget_path) and os.path.exists(manifest_path):
            try:
                with open(manifest_path) as f:
                    pending.append({"folder": item, "path": widget_path, "manifest": json.load(f)})
            except Exception:
                continue

    if not pending:
        print("✅ No pending widgets to review!")
        return

    print(f"\n📋 Found {len(pending)} pending widget(s)\n{'=' * 80}")

    for idx, widget in enumerate(pending, 1):
        meta = widget["manifest"].get("meta", {})
        widget_id = meta.get("id", "unknown")
        widget_name = meta.get("name", "Unknown")
        differentiation = meta.get("differentiation", "")
        similar_widgets = meta.get("similar_widgets", [])

        print(f"\n[{idx}/{len(pending)}] {widget_name} ({widget_id})\n{'-' * 80}")

        if similar_widgets:
            print("\n⚠️  Similar to existing widgets:")
            for sim_id in similar_widgets:
                sim = next((w for w in carto.widgets if w["id"] == sim_id), None)
                if sim:
                    print(f"  • {sim_id}\n    {sim['description'][:70]}...\n    Maturity: {sim.get('maturity', 'unknown')}")
                else:
                    print(f"  • {sim_id}")

        if differentiation:
            print(f"\n💡 Differentiation: {differentiation}")
        print(f"\n📁 Location: {widget['path']}")

        while True:
            choice = input("\n❓ Action: [a]pprove  [r]eject  [i]nspect  [s]kip  [q]uit: ").strip().lower()
            if choice == "a":
                _approve(carto, widget)
                break
            elif choice == "r":
                _reject(widget)
                break
            elif choice == "i":
                print("\n" + json.dumps(widget["manifest"], indent=2))
            elif choice == "s":
                print("⏭️  Skipped")
                break
            elif choice == "q":
                print("\n👋 Review session ended")
                return
            else:
                print("Invalid choice. Please choose a, r, i, s, or q.")

        print(f"\n{'=' * 80}")

    print("\n✅ Review complete!")


def _approve(carto, widget):
    dest_path = os.path.join(carto.library_path, widget["folder"])
    if os.path.exists(dest_path):
        print(f"❌ Error: Widget already exists in library: {dest_path}")
        return
    manifest_path = os.path.join(widget["path"], "widget.json")
    data = widget["manifest"]
    if "needs_review" in data.get("meta", {}):
        data["meta"]["needs_review"] = False
        with open(manifest_path, "w") as f:
            json.dump(data, f, indent=2)
    shutil.move(widget["path"], dest_path)
    print(f"✅ Approved! Moved to Widget_Library/{widget['folder']}")


def _reject(widget):
    widget_id = widget["manifest"].get("meta", {}).get("id", "unknown")
    confirm = input(f"⚠️  Delete {widget_id} permanently? [y/N]: ").strip().lower()
    if confirm == "y":
        shutil.rmtree(widget["path"])
        print(f"🗑️  Deleted {widget_id}")
    else:
        print("❌ Cancelled")
