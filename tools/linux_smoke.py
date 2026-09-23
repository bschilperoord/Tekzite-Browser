from __future__ import annotations

"""Small Linux integration smoke for Tekzite's real Chromium/CDP renderer.

Run under an X/Wayland display, for example:
    xvfb-run -a python tools/linux_smoke.py
"""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    if not sys.platform.startswith("linux"):
        print("Linux smoke skipped: not running on Linux")
        return 0

    # Hosted Linux runners can expose a distro Chromium wrapper alongside a
    # directly executable Chrome. Prefer the direct Chrome binary for this
    # integration smoke, while normal Tekzite desktop discovery remains
    # Chromium-first unless TEKZITE_CHROMIUM is explicitly set by the user.
    if not os.environ.get("TEKZITE_CHROMIUM"):
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                os.environ["TEKZITE_CHROMIUM"] = found
                break

    state = Path(tempfile.mkdtemp(prefix="tekzite-linux-smoke-state-"))
    os.environ["XDG_STATE_HOME"] = str(state)
    pref_dir = state / "tekzite-browser"
    pref_dir.mkdir(parents=True, exist_ok=True)
    (pref_dir / "preferences.json").write_text(json.dumps({
        "startup": "blank",
        "restore_tabs": False,
        "privacy_lockdown": True,
        "quiet_mode": True,
        "https_first": False,
        "page_zoom_percent": 100,
        "customization": {"animations": False},
    }), encoding="utf-8")

    import main as browser_main
    import engine.net as net

    app = browser_main.BrowserApp()
    started = time.monotonic()
    result = {"ok": False, "frame": False, "input": False, "socket_monitor": False}

    def finish(code=0):
        try:
            app.on_close()
        except Exception:
            try:
                app.root.destroy()
            except Exception:
                pass
        result["elapsed_s"] = round(time.monotonic() - started, 2)
        print(json.dumps(result, sort_keys=True))
        app._linux_smoke_exit_code = int(code)

    def fail(message):
        result["error"] = str(message)
        finish(1)

    def verify_input(target_id):
        try:
            net._persistent_page_cdp_call(
                net._EDGE_SESSION,
                "Runtime.evaluate",
                {"expression": "document.getElementById('tekziteSmokeInput').focus()", "returnByValue": True},
                target_id=target_id,
                timeout=2,
                purpose="linux-smoke",
            )
            net.dispatch_embedded_chromium_key(
                key="a", text="a", event_type="char", target_id=target_id, timeout=2
            )
            value = net._persistent_page_cdp_call(
                net._EDGE_SESSION,
                "Runtime.evaluate",
                {"expression": "document.getElementById('tekziteSmokeInput').value", "returnByValue": True},
                target_id=target_id,
                timeout=2,
                purpose="linux-smoke",
            )
            actual = (((value or {}).get("result") or {}).get("value"))
            result["input"] = actual == "a"
            sockets = net.live_socket_snapshot()
            result["socket_monitor"] = bool(sockets.get("supported"))
            result["socket_rows"] = len(sockets.get("rows") or [])
            if not result["socket_monitor"]:
                result["socket_message"] = str(sockets.get("message") or "")[:240]
            result["ok"] = bool(result["frame"] and result["input"] and result["socket_monitor"])
            finish(0 if result["ok"] else 1)
        except Exception as exc:
            fail(f"input/socket verification failed: {type(exc).__name__}: {exc}")

    def wait_for_frame(target_id, deadline):
        try:
            photo = getattr(app, "_chromium_frame_photo", None)
            if photo is not None and int(photo.width()) >= 320 and int(photo.height()) >= 200:
                result["frame"] = True
                app.root.after(0, verify_input, target_id)
                return
        except Exception:
            pass
        if time.monotonic() >= deadline:
            fail("software compositor did not present a frame")
            return
        app.root.after(50, wait_for_frame, target_id, deadline)

    def inject_content(target_id):
        try:
            expression = r'''(() => {
              document.title = 'Tekzite Linux Smoke';
              document.body.innerHTML = '<main style="font:32px sans-serif;padding:40px">Linux renderer works<br><input id="tekziteSmokeInput" autofocus></main>';
              return true;
            })()'''
            net._persistent_page_cdp_call(
                net._EDGE_SESSION,
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True},
                target_id=target_id,
                timeout=2,
                purpose="linux-smoke",
            )
            app._chromium_last_frame_signature = None
            app._mark_chromium_interaction(1.0)
            app.root.after(0, app._request_chromium_software_frame, app._chromium_frame_generation)
            app.root.after(50, wait_for_frame, target_id, time.monotonic() + 5.0)
        except Exception as exc:
            fail(f"content injection failed: {type(exc).__name__}: {exc}")

    def wait_for_target(deadline):
        tab = app._active_tab()
        target_id = str((tab or {}).get("chromium_target_id") or "")
        if target_id and getattr(app, "_chromium_software_mode", False):
            inject_content(target_id)
            return
        if time.monotonic() >= deadline:
            result["chromium"] = os.environ.get("TEKZITE_CHROMIUM", "")
            debug = dict(getattr(net, "_CHROMIUM_LAUNCH_DEBUG", {}) or {})
            for key in ("errors", "last_error", "executable", "attempts", "port",
                        "devtools_ready_ms", "process_spawn_ms", "linux_root_no_sandbox"):
                if key in debug:
                    result[f"launch_{key}"] = debug.get(key)
            fail(f"Chromium target did not become ready: {app.status_var.get()}")
            return
        app.root.after(50, wait_for_target, deadline)

    def start():
        app.navigate_to("about:blank", add_history=True, reuse_existing=False)
        app.root.after(50, wait_for_target, time.monotonic() + 18.0)

    app._linux_smoke_exit_code = 1
    app.root.after(350, start)
    app.root.after(35000, lambda: fail("overall smoke timeout"))
    app.root.mainloop()
    code = int(getattr(app, "_linux_smoke_exit_code", 1))
    shutil.rmtree(state, ignore_errors=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
