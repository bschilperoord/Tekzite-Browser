from pathlib import Path

def replace_once(path, old, new, label):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match in {path}, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")

replace_once(
    "engine/net.py",
    '''    seen = set()

    if os.name == "nt":''',
    '''    seen = set()

    # Linux preview/CI can pin an exact Chromium-family executable without
    # changing the normal desktop discovery order. This is also useful on
    # distributions where `chromium` is a sandboxed launcher wrapper rather
    # than the real browser binary.
    override = str(os.environ.get("TEKZITE_CHROMIUM") or "").strip()
    if override:
        candidate = shutil.which(override) if os.path.basename(override) == override else os.path.expanduser(override)
        if candidate and os.path.isfile(candidate):
            key = os.path.normcase(os.path.realpath(candidate))
            seen.add(key)
            yield candidate

    if os.name == "nt":''',
    "Chromium executable override",
)

replace_once(
    "tools/linux_smoke.py",
    '''    state = Path(tempfile.mkdtemp(prefix="tekzite-linux-smoke-state-"))
    os.environ["XDG_STATE_HOME"] = str(state)''',
    '''    # Hosted Linux runners can expose a distro Chromium wrapper alongside a
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
    os.environ["XDG_STATE_HOME"] = str(state)''',
    "smoke Chromium selection",
)

replace_once(
    "tools/linux_smoke.py",
    '''        if time.monotonic() >= deadline:
            fail(f"Chromium target did not become ready: {app.status_var.get()}")
            return''',
    '''        if time.monotonic() >= deadline:
            result["chromium"] = os.environ.get("TEKZITE_CHROMIUM", "")
            debug = dict(getattr(net, "_CHROMIUM_LAUNCH_DEBUG", {}) or {})
            for key in ("errors", "last_error", "executable", "attempts", "port",
                        "devtools_ready_ms", "process_spawn_ms", "linux_root_no_sandbox"):
                if key in debug:
                    result[f"launch_{key}"] = debug.get(key)
            fail(f"Chromium target did not become ready: {app.status_var.get()}")
            return''',
    "smoke startup diagnostics",
)

replace_once(
    "tools/linux_smoke.py",
    'app.root.after(50, wait_for_target, time.monotonic() + 8.0)',
    'app.root.after(50, wait_for_target, time.monotonic() + 18.0)',
    "smoke target timeout",
)

replace_once(
    "tools/linux_smoke.py",
    'app.root.after(15000, lambda: fail("overall smoke timeout"))',
    'app.root.after(35000, lambda: fail("overall smoke timeout"))',
    "smoke overall timeout",
)

print("Linux runtime follow-up transformations applied and smoke backend pinned")
