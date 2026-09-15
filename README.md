# Tekzite Browser

Tekzite Browser is an experimental Windows desktop browser shell built in Python/Tk around a real Chromium renderer. Tekzite keeps its own tabs, omnibox, menus, preferences and interaction layer while Chromium handles web standards, JavaScript, media, cookies, canvas, WebGL and page rendering.

> **Current release:** v8.2 GitHub-ready source tree  
> **Platform:** Windows 10/11  
> **Status:** experimental, actively developed

## Highlights

- Chromium-only web rendering with a dedicated Tekzite profile.
- Native DWM presentation instead of screenshot polling.
- Real Chromium page zoom with a local Manifest V3 zoom bridge.
- Zoom-aware mouse input, cursor feedback and text selection.
- Fast native tab switching, favicons, live titles and loading state.
- Find in Page, restore closed tab, middle-click close and common browser shortcuts.
- Built-in conservative host-based ad blocker.
- Loopback-only HTTP/HTTPS CONNECT network helper; HTTPS stays end-to-end encrypted.
- Microsoft web pages allowed while a narrow browser/vendor telemetry blocklist remains active.
- OLED-friendly custom Tekzite chrome with lightweight UI animations.

## Requirements

- Windows 10 or Windows 11.
- Python 3.10 or newer. Python 3.12+ is recommended.
- Pillow (`pip install -r requirements.txt`).
- A Chromium-family executable. Tekzite looks for, in order:
  1. `./chromium.exe`
  2. `./chromium/chrome.exe`
  3. `./ungoogled-chromium/chrome.exe`
  4. installed Chromium
  5. installed Google Chrome
  6. a non-WindowsApps `chromium.exe` / `chrome.exe` on `PATH`

Tekzite intentionally does not silently switch to Microsoft Edge.

## Quick start

```powershell
# Clone the repository
git clone https://github.com/YOUR-ACCOUNT/tekzite-browser.git
cd tekzite-browser

# Create an isolated environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install runtime dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Optional: verify the local setup
python tools\doctor.py

# Start Tekzite
python main.py
```

You can also use `run.bat` or `run.ps1` after creating the virtual environment.

## Development setup

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m py_compile main.py engine\net.py tekzite_network.py
python -m pytest
```

The CI workflow runs these checks on Windows with supported Python versions.

## Architecture

Tekzite is not a custom HTML engine. The current stack is:

```text
Tekzite Tk shell
    │
    ├── tabs / omnibox / menus / preferences / shortcuts
    ├── CDP input + browser control
    ├── DWM thumbnail presentation
    │       └── off-screen Chromium source window
    └── loopback Tekzite Network helper
            └── end-to-end HTTPS CONNECT tunnels
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [NETWORK_ENGINE.md](NETWORK_ENGINE.md) for more detail.

## Privacy and profiles

Tekzite launches Chromium with its own profile under:

```text
%LOCALAPPDATA%\Tekzite Browser\Chromium Bridge Profile
```

It does not intentionally reuse your normal Chrome/Chromium profile. The network helper binds to loopback and tunnels HTTPS without decrypting page contents.

The built-in ad blocker is deliberately conservative and can be disabled in Preferences. The telemetry blocklist is separate from ad blocking.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+L` | Focus address bar |
| `Ctrl+T` | New tab |
| `Ctrl+W` | Close current tab |
| `Ctrl+Shift+T` | Reopen closed tab |
| `Ctrl+F` | Find in Page |
| `Ctrl+Tab` | Next tab |
| `Ctrl+Shift+Tab` | Previous tab |
| `Ctrl+1` ... `Ctrl+9` | Select tab |
| `Alt+Left` / `Alt+Right` | Back / forward |

## Repository layout

```text
main.py                     Tekzite UI and browser shell
engine/net.py               Chromium, CDP, DWM and browser integration
tekzite_network.py          Loopback proxy, telemetry policy and ad blocking
chromium_zoom_extension/    Local native Chromium zoom bridge
tests/current/              Tests for the current architecture
tests/legacy/               Historical version-specific regression tests
tools/doctor.py             Local environment diagnostics
docs/                       Architecture and release documentation
```

## Building the optional network helper executable

Tekzite can run the network helper from Python during development. To build the standalone Windows helper:

```powershell
python -m pip install -r requirements-build.txt
.\build_network_exe.bat
```

The generated `tekzite-network.exe` is intentionally ignored by Git.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Please include a short reproduction for behavioral bugs and run the current test suite before submitting changes.

## Security

Please do not publish sensitive security reports as ordinary issues. See [SECURITY.md](SECURITY.md).

## License

No open-source license has been selected for Tekzite Browser yet. The repository therefore currently ships with an all-rights-reserved notice in [LICENSE](LICENSE). Choose an explicit open-source license before accepting redistributable outside contributions.

## Release history

See [CHANGELOG.md](CHANGELOG.md).
