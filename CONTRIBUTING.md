# Contributing to Tekzite Browser

Thanks for helping improve Tekzite Browser.

## Before you start

Tekzite's supported runtime is Windows. The web renderer is Chromium, presented through Windows DWM, while browser input/control uses CDP. Changes that work only in a screenshot/software-rendering path are not substitutes for the native path.

## Development setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
python tools\doctor.py
```

Run the browser with:

```powershell
python main.py
```

## Before opening a pull request

Run:

```powershell
python -m py_compile main.py engine\net.py tekzite_network.py
python -m pytest
```

Please keep pull requests focused. For browser-behavior changes, include:

- what was wrong;
- how to reproduce it;
- what changed;
- which pages were tested;
- whether native zoom, DWM, tab switching, text selection or the network helper are affected.

## Architecture rules

- Chromium is the only web engine.
- DWM/native presentation is the primary presentation path on Windows.
- Do not reintroduce automatic software-rendering fallback.
- Do not touch the user's normal Chromium/Chrome profile.
- Keep the Tekzite Chromium profile isolated under `%LOCALAPPDATA%\Tekzite Browser`.
- HTTPS CONNECT traffic must remain end-to-end unless the project explicitly adopts a different security model.
- Avoid site-specific DOM hacks when a Chromium/browser-level solution exists.

## Tests

`tests/current/` is the CI suite for the current architecture. `tests/legacy/` preserves historical implementation-specific tests and is not collected by default.

New behavior should normally get a current-release regression test.
