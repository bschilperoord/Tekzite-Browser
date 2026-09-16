# Tekzite Browser

Tekzite Browser is an experimental Windows desktop browser shell built in Python/Tk around a real Chromium renderer. Tekzite keeps its own tabs, omnibox, menus, preferences and interaction layer while Chromium handles web standards, JavaScript, media, cookies, canvas, WebGL and page rendering.

> **Current release:** v10.5.0 Windows source tree  
> **Platform:** Windows 10/11  
> **Status:** experimental, actively developed

## Highlights

- Chromium-only web rendering with a dedicated Tekzite profile.
- Native DWM presentation instead of screenshot polling.
- Real Chromium page zoom with a local Manifest V3 zoom bridge.
- Zoom-aware mouse input, cursor feedback and text selection.
- Fast native tab switching, favicons, live titles and loading state.
- Find in Page, restore closed tab, middle-click close and common browser shortcuts.
- **Privacy Lockdown enabled by default:** temporary Chromium profile, no persistent history/session, and user extensions disabled while locked down.
- Built-in ad + tracker blocking with per-site ad exceptions and aggregate privacy counters.
- Tracking-parameter removal, HTTPS-first navigation, referrer stripping, GPC + DNT, third-party-cookie blocking and default-deny sensitive permissions.
- QUIC, built-in DoH, non-proxied WebRTC UDP, prediction/prefetch, sync, crash reporting and Chromium vendor background telemetry paths are disabled.
- Loopback-only HTTP/HTTPS CONNECT network helper; HTTPS stays end-to-end encrypted.
- Normal Microsoft web pages remain allowed while known browser/vendor telemetry endpoints are blocked.
- OLED-friendly custom Tekzite chrome with lightweight UI animations.
- Private windows with process-isolated temporary Chromium profiles.
- Site Info & Privacy panel with origin-scoped storage clearing.
- Unpacked Chromium Extension Manager with enable/disable and permission inspection.

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

**Privacy Lockdown is enabled by default.** In that mode Chromium receives a fresh process-temporary profile instead of Tekzite's persistent Chromium profile. Cookies, cache, IndexedDB, service-worker state and Chromium history live only in that temporary tree and are deleted on normal shutdown. Tekzite's own browsing history and open-tab session are not written to disk. Bookmarks and files you explicitly download remain persistent because they are user-created data.

Tekzite's Privacy Core also:

- routes Chromium HTTP/HTTPS through the loopback Tekzite Network helper while keeping HTTPS CONNECT end-to-end encrypted;
- blocks known browser/vendor telemetry, ad hosts and dedicated analytics/tracker hosts before an upstream connection is opened;
- strips known marketing/click query parameters without removing unknown functional parameters;
- sends `DNT: 1` and `Sec-GPC: 1`, exposes Global Privacy Control to page JavaScript, and strips Referer/client-metadata headers where supported;
- blocks third-party cookies and disables password saving, cloud autofill, search suggestions, DNS prefetch, network prediction and Privacy Sandbox advertising APIs;
- disables Chromium's built-in DoH, QUIC and non-proxied WebRTC UDP so Tekzite does not silently choose its own public DNS resolver or a UDP path around the local proxy;
- defaults camera, microphone, location, notifications, sensors and several device APIs to deny;
- disables user-installed unpacked extensions while Privacy Lockdown is active, because an extension with broad host permissions can otherwise widen the privacy boundary;
- uses Startpage as the default omnibox search provider.

Use **Tools → Privacy Shield** for the live audit. It shows enabled protections plus aggregate counters for blocked telemetry, trackers, ads, HTTPS upgrades and tracking parameters. These counters do **not** store destination hosts. **Tools → Local Ports & Loopback** separately explains the required localhost services and recent denied Python loopback attempts.

Tekzite's process-local Python egress guard allows Python to connect on loopback only to the dynamically registered Tekzite Network proxy and Chromium DevTools/CDP ports. This is an application-level guard, not a Windows firewall rule.

### Important privacy boundary

Tekzite minimizes what the browser itself leaks, stores and sends in the background, but it does not claim network anonymity. A website you intentionally visit can still observe the public IP address of your network unless you add an upstream privacy layer such as a VPN, proxy or Tor. Tekzite also does not decrypt HTTPS traffic to inspect page contents.

When Privacy Lockdown is disabled, named Tekzite profiles can use the normal persistent Chromium profile under `%LOCALAPPDATA%\Tekzite Browser` and user extensions can be enabled through the Extension Manager.

## Customizing Tekzite

Open **View → Customize Tekzite…** or press `Ctrl+Shift+,`. Customization is saved per Tekzite profile. Appearance presets can be previewed live, exported as JSON and imported into another profile. Hiding the toolbar or address item never locks you out: `Ctrl+L` temporarily reveals the address bar, and `Ctrl+Shift+Alt+R` restores Tekzite's default interface without clearing browser data.

Tekzite customization applies to Tekzite-owned browser chrome. Website HTML/CSS remains Chromium-owned and is not rewritten by the theme system.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+L` | Focus/reveal address bar |
| `Ctrl+T` | New tab |
| `Ctrl+Shift+N` | New Private Window |
| `Ctrl+W` | Close current tab |
| `Ctrl+Shift+T` | Reopen closed tab |
| `Ctrl+F` | Find in Page |
| `Ctrl+Tab` | Next tab |
| `Ctrl+Shift+Tab` | Previous tab |
| `Ctrl+1` ... `Ctrl+9` | Select tab |
| `Alt+Left` / `Alt+Right` | Back / forward |
| `Ctrl+,` | Browser settings |
| `Ctrl+Shift+,` | Customize Tekzite |
| `Ctrl+Shift+Alt+R` | Reset interface customization only |

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

## Bookmarks and restart tabs

Use Ctrl+D to save the current page. Bookmarks → Manage Bookmarks (Ctrl+Shift+O) opens, renames or removes saved pages.

Open tabs, pins and the selected tab are saved periodically and when you close Tekzite normally, then restored at the next launch. Background tabs load when selected. This restores page addresses, not unsaved forms or back/forward history. Preferences includes a restore-tabs switch; disabling it removes the saved session on normal exit. With multiple windows, the last window closed supplies the next session.

Bookmarks and session addresses are stored locally alongside preferences, separately from the Chromium profile. Clearing Chromium browsing data on exit still clears cookies/profile data; saved bookmarks and enabled session restoration remain available.

Build on Windows with `powershell -ExecutionPolicy Bypass -File .\build_windows.ps1`, or run `python main.py` after installing requirements.


## New in v10.5.0

### Luxe UI

- Soft tabs are now genuinely rounded Canvas-rendered surfaces rather than square Tk frames.
- Traffic-light window controls can be used in macOS-style left-side placement; classic Tekzite controls remain selectable.
- Added Aurora Glass and OLED Neon visual presets.
- Window-control style and tab style are live, per-profile customization options.
- Browser chrome uses richer layered surfaces, refined spacing and focus borders without risky full-window transparency.

## New in v10.3.3

### DWM performance hardening

- Added a steady-state DWM thumbnail resize fast path that reuses the established source/crop contract.
- Removed synchronous compositor flushes from ordinary interactive resizes; cold registration/recovery still retains the safe full path.
- Rate-limited Chromium presenter parking and made late-presenter cleanup single-flight.
- Pure top-level moves use `SWP_NOSIZE` for the DWM destination when dimensions are unchanged.
- Window dragging batches the Tekzite root and DWM destination with `BeginDeferWindowPos` / `EndDeferWindowPos`.
- Duplicate drag coordinates and duplicate DWM viewport sizes are skipped.
- Navigation-settle callbacks can explicitly force a full crop re-measure so the fast path never trades correctness for speed.
- DWM diagnostics expose fast/full resize counters and the last resize path.

## New in v10.3.0

- Added a full per-profile Customize Tekzite center with live preview.
- Added four built-in color presets plus editable colors for every Tekzite chrome role.
- Added custom UI/display fonts, font sizing, density, UI scaling and animation control.
- Toolbar controls can be reordered, hidden and switched between icon, text or combined labels.
- App bar, branding, menu bar, window controls, tab strip, tab details, scrollbar and status indicators can be independently shown or hidden.
- Tabs can sit above or below the toolbar, and the new-tab button can move left or right.
- Chrome bar heights, initial/minimum window dimensions and start-maximized behavior are configurable.
- Search URL template is user-configurable through `{query}` and the existing homepage/startup/new-tab/zoom settings are exposed in the customization center.
- Customization presets can be imported/exported as JSON and a safe Ctrl+Shift+Alt+R reset restores only the interface.

## New in v10.2.1

- Added conventional desktop-browser navigation controls: Back, Forward, Reload/Stop and Home.
- Added a live bookmark star inside the address bar that toggles add/remove state.
- Added dedicated Downloads and three-dot main-menu buttons to the primary toolbar.
- Reload changes to Stop while the active Chromium page is loading, backed by CDP `Page.stopLoading`.
- Removed developer/debug actions from the primary browsing toolbar; they remain available under Tools.

## New in v10.2.0

| Feature | Where to find it |
| --- | --- |
| Sleeping tabs | Settings → Startup and tabs |
| Tab groups | Right-click a tab → Move to Group, or Tools → Tab Groups |
| Per-site permissions | Tools → Permissions Manager |
| Downloads 2.0 | Tools → Downloads, Ctrl+J |
| Isolated profiles | Tools → Profiles |
| Task Manager | Tools → Task Manager |
| Diagnostics | Tools → Diagnostics |
| GitHub update checker | Tools → Check for Updates |

Sleeping tabs release the Chromium page target after the configured inactivity period, then recreate and reload the page when selected. Active, pinned and currently-audible media tabs are excluded. Because sleeping releases the renderer target, unsaved form state inside a sleeping page may be lost; use a longer timeout or pin a tab when that matters.

Tab groups are saved with the browser session. Groups can be created from a tab context menu, collapsed from the tab strip or managed from Tools → Tab Groups.

Permissions Manager stores explicit per-origin Allow, Block or Ask rules for notifications, location, microphone, camera, clipboard and sensors. Tekzite keeps its privacy-first Block defaults when no site override exists.

Downloads now support pause, resume, cancel, retry, open file, open containing folder and remove-from-list. Settings can also request Chromium's save-location prompt on new downloads after restart.

Profiles isolate Tekzite preferences/history/session/bookmarks and Chromium cookies/cache/storage. The historical Default profile keeps the existing storage location, so upgrading does not strand current data.

Task Manager shows open Tekzite tabs with renderer task-time and JavaScript-heap metrics when available, alongside Chromium process PID/CPU metadata and Windows working-set memory. Diagnostics summarizes profile, tabs, Chromium/network state and the tail of the local stability log.

Update Checker uses a GitHub repository configured in Settings (`owner/repository`). It compares the latest release tag with the installed version, can download a Windows release asset, computes SHA-256 locally and verifies it when GitHub publishes a `sha256:` asset digest. It never silently installs an update.

Crash recovery now asks before restoring a session whose last checkpoint was marked as an unclean exit.

## New in v10.1.0

| Feature | Where to find it |
| --- | --- |
| Private Window with temporary Chromium profile | File → New Private Window, Ctrl+Shift+N |
| Site security/privacy overview | ◈ button in the address bar, or Tools → Site Info & Privacy |
| Clear current-origin cookies/storage/cache | Site Info & Privacy → Clear site data |
| Unpacked Chromium extensions | Tools → Extension Manager |

Private windows launch in their own Tekzite process and receive a unique temporary Chromium user-data directory. They do not restore the normal saved session, do not write Tekzite browsing history or session checkpoints, and always delete their Chromium profile when closed. Preferences and bookmarks remain shared so the private window still feels like Tekzite rather than a blank second application. Downloads remain ordinary files on disk.

Site Info reads live Chromium state over CDP. It reports the current URL/origin, HTTPS security state where available, cookie count without exposing cookie values, local/session-storage entry counts, Chromium origin usage/quota, ad-block status and Tekzite privacy defaults. Clear site data calls Chromium's origin-scoped storage clearing API rather than clearing every site's cookies.

Extension Manager loads unpacked Chromium extensions from user-selected folders. Tekzite validates `manifest.json`, shows declared permissions, allows enable/disable/remove operations, and keeps the built-in Tekzite Local Browser Services extension permanently enabled. Extension-set changes are applied on restart because Chromium receives extension directories on its startup command line.

## New in v10.0

| Feature | Where to find it |
| --- | --- |
| Downloads: progress, cancel, retry/resume, open folder | Tools → Downloads, Ctrl+J |
| Search history by page name or address | History → Search History, Ctrl+H |
| Per-site ad blocking | Tools → Enable/Disable Ad Blocking for the current hostname |
| Pinned tabs | Right-click a tab → Pin Tab / Unpin Tab |
| Quiet mode | View → Toggle Quiet Mode, or Preferences |
| Crash recovery | Automatic while Restore open tabs is enabled |

Pinned tabs move left, use compact labels, and survive Close Other Tabs / Close Tabs to the Right. Explicit close (Ctrl+W or the context menu) still closes a pin.

Quiet mode hides the debug buttons and status bar and reduces animations. Navigation and menus remain accessible.

Recovery writes an atomic snapshot every two seconds when state changes. A crash may lose changes since the last successful snapshot. Addresses, order, pins and selection are recovered; form text, scroll position and back/forward history are not. Disabling restoration removes the saved session at the next checkpoint or normal exit. With multiple windows, the latest checkpoint/last closed window wins.

History stores up to 5,000 distinct page addresses with their latest visit and title, locally. Clear History removes it immediately; the existing Clear browsing data on exit preference also clears it on normal exit. Bookmarks and enabled session snapshots are separate.

Site exceptions cover a hostname and its subdomains, including embedded requests under that site's main frame. The current page reloads after toggling; reload other already-open matching pages to apply their new policy. Telemetry blocking is independent. Enabling blocking removes any matching parent-host exception, which also re-enables blocking on its other subdomains.

Downloads use Chromium's own download engine and protection checks. Retry resumes where possible; otherwise it requests the file again. Expiring links, POST downloads and blob downloads may require revisiting the source page. The panel shows the latest 200 items in the Chromium profile; clearing that profile clears its download list but does not delete downloaded files. Closing the browser stops active downloads.

Implementation references: [Chromium Downloads API](https://developer.chrome.com/docs/extensions/reference/api/downloads) and [Chromium declarativeNetRequest API](https://developer.chrome.com/docs/extensions/reference/api/declarativeNetRequest).

## v10.0.1 startup hotfix

Fixes the fatal “The local browser service did not become ready” startup path. DevTools wakes the worker before testing readiness and installs the bundled entry point when it is absent. Optional-service failure no longer terminates the Chromium launch. The proxy retains ad filtering until the extension confirms its rules; telemetry filtering remains independent.

Extract this release into a fresh folder and run build_windows.ps1. Rebuild both executables using that script: the proxy helper now accepts a live fallback-policy file. Do not reuse the v10.0 helper executable.

Protocol reference: [Chrome DevTools Runtime](https://chromedevtools.github.io/devtools-protocol/tot/Runtime/).

## v10.0.2 native startup repair

Restores direct startup at the requested page instead of forcing about:blank first. Optional browser services start asynchronously after successful presentation, keeping service initialization out of native window selection. If Chromium is replacing its render host during attachment, validation can retry up to three times after the first check; an invalid owner is never embedded. Retries run on the navigation worker, not the UI thread.

The proxy fallback stays active until extension configuration succeeds. Reload an initially opened exempt site after services initialize to apply its exception to requests blocked during startup. New services remain available after startup; no feature is removed.

Extract into a fresh folder and rebuild with build_windows.ps1. Windows rendering must still be checked on the target PC.
