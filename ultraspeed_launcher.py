from __future__ import annotations

"""Tekzite Browser low-latency executable entry point."""

import os
import sys
import time

from ultraspeed_runtime import apply_ultraspeed


def _shutdown_onefile_children() -> None:
    """Release every Tekzite child that can hold PyInstaller's _MEI tree open."""
    try:
        import engine.net as net
    except Exception:
        return

    # Chromium loads Tekzite's bundled unpacked extension from the OneFile
    # extraction tree, so Chromium must be gone before the PyInstaller
    # bootloader tries to delete that tree.
    session = getattr(net, "_EDGE_SESSION", None) or {}
    profile = session.get("profile") if isinstance(session, dict) else None

    try:
        net.close_embedded_chromium(clear_profile=False)
    except Exception:
        pass

    # close_embedded_chromium() normally terminates the exact Tekzite Chromium
    # process tree. Perform one profile-scoped verification/fallback because an
    # adopted Chromium process can outlive the launcher process that started it.
    if os.name == "nt" and profile:
        try:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if not net._profile_chromium_pids(profile):
                    break
                time.sleep(0.05)
            remaining = net._profile_chromium_pids(profile)
            if remaining:
                net._terminate_profile_chromium_processes(profile)
        except Exception:
            pass

    # The proxy helper is also bundled inside the outer OneFile extraction.
    # Stop/reap it only after Chromium no longer needs the proxy.
    try:
        net._stop_network_engine()
    except Exception:
        pass



def _linux_package_smoke() -> int:
    """Exercise the exact Pillow/Tk bridge used by the packaged Linux compositor."""
    if os.name == "nt":
        return 0
    root = None
    try:
        import tkinter as tk
        import PIL._tkinter_finder  # PyInstaller/Pillow Tk bridge.
        from PIL import Image, ImageTk

        root = tk.Tk()
        root.withdraw()
        image = Image.new("RGB", (2, 2), "black")
        photo = ImageTk.PhotoImage(image, master=root)
        root.update_idletasks()
        if int(photo.width()) != 2 or int(photo.height()) != 2:
            return 2
        return 0
    except Exception:
        return 1
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def main() -> int:
    # This path exists specifically so CI can execute the final PyInstaller
    # artifact and catch missing Pillow/Tk modules before publishing it.
    if "--linux-package-smoke" in sys.argv:
        return _linux_package_smoke()

    # Apply Windows latency tuning before importing Tk/Pillow/browser modules.
    apply_ultraspeed()

    from main import BrowserApp

    app = BrowserApp()
    try:
        app.run()
    finally:
        # Run while Python is still alive. Relying only on atexit is too late
        # for PyInstaller OneFile because the bootloader immediately starts
        # removing its _MEI extraction directory.
        _shutdown_onefile_children()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
