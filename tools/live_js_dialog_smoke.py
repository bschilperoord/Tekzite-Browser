#!/usr/bin/env python3
"""Live Windows smoke test for Tekzite's Chromium JavaScript-dialog bridge.

This intentionally launches a real, non-headless Chromium-family browser so a
JavaScript confirm() has a browser UI handler. It then exercises the exact
production helpers in engine.net.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import net


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _browser_candidates():
    env = os.environ.get("TEKZITE_DIALOG_SMOKE_BROWSER", "").strip()
    if env:
        yield Path(env)
    for name in ("msedge.exe", "chrome.exe", "chromium.exe"):
        found = shutil.which(name)
        if found:
            yield Path(found)
    roots = [
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    rels = [
        Path("Microsoft/Edge/Application/msedge.exe"),
        Path("Google/Chrome/Application/chrome.exe"),
        Path("Chromium/Application/chrome.exe"),
    ]
    for root in roots:
        if not root:
            continue
        for rel in rels:
            yield Path(root) / rel


def _find_browser():
    seen = set()
    for candidate in _browser_candidates():
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file():
            return resolved
    raise RuntimeError("No installed Edge/Chrome/Chromium executable found")


def _wait_devtools(port, process, timeout=12.0):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Browser exited before DevTools was ready: {process.returncode}")
        try:
            version = net._devtools_json(port, "/json/version", timeout=0.4)
            pages = net._devtools_json(port, "/json/list", timeout=0.4)
            page = next(
                (
                    row for row in pages
                    if row.get("type") == "page" and row.get("webSocketDebuggerUrl")
                ),
                None,
            )
            if version.get("webSocketDebuggerUrl") and page:
                return version, page
        except Exception as exc:
            last_error = exc
        time.sleep(0.05)
    raise RuntimeError(f"Timed out waiting for browser DevTools: {last_error}")


def _evaluate(session, target_id, expression, timeout=2.0):
    return net._persistent_page_cdp_call(
        session,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": False},
        target_id=target_id,
        timeout=timeout,
        purpose="dialog-smoke-control",
    )


def main():
    if os.name != "nt":
        print("SKIP: live JavaScript-dialog smoke is Windows-only")
        return 0

    browser = _find_browser()
    port = _free_port()
    profile = Path(tempfile.mkdtemp(prefix="tekzite-dialog-smoke-"))
    command = [
        str(browser),
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--disable-extensions",
        "--disable-features=Translate",
        "--window-position=-32000,-32000",
        "--window-size=900,700",
        "--app=about:blank",
    ]
    print("Browser:", browser)
    print("DevTools port:", port)

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    old_session = net._CHROMIUM_SESSION
    session = None
    try:
        version, page = _wait_devtools(port, process)
        target_id = str(page.get("id") or "")
        if not target_id:
            raise RuntimeError("Live browser exposed no page target id")

        session = {
            "port": port,
            "browser_ws_url": str(version.get("webSocketDebuggerUrl") or ""),
            "target_id": target_id,
            "active_target_id": target_id,
            "page_cdp_channels": {},
        }
        net._CHROMIUM_SESSION = session

        # Full Tekzite already has independent page CDP sessions with Page
        # enabled for presentation/state work. Reproduce that condition here;
        # the dialog observer must still receive the browser-owned event.
        net._persistent_page_cdp_call(
            session,
            "Page.enable",
            {},
            target_id=target_id,
            timeout=2.0,
            purpose="dialog-smoke-competing-page",
        )
        competing = (session.get("page_cdp_channels") or {}).get(
            f"{target_id}:dialog-smoke-competing-page"
        ) or {}
        competing.setdefault("enabled_domains", set()).add("Page")
        print("Competing Page-enabled session:", bool(competing.get("ws")))

        armed = net.ensure_embedded_chromium_javascript_dialog_monitor(
            target_id, timeout=2.0
        )
        if not armed:
            raise AssertionError("Tekzite dialog monitor did not arm")
        channel = (session.get("javascript_dialog_browser_channels") or {}).get(target_id) or {}
        print("Attached dialog session:", channel.get("session_id"))
        if not channel.get("session_id"):
            raise AssertionError("No flattened Target session was attached")

        # Return from Runtime.evaluate before confirm() opens so this command
        # cannot itself block waiting for the synchronous page dialog.
        result = _evaluate(
            session,
            target_id,
            """(() => {
              window.__tekziteDialogSmokeResult = 'pending';
              setTimeout(() => {
                window.__tekziteDialogSmokeResult =
                  confirm('TEKZITE LIVE DIALOG SMOKE');
              }, 250);
              return 'armed';
            })()""",
        )
        value = (((result or {}).get("result") or {}).get("value"))
        if value != "armed":
            raise AssertionError(f"Could not arm confirm() trigger: {value!r}")

        event = None
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and event is None:
            rows = net.poll_embedded_chromium_javascript_dialogs(
                target_id, timeout=0.20
            )
            if rows:
                event = rows[0]
                break
            time.sleep(0.03)

        if event is None:
            debug = {
                "channel_keys": sorted(channel.keys()),
                "dialog_open": channel.get("dialog_open"),
                "events": channel.get("events"),
                "closed": channel.get("closed"),
                "calls": channel.get("calls"),
            }
            raise AssertionError(
                "No Page.javascriptDialogOpening event reached Tekzite. "
                + json.dumps(debug, default=str)
            )

        print("Dialog event:", json.dumps(event, sort_keys=True))
        if event.get("type") != "confirm":
            raise AssertionError(f"Expected confirm event, got {event!r}")
        if "TEKZITE LIVE DIALOG SMOKE" not in str(event.get("message") or ""):
            raise AssertionError(f"Wrong dialog message: {event!r}")
        print("hasBrowserHandler:", event.get("has_browser_handler"))

        if not net.resolve_embedded_chromium_javascript_dialog(
            target_id, True, timeout=2.0
        ):
            raise AssertionError("Tekzite could not accept the live confirm dialog")

        deadline = time.monotonic() + 5.0
        js_value = None
        while time.monotonic() < deadline:
            result = _evaluate(
                session, target_id, "window.__tekziteDialogSmokeResult", timeout=1.0
            )
            js_value = (((result or {}).get("result") or {}).get("value"))
            if js_value is True:
                break
            time.sleep(0.05)
        if js_value is not True:
            raise AssertionError(
                f"confirm() did not receive Tekzite's accepted result: {js_value!r}"
            )

        print("PASS: live browser confirm() was intercepted and answered by Tekzite")
        return 0
    finally:
        try:
            if session is not None:
                net._close_javascript_dialog_browser_channels(session)
                net._close_persistent_page_cdp_channels(session)
        except Exception:
            pass
        net._CHROMIUM_SESSION = old_session
        try:
            process.terminate()
            process.wait(timeout=4)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
