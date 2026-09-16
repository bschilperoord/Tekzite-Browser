from __future__ import annotations

"""Tekzite Browser low-latency executable entry point."""

from ultraspeed_runtime import apply_ultraspeed


def main() -> int:
    # Apply Windows latency tuning before importing Tk/Pillow/browser modules.
    apply_ultraspeed()

    from main import BrowserApp

    app = BrowserApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
