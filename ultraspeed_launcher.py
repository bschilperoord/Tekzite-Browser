from __future__ import annotations

"""Tekzite Browser low-latency executable entry point."""

import os
import subprocess

from ultraspeed_runtime import apply_ultraspeed


def _shutdown_network_engine_for_onefile() -> None:
    """Stop the bundled helper before PyInstaller removes its _MEI tree."""
    try:
        import engine.net as net
    except Exception:
        return

    state = getattr(net, "_NETWORK_ENGINE", None) or {}
    proc = state.get("process") if isinstance(state, dict) else None

    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            # The helper is itself a PyInstaller OneFile executable on Windows.
            # Kill its complete process tree if graceful shutdown times out so
            # no child keeps tekzite-network.exe open inside Tekzite's _MEI dir.
            if os.name == "nt" and proc.poll() is None:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(int(proc.pid)), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except Exception:
                    pass
            elif proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass

            # Reap the helper before control returns to the PyInstaller
            # bootloader, which immediately starts deleting the _MEI directory.
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

    # Release Tekzite's proxy state, loopback registration and log handle.
    try:
        net._stop_network_engine()
    except Exception:
        pass


def main() -> int:
    # Apply Windows latency tuning before importing Tk/Pillow/browser modules.
    apply_ultraspeed()

    from main import BrowserApp

    app = BrowserApp()
    try:
        app.run()
    finally:
        # Do this before Python/PyInstaller shutdown rather than relying only on
        # atexit, because Windows file handles can otherwise outlive _MEI cleanup.
        _shutdown_network_engine_for_onefile()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
