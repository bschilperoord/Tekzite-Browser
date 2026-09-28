#!/usr/bin/env python3
"""End-to-end Windows smoke for Tekzite's Tk JavaScript dialog handoff."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main as tekzite_main
from engine import net


def _find_button(widget, text):
    try:
        children = list(widget.winfo_children())
    except Exception:
        return None
    for child in children:
        try:
            if child.winfo_class() == "Button" and str(child.cget("text")) == text:
                return child
        except Exception:
            pass
        found = _find_button(child, text)
        if found is not None:
            return found
    return None


def _dialog_debug(app):
    tab = app._active_tab() or {}
    session = net._CHROMIUM_SESSION or {}
    target_id = str(tab.get("chromium_target_id") or "")
    channel = (session.get("javascript_dialog_browser_channels") or {}).get(target_id) or {}
    try:
        pages = net._devtools_json(session.get("port"), "/json/list", timeout=0.5) if session.get("port") else []
    except Exception as exc:
        pages = [{"list_error": f"{type(exc).__name__}: {exc}"}]
    return {
        "active_tab_id": getattr(app, "active_tab_id", None),
        "tab_url": tab.get("url"),
        "tab_target_id": target_id,
        "frame_target_id": getattr(app, "_chromium_frame_target_id", None),
        "session_target_id": session.get("target_id"),
        "session_active_target_id": session.get("active_target_id"),
        "dwm_mode": getattr(app, "_chromium_dwm_mode", None),
        "dwm_ready": getattr(app, "_dwm_surface_ready", None),
        "dwm_visible": getattr(app, "_dwm_host_visible", None),
        "dialog_after_id": getattr(app, "_javascript_dialog_after_id", None),
        "dialog_poll_busy": getattr(app, "_javascript_dialog_poll_busy", None),
        "dialog_window": bool(getattr(app, "_javascript_dialog_window", None)),
        "confirm_eval_done": bool(
            getattr(app, "_tekzite_smoke_arm_future", None)
            and getattr(app, "_tekzite_smoke_arm_future").done()
        ),
        "channel_session_id": channel.get("session_id"),
        "channel_closed": channel.get("closed"),
        "channel_dialog_open": channel.get("dialog_open"),
        "channel_events": channel.get("events"),
        "channel_calls": channel.get("calls"),
        "pages": [
            {
                "id": row.get("id"),
                "type": row.get("type"),
                "url": row.get("url"),
                "title": row.get("title"),
            }
            for row in pages
            if isinstance(row, dict)
        ],
    }


def main():
    if os.name != "nt":
        print("SKIP: full Tekzite dialog smoke is Windows-only")
        return 0

    temp_root = Path(tempfile.mkdtemp(prefix="tekzite-full-dialog-smoke-"))
    page = temp_root / "dialog-smoke.html"
    page.write_text(
        "<!doctype html><meta charset='utf-8'><title>Tekzite Dialog Smoke</title>"
        "<h1>Tekzite dialog smoke</h1><button id='b'>button</button>",
        encoding="utf-8",
    )
    page_url = page.resolve().as_uri()

    old_argv = list(sys.argv)
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tekzite-dialog-smoke")
    app = None
    state = {
        "started": time.monotonic(),
        "dialog_started_at": None,
        "armed": False,
        "arm_future": None,
        "clicked": False,
        "verify_future": None,
        "result": None,
        "error": None,
    }

    try:
        # Private mode gives this integration test a fresh Chromium profile and
        # avoids restore prompts or state from the runner account.
        sys.argv[:] = [str(ROOT / "main.py"), "--private", page_url]
        app = tekzite_main.BrowserApp()

        def fail(message):
            if state["error"] is None:
                state["error"] = str(message)
                print("FAIL:", message)
                print("DIAGNOSTICS:", json.dumps(_dialog_debug(app), default=str, sort_keys=True))
            try:
                app.root.after(20, app.root.quit)
            except Exception:
                pass

        def finish_success():
            state["result"] = True
            print("PASS: full Tekzite Browser displayed and answered its Tk-native confirm dialog")
            print("DIAGNOSTICS:", json.dumps(_dialog_debug(app), default=str, sort_keys=True))
            try:
                app.root.after(20, app.root.quit)
            except Exception:
                pass

        def tick():
            if state["error"] is not None or state["result"] is True:
                return
            if (state["dialog_started_at"] is not None
                    and time.monotonic() - state["dialog_started_at"] > 12.0):
                fail("Timed out waiting for Tekzite's Tk-native JavaScript dialog")
                return

            tab = app._active_tab() or {}
            target_id = str(tab.get("chromium_target_id") or "")
            session = net._CHROMIUM_SESSION

            if not state["armed"]:
                if not target_id or not session or not tab.get("loaded"):
                    app.root.after(50, tick)
                    return
                if state["arm_future"] is None:
                    def arm():
                        return net._persistent_page_cdp_call(
                            session,
                            "Runtime.evaluate",
                            {
                                "expression": """(() => {
                                  window.__tekziteFullDialogSmoke =
                                    confirm('TEKZITE FULL BROWSER DIALOG SMOKE');
                                  return window.__tekziteFullDialogSmoke;
                                })()""",
                                "returnByValue": True,
                            },
                            target_id=target_id,
                            timeout=20.0,
                            purpose="dialog-full-smoke",
                        )
                    state["arm_future"] = worker.submit(arm)
                    app._tekzite_smoke_arm_future = state["arm_future"]
                    state["dialog_started_at"] = time.monotonic()
                    state["armed"] = True
                    print("Synchronous confirm() started for target:", target_id)
                    app.root.after(40, tick)
                    return

            win = getattr(app, "_javascript_dialog_window", None)
            if win is not None:
                try:
                    exists = bool(win.winfo_exists())
                except Exception:
                    exists = False
                if exists and not state["clicked"]:
                    button = _find_button(win, "OK")
                    if button is None:
                        fail("Tekzite dialog window appeared but had no OK button")
                        return
                    print("Tk dialog appeared; invoking real OK button")
                    button.invoke()
                    state["clicked"] = True
                    app.root.after(80, tick)
                    return

            if state["clicked"]:
                if state["verify_future"] is None:
                    def verify():
                        try:
                            result = state["arm_future"].result(timeout=5.0)
                        except Exception as exc:
                            return {"error": f"{type(exc).__name__}: {exc}"}
                        return (((result or {}).get("result") or {}).get("value"))
                    state["verify_future"] = worker.submit(verify)
                    app.root.after(50, tick)
                    return
                if not state["verify_future"].done():
                    app.root.after(50, tick)
                    return
                try:
                    value = state["verify_future"].result()
                except Exception as exc:
                    fail(f"Could not verify dialog result: {type(exc).__name__}: {exc}")
                    return
                if value is not True:
                    fail(f"Page did not receive Tk OK result: {value!r}")
                    return
                finish_success()
                return

            app.root.after(50, tick)

        app.root.after(50, tick)
        app.root.mainloop()

        if state["error"] is not None:
            raise AssertionError(state["error"])
        if state["result"] is not True:
            raise AssertionError("Full Tekzite dialog smoke exited without success")
        return 0
    finally:
        sys.argv[:] = old_argv
        worker.shutdown(wait=False, cancel_futures=True)
        if app is not None:
            try:
                app._closing = True
            except Exception:
                pass
            try:
                net.close_embedded_chromium(clear_profile=False)
            except Exception:
                pass
            try:
                app.root.destroy()
            except Exception:
                pass
            for profile in (
                getattr(app, "_private_profile_dir", None),
                getattr(app, "_privacy_profile_dir", None),
            ):
                if profile:
                    shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
