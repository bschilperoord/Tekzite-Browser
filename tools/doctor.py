from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def ok(label: str, value: str) -> None:
    print(f"[OK]   {label}: {value}")


def warn(label: str, value: str) -> None:
    print(f"[WARN] {label}: {value}")


def fail(label: str, value: str) -> None:
    print(f"[FAIL] {label}: {value}")


def main() -> int:
    failures = 0
    print("Tekzite Browser environment doctor\n")

    if os.name == "nt":
        ok("Platform", f"Windows ({platform.platform()})")
        ok("Renderer backend", "native DWM/Chromium with software fallback")
    elif sys.platform.startswith("linux"):
        ok("Platform", f"Linux Preview ({platform.platform()})")
        ok("Renderer backend", "Chromium headless + CDP software compositor (X11/Wayland shell)")
        try:
            import tkinter  # noqa: F401
            ok("Tk", str(getattr(tkinter, "TkVersion", "installed")))
        except Exception as exc:
            failures += 1
            fail("Tk", f"not importable: {exc}")
    else:
        warn("Platform", f"{platform.platform()} (unsupported preview platform)")

    if sys.version_info >= (3, 10):
        ok("Python", sys.version.split()[0])
    else:
        failures += 1
        fail("Python", f"{sys.version.split()[0]} (3.10+ required)")

    try:
        import PIL  # noqa: F401
        ok("Pillow", getattr(PIL, "__version__", "installed"))
    except Exception as exc:
        failures += 1
        fail("Pillow", f"not importable: {exc}")

    try:
        from engine.net import _chromium_candidates
        candidates = list(_chromium_candidates())
    except Exception as exc:
        candidates = []
        warn("Chromium discovery", f"could not run discovery: {exc}")

    if candidates:
        ok("Chromium", candidates[0])
        if len(candidates) > 1:
            print("       alternatives:")
            for candidate in candidates[1:]:
                print(f"       - {candidate}")
    else:
        failures += 1
        fail("Chromium", "no supported Chromium/Chrome executable found")

    extension = ROOT / "chromium_zoom_extension" / "manifest.json"
    if extension.is_file():
        ok("Native zoom bridge", str(extension))
    else:
        failures += 1
        fail("Native zoom bridge", "manifest.json is missing")

    print()
    if failures:
        print(f"Doctor finished with {failures} blocking issue(s).")
        return 1
    print("Doctor found no blocking setup issues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
