# Tekzite Browser

Tekzite Browser is an experimental Windows desktop browser shell built in Python/Tk around a real Chromium renderer. Tekzite keeps its own tabs, omnibox, menus, preferences and interaction layer while Chromium handles web standards, JavaScript, media, cookies, canvas, WebGL and page rendering.

> **Current release:** v10.5.80 UltraSpeed for Windows  

## Connection Forensics: see why a connection exists

Tekzite's **Tools -> Network Connections** is more than a list of IP addresses. It correlates the Windows socket owner, Tekzite Network proxy state, Chromium request metadata and JavaScript initiator evidence so you can follow a live causal chain:

**process -> socket -> proxy -> hostname -> request -> JavaScript caller -> response**

For attributed traffic, Tekzite can show the process/PID, TCP or UDP endpoint, exact proxy-requested hostname, request purpose/resource type, page/worker/extension context, sanitized JavaScript caller and async stack, connection-reuse evidence, response status/MIME/bytes, cache or service-worker delivery, redirect lineage, TLS metadata and recent short-lived TCP/UDP activity. Double-click a row to inspect the evidence, or use **Show script source** to view a bounded excerpt around the exact caller. Minified one-line bundles can be locally pretty-printed and inline source maps can be decoded without generating another network request.

The feature is designed as a **causal audit, not a packet sniffer**. The live ledger is bounded and RAM-only while the monitor is open. It does not retain packet payloads, full URLs, query strings, header values, cookies, request/response bodies or complete script source. Unknown traffic stays **Unattributed** rather than being automatically called telemetry, and HTTP/2 reuse is explicitly separated from evidence that a script actually opened a socket.

### Minimal, explicit favicon networking (v10.5.80)

Tekzite no longer injects a page-context `fetch(..., credentials:'include')` call to retrieve tab favicons. Chromium is asked only for the icon URL. Tekzite then performs a small browser-owned GET through **Tekzite Network**, without page/session cookies, Authorization, Origin or Referer headers. Response cookies are ignored. This removes the confusing case where Tekzite's own favicon helper appeared in CDP as anonymous website JavaScript.

The favicon path is deliberately narrow: only `http`, `https` and bounded `data:` icons are accepted, transfer is capped at 512 KiB, and explicit loopback/private/link-local or conventional local-name targets are rejected before any request is made. Redirects into local address space are rejected as well. The Live Socket View keeps only a short-lived hostname-level marker for this browser-owned request so a matching upstream can be labeled **Tekzite favicon fetch / Tekzite Browser internal** rather than **Unattributed** or page script traffic.

### Deep JavaScript caller inspector (v10.5.78)

**Show script source** in Live Socket View Details is now a deeper JavaScript inspector. One-line/minified bundles are locally pretty-printed around the captured CDP caller coordinate, Tekzite isolates the best-effort containing function, and it scans code-only regions for direct browser network primitives such as `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `navigator.sendBeacon` and `WebTransport`. Strings, comments and regular-expression literals are masked during this scan so text that merely contains `fetch(` is not presented as causal code.

The inspector is source-map aware without contaminating the network audit. `Debugger.scriptParsed` metadata is captured on the temporary source-inspection channel. Inline Source Map v3 data can be decoded locally to show the mapped original filename/name/line and a bounded `sourcesContent` excerpt when present. External source maps are reported by sanitized hostname/final filename but are **not fetched automatically**, because generating a new network request while investigating another request would muddy the evidence. The complete generated script and inline map exist only during the explicit inspection operation; only bounded excerpts are displayed and nothing is added to the persistent/request ledger or written to disk.

### Causal request timeline + response evidence (v10.5.77)

The Live Socket View now includes a **Request timeline** that preserves a short RAM-only causal history while the monitor is open. It combines Chromium request metadata with the existing socket evidence: destination relation, method/resource type, initiator and sanitized script call chain, response status/MIME, encoded bytes, cache/service-worker delivery, redirects, failures, TLS protocol/cipher/issuer and connection-reuse state. This makes it possible to follow **page/worker → script → request → socket/connection → response** without packet payload capture.

Tekzite also records presence-only privacy hints for request/response headers Chromium exposes to the Network event stream: Cookie, Authorization, Origin, Referer and Set-Cookie. Header values are discarded immediately and never enter the audit ledger. A missing hint is not proof that Chromium sent no such header. Async stack descriptions such as timer/Promise boundaries are preserved when CDP supplies them, while full URLs, query strings, headers, bodies, cookies and complete script source remain outside the retained timeline.

### On-demand connection caller source (v10.5.76)

The Live Socket View can now go one step beyond filename/function attribution. Double-click an attributed connection, open **Details**, and choose **Show script source** to ask the live Chromium target for a small source excerpt around the exact caller line and column. The triggering line is marked and long/minified bundles are clipped around the call site so the source viewer remains responsive.

This is deliberately on-demand. The continuous network audit retains only sanitized caller metadata plus opaque target/script IDs. Tekzite opens a separate temporary DevTools channel for the source request, reduces Chromium's returned source immediately to the bounded excerpt, and does not write the complete script source to disk or add it to the connection ledger. Parser/browser-generated requests without a JavaScript caller simply report that no source is available.

### Script-to-socket forensics + recent TCP ETW (v10.5.75)

**Tools -> Network Connections** now goes beyond host-level attribution. For Chromium requests that expose an initiator stack, Tekzite retains a sanitized JavaScript caller chain containing only origin hostname, final script filename, function name and 1-based line/column. The live table adds **Script caller** and **Match** columns, and double-click/Details opens the complete sanitized call chain. `fetch`, XHR, WebSocket, EventSource and beacon/ping traffic are identified separately where Chromium exposes that resource type. Full script URLs/paths, query strings, script contents, request headers, cookies and bodies are not retained.

Socket attribution is deliberately confidence-scored instead of pretending HTTP/2 multiplexing is simple. **Strong opener** requires an exact requested-host match, close socket-open timing and Chromium explicitly reporting `connectionReused = false`. **Likely opener** has exact-host/timing evidence without a reuse verdict; **Probable opener** uses endpoint/timing evidence when an exact hostname is unavailable; **Reused connection**, **Endpoint activity** and **Host activity** are shown when the request is related but must not be claimed as the socket creator.

The Kernel-Network ETW layer now also retains recent TCP connect/accept events for Tekzite-owned PIDs. A very short TCP flow that vanishes before the next 250 ms owner-table snapshot can therefore remain briefly as a **RECENT** row. Current sockets still come from the Windows owner tables; ETW is an ephemeral RAM-only supplement and captures no payloads.

### Live request purpose + initiator attribution (v10.5.74)

**Tools -> Network Connections** can now explain many live web upstreams instead of showing only a socket and hostname. While the Live Socket View is open, Tekzite opens dedicated read-only Chromium DevTools Network observers for exposed page/worker/extension targets and correlates recent `Network.requestWillBeSent` events with Tekzite Network's exact upstream hostname. New **Purpose**, **Resource**, and **Initiator** columns distinguish page navigation/parser/script/preload traffic, workers/service workers, exposed extension targets and other Chromium target classes.

The attribution ledger is bounded, short-lived and RAM-only. Tekzite retains destination hostname/port, target class, resource type and initiator type/hostname, but immediately discards full URLs, paths, query strings, headers, cookies and payloads. Attribution begins when the Live Socket View opens, so refreshing the page gives the most complete picture. An upstream marked **Unattributed** only means that no matching page/extension CDP event has been observed in the live window; it is not automatically labeled telemetry.

This release also fixes PyInstaller one-file `tekzite-network.exe` payload processes being mistaken for generic Tekzite children. The whole helper process tree is now recognized as **Tekzite Network**, so its public sockets are labeled **Tekzite Network upstream** and can receive the exact original requested hostname instead of falling back to PTR.

### UDP remote peers via live ETW (v10.5.73)

**Tools -> Network Connections** can now resolve the remote peer behind live UDP sockets instead of stopping at the local Windows owner-table endpoint. While the Live Socket View is open, Tekzite starts a RAM-only `Microsoft-Windows-Kernel-Network` ETW consumer for Tekzite/Chromium/helper PIDs and correlates UDP send/receive events with the owning socket. The dashboard shows the remote IP and port, one row per recent peer, TX/RX packet and byte counters, last-seen age, route classification and asynchronous hostname enrichment.

One UDP socket may talk to several destinations, so peers remain separate rows for a short rolling window rather than overwriting each other. The ETW monitor stores metadata only in process memory and stops when the Live Socket View closes; it does not capture packet payloads. If Windows refuses the ETW session, the UI reports the reason and falls back to the local UDP endpoint instead of inventing a remote peer. Current TCP sockets use the Windows owner-table snapshot; starting with v10.5.75, Kernel-Network ETW also retains recent TCP connect/accept events so very short-lived flows can remain visible as RECENT rows. UDP peer discovery remains event-driven after the monitor starts.

### Full live socket view (v10.5.72)

**Tools -> Network Connections** is now a process-level **Live Socket View**. Tekzite reads Windows' owner-PID TCP/UDP tables and shows every current socket owned by Tekzite itself, Chromium, Tekzite Network and their descendants: process role/name, PID, TCP/UDP + IPv4/IPv6, local endpoint, hostname, remote endpoint, TCP state and route classification. Public Chromium sockets that do not go through Tekzite Network are called out as **Direct external**.

For proxied web traffic, the network helper correlates its live upstream socket with the original requested hostname in RAM, so the table can show the real site/subdomain even when the remote IP belongs to a CDN. Other unresolved IPs can be enriched with optional background PTR lookup. No URL paths, headers, query strings or page contents are added to the monitor. Windows' UDP owner table itself exposes only local UDP endpoints. Starting with v10.5.73, Tekzite augments those UDP rows with live Kernel-Network ETW peer events. Current TCP state remains owner-table based; starting with v10.5.75, Kernel-Network ETW supplements it with a short-lived RECENT ledger for connect/accept events that disappear between snapshots.

### Live network connections overview (v10.5.71)

**Tools -> Network Connections** now shows the current Tekzite Network helper session as a live destination table: hostname, port, protocol, allowed/blocked result, connection count, active tunnels and last-seen age. The ledger lives only in the helper's RAM and is read through the existing loopback proxy port using a random per-launch token. Tekzite does not persist connection history for this feature and does not record URL paths, query strings, headers or page contents. HTTPS traffic remains opaque inside end-to-end CONNECT tunnels.

### Maximized DWM pointer alignment (v10.5.70)

Maximize/restore now re-establishes the DWM pointer transform from the actual visible thumbnail pixel contract instead of a possibly stale pre-maximize RenderWidgetHost measurement. Tekzite forces one real recrop before refreshing input metrics, then performs lightweight metric-only settle checks. This keeps text selection, links and controls under the physical cursor even when the viewport jumps to a much larger maximized size.

### Faster Google auth close + durable sign-out (v10.5.69)

A successful Google/YouTube handoff now closes the standalone Chromium window on the first confirmed live YouTube HWND/title return. The live auth monitor runs every 70 ms instead of 220 ms and no longer imposes the old extra 0.55-second settle delay on this authoritative signal. Cookie/history-only fallbacks remain deliberately conservative. Normal Tekzite exit now also gives Chromium a clean `Browser.close` window before fallback teardown, so newly written cookie changes such as a YouTube sign-out are flushed to the profile instead of being lost to an immediate forced process-tree kill.

### Native/DComp stall guard (v10.5.68)

Hot Native navigation now treats surface-reuse state as per-navigation instead of persistent session state. Tekzite clears stale cold-frame diagnostics before every hot handoff, skips the old fixed 220 ms screen probe while Chromium is swapping renderers, and spaces forced DWM recrops farther apart. Cold/new-target surface diagnostics now ignore flat frames while the page is still loading and require two post-load blank samples before declaring a real DComp stall.

### Continuous Chromium frame handoff (v10.5.67)

Refreshes and same-tab navigations now keep the existing healthy DWM page surface continuously visible while Chromium swaps to the new document. Tekzite no longer hides that surface and re-reveals it on a fixed timer, removing a race that could expose Chromium's black DirectComposition backing surface. Cold startup also gets one hidden full-recrop/readiness retry before the first Chromium frame is revealed.

### Live auth-window completion (v10.5.66)

Google/YouTube sign-in completion now follows the visible standalone Chromium window itself. Tekzite records the exact auth HWND, detects when that window has visibly returned to YouTube, and sends a synchronous clean close directly to that HWND. Chromium History and cookie snapshots remain fallback signals, but they are no longer allowed to lag behind a visibly completed login.

### Reliable already-signed-in Google auth return (v10.5.65)

The Google/YouTube handoff no longer depends on an authentication cookie changing. Tekzite also watches Chromium's live History WAL for a fresh navigation back to the originating site, so an already-signed-in account can complete the handoff, close the standalone Chromium window, and refresh the Tekzite tab automatically. Before opening the auth window, Tekzite heals stale Chromium clean-exit metadata left by older releases and suppresses the legacy crash-recovery bubble.

### Clean Google-auth Chromium handoff (v10.5.64)

The Google sign-in handoff now closes Tekzite's embedded Chromium with Chromium's own `Browser.close` command before reusing the shared profile. The standalone sign-in window is also closed cooperatively with normal Windows close messages only. This prevents Chromium from treating the handoff as a crash and showing the “restore pages / wasn’t shut down correctly” bubble after login.

### Google sign-in completion handoff (v10.5.63)

Google authentication handoff now detects live Chromium cookie changes from SQLite WAL, closes the standalone sign-in window automatically, and performs a one-shot authenticated refresh of the originating tab.

### Release hygiene + maximize/restore guard (v10.5.62)

Tekzite now performs a final explicit DWM viewport reconciliation after maximize/restore, and the release metadata/test/build pipeline is synchronized around one source version. The release workflow builds directly from a pushed `vX.Y.Z` tag instead of replaying an old embedded source patch.

### Native Windows identity + Google auth handoff (v10.5.61)

The packaged browser now carries Tekzite's own native app identity and icon more consistently. Google sign-in can hand off to a normal visible Chromium window using the same profile, detect a settled authentication-cookie change, close that window normally, wait for the profile to be released, and then return to the embedded Tekzite tab.

### Drag lock after taskbar restore (v10.5.54)

Tekzite now refreshes the native Tk root HWND after every taskbar restore and again at the start of each custom title-bar drag. The DWM page surface is only moved when the real Tekzite root move succeeds, preventing a recreated DWM destination from drifting away on its own after minimize/restore.

### Fresh DWM destination on taskbar restore (v10.5.52)

Taskbar minimize retires the transient DWM destination HWND completely. On restore Tekzite creates a new hidden destination, reattaches the existing Chromium session to that HWND, registers a fresh thumbnail, and only then reveals the page. This avoids carrying a detached destination across Tk's minimize/restore wrapper transition.

### Cold DWM taskbar recovery (v10.5.51)

Taskbar restore now treats the DWM thumbnail as disposable compositor state. Tekzite keeps the raw destination hidden, forces a new DWM thumbnail registration, flushes the compositor, and only then fades the page surface back in. The internal destination window also has no visible caption text, so a delayed or failed thumbnail can never expose the old `Tekzite DWM Surface` label.

### DWM taskbar restore ownership (v10.5.49)

Tekzite now suspends its separate DWM presentation popup before minimizing the frameless browser window. On taskbar restore, the popup is reattached to the current native Tekzite owner and its non-activating tool-window style is reasserted before the webpage surface is shown again. This prevents the internal DWM surface from appearing as the front window after restore.

> **Platform:** Windows 10/11  
> **Status:** experimental, actively developed

### Local omnibox autocomplete (v10.5.48)

The address bar now shows instant local suggestions while you type. Results are ranked from bookmarks, open tabs, in-memory tab history, Tekzite history when enabled, and searches/addresses entered in the current session. Arrow keys move through suggestions, Tab accepts a suggestion without navigating, Enter opens the selected suggestion, and Escape closes the panel. Tekzite does not send partial typing to a remote autocomplete service.


## New in v10.5.47

- Replaces the unreliable Tk-only DWM keyboard path with a foreground-only Win32 key-state poller.
- Translates physical keys through the active Windows keyboard layout and forwards printable text to Chromium with `Input.insertText`.
- Keeps the safe lazy Tk focus sink, but no longer requires Tk to deliver `KeyPress` events for webpage typing to work.
- Handles Backspace, Enter, Tab, Delete, arrows, Home/End/PageUp/PageDown and common editing shortcuts on the same ordered Chromium input lane.
- Adds native keyboard-poller diagnostics while keeping raw Python Win32 callbacks out of bootstrap.

## New in v10.5.46

- Reintroduces the DWM keyboard-sink idea without the unstable raw Win32 subclass used by v10.5.44.
- Creates the sink lazily only after a real webpage click, so Chromium/DWM bootstrap remains untouched.
- Uses a Tk-owned native child HWND and Tk's normal key translation, then forwards keys through Tekzite's existing ordered Chromium input lane.
- Keeps Startpage/input typing support while removing the Python WNDPROC lifetime that could trigger bootstrap errors or a crash.
- Adds keyboard-sink diagnostics to the Tekzite debug report.

## New in v10.5.45

- Rolls back the experimental v10.5.44 native Win32 DWM keyboard-sink path after bootstrap errors and a crash were observed.
- Restores the stable v10.5.43 DWM input architecture, including its click-to-focus handling, without the extra native child HWND/WndProc layer.
- Keeps all v10.5.42 default-browser integration, centered dialogs, and v10.5.38 deterministic DWM viewport resizing intact.

## New in v10.5.43

- Fixes DWM-page text entry on sites such as Startpage by explicitly reclaiming Tekzite keyboard focus on a page click.
- Queues a Chromium point-focus immediately after the DWM mouse press on the same ordered CDP input lane, so fast keystrokes cannot arrive before the clicked input is focused.
- Keeps the existing zoom-aware DWM pointer mapping and native Chromium typography path unchanged.

## New in v10.5.42

- Fixes default-browser detection when Windows represents Tekzite with an `Applications\...exe` or other effective ProgID instead of the literal `TekziteBrowserURL` ProgID.
- Uses the Windows Shell's effective association executable for HTTP/HTTPS as the primary detection signal, with the read-only `UserChoice` ProgId retained as a fallback/diagnostic.
- Recognizes both installed `TekziteBrowser.exe` and versioned standalone Tekzite release executables.

## New in v10.5.41

- Detects the real Windows HTTP/HTTPS default-browser associations from the per-user `UserChoice` registry state.
- Settings shows whether Tekzite is fully default, partially assigned, or not default, and updates automatically after returning from Windows Default Apps.
- Detection is read-only; Windows retains control of the final default-app choice.

## New in v10.5.40

- Registers Tekzite as an available Windows browser for HTTP, HTTPS, .htm and .html using per-user Default Apps registration.
- Adds a **Make Tekzite default browser…** control in Settings that opens Windows 11 directly to Tekzite Browser in Default Apps for user confirmation.
- Accepts web URLs and local HTML files passed by Windows on the command line and gives those shell-activation targets priority over ordinary startup/session restore.
- Adds equivalent per-user browser registration to the Inno Setup installer and notifies Windows that associations changed.

## Highlights

- Chromium-only web rendering with a dedicated Tekzite profile.
- **UltraSpeed runtime:** 1 ms Windows timer request while running, above-normal browser/UI scheduling, execution-speed throttling disabled where supported, cached privacy hot paths and coalesced privacy-stat writes.
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
git clone https://github.com/bschilperoord/Tekzite-Browser.git
cd tekzite-browser

# Create an isolated environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install runtime dependencies for development
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
python -m py_compile main.py engine\net.py tekzite_network.py tekzite_network_fast.py ultraspeed_runtime.py ultraspeed_launcher.py
python -m pytest
```

The CI workflow runs these checks on Windows with supported Python versions. Official Windows packaging uses `requirements-windows.lock` and `requirements-build-windows.lock` with `pip --require-hashes`; the plain requirements files remain convenient development inputs.

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
ultraspeed_launcher.py      OneFile entry point + orderly helper shutdown
ultraspeed_runtime.py       Low-latency Windows process/runtime tuning
engine/net.py               Chromium, CDP, DWM and browser integration
tekzite_network.py          Loopback proxy, telemetry policy and ad blocking
tekzite_network_fast.py     Cached/coalesced UltraSpeed proxy hot paths
chromium_zoom_extension/    Local native Chromium zoom bridge
build_windows.ps1           Optimized Windows OneFile build pipeline
tests/current/              Tests for the current architecture
tests/legacy/               Historical version-specific regression tests
tools/doctor.py             Local environment diagnostics
docs/                       Architecture and release documentation
```

## Building the Windows UltraSpeed OneFile executable

The normal Windows release build packages Tekzite into a single `TekziteBrowser.exe`. The build also creates and embeds the `tekzite-network.exe` helper used by the loopback privacy proxy.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_windows.ps1
```

The result is:

```text
dist\TekziteBrowser.exe
```

At runtime PyInstaller expands the bundled application into a temporary `_MEI...` directory. Tekzite shuts down and reaps the bundled network helper before the OneFile bootloader removes that directory, preventing stale helper handles from blocking cleanup.

## Building the optional network helper executable

Tekzite can run the network helper from Python during development. To build the standalone Windows helper:

```powershell
# The build script uses the SHA-256 hash-locked Windows toolchain.
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



## New in v10.5.39

- Centers every Tekzite-owned dialog on the screen using one shared geometry helper before its opening animation begins.
- Settings now uses the same screen-center helper while retaining its larger deterministic size, scrollbar and pinned footer.
- Removes inconsistent browser-relative/default dialog placement without changing the native file/color picker behavior.

## New in v10.5.38

- Makes the DWM destination rectangle the authoritative Chromium viewport during window resizing.
- Fixes maximize/restore/snap cases where Chromium could remain at the old size while Tekzite had already grown, leaving a large white area beside or below the page.
- Reconciles DWM size on every non-drag root Configure event while filtering pure moves through the existing viewport cache.
- Adds a final delayed resize pass after maximize/restore so Windows and Tk layout settling cannot leave the DWM surface stale.

## New in v10.5.37

- Makes Settings sizing deterministic in Tk coordinate space and keeps its scrollable body with a pinned Save/Cancel footer.

## New in v10.5.32

- Keeps closed Chromium renderer targets out of the immediate close-then-new-tab path by debouncing target destruction for about 1.8 seconds.
- Opening or navigating a fresh tab postpones cleanup again, giving the new tab priority over Chromium teardown.
- Adds a 180 ms cancelable handoff window after an active tab closes, so a quick `+` click prevents replacement-target activation from even starting.
- Uses asynchronous DWM-popup hiding for blank/new-tab transitions.
- Paints homepage-style new tabs before their Chromium navigation starts.

## New in v10.5.31

- Active-tab close no longer starts Chromium work inside the tab's click/keyboard callback. The replacement tab becomes the logical selection immediately, while target activation starts after the close event returns.
- Soft tabs close on mouse release instead of mouse press, avoiding re-entrant destruction of the clicked tab widget.
- Chromium target activation and closure use short, loopback-only DevTools HTTP commands instead of the shared browser CDP WebSocket.
- A new-tab click or another tab action can cancel a pending close handoff.

## New in v10.5.25

- Unifies Tekzite-owned dialogs and menu option windows around the About Tekzite visual shell, with the Tekzite tile, title, version line, separator and consistent spacing.
- Applies the same DWM-safe native z-order behavior to every branded dialog so managers and settings windows do not disappear behind the webpage.
- Preserves each dialog's existing body space when the shared header is inserted.
- Keeps native Windows file/folder/color pickers native, while every Tekzite-rendered dialog uses the shared design.


## New in v10.5.24

- Adds a browser-wide motion system for Tekzite-owned windows, tools, settings, inspectors and managers.
- App windows now fade and lift into place and fade/settle out when closed, including Close/Escape paths wired before dialog controls are created.
- Replaces Tekzite message boxes and text prompts with animated theme-aware dialogs so warnings, errors, confirmations and input prompts match the rest of the browser.
- Adds a startup fade for the main shell, animated Customize page transitions, animated standard button hover/press feedback and animated Entry focus surfaces.
- Keeps Chromium/DWM webpage presentation outside the animation layer so page input, rendering and compositor timing remain untouched.
- Existing animated menus and Find-bar motion remain integrated with the same Animations/Quiet Mode preference.


## New in v10.5.18

- Fixes dark-theme omnibox URL text that could look half dark/half light from Windows ClearType subpixel rendering.
- Shows a grayscale-antialiased resting URL preview while retaining the real Tk Entry whenever the address bar is focused or edited.
- Clicking the URL preview focuses the omnibox and places the caret where you clicked.


## New in v10.5.17

- Replaces native popup menus with Tekzite-rendered rounded animated menus.
- Menus fade and slide into place with a short ease-out transition.
- Menu rows now have hover, keyboard-selection and tactile pressed/click feedback before actions run.
- Cascading submenus open on hover or click and animate independently.
- Top menu buttons stay visibly selected while their menu is open and click again to close.
- Escape, arrows, Enter and outside-click dismissal are supported without touching Chromium/DWM input.


## New in v10.5.16

- Uses a spacious layout by default with more breathing room around the title bar, menus, tabs, toolbar, omnibox, status bar and find bar.
- Increases default chrome heights and slightly enlarges core UI typography.
- Expands normal tabs to 175–330 px and shows up to 28 title characters by default.
- Starts at 1440×900 by default so the roomier browser chrome still leaves generous webpage space.
- Automatically migrates the untouched previous default layout, while layouts that the user changed remain unchanged.
- Retains the safe native Windows corner handling from v10.5.14 and the rounded modern control design from v10.5.13.


## New in v10.5.14

- Uses Windows' native DWM corner preference for the outer frameless window instead of clipping Tk with `SetWindowRgn`.
- Prevents the title/tab/toolbar region from becoming transparent and exposing the desktop.
- Keeps rounded web content and rounded controls intact.


## New in v10.5.13

- Adds rounded native window corners, rounded web-content presentation, rounded toolbar controls and a pill-shaped omnibox.
- Adds configurable Window, Web content and Controls corner radii.


## New in v10.5.12

- Verifies the Tekzite Network helper with a per-launch random instance token before terminating any listener PID, closing the remaining Windows PID/port reuse race.
- Restores Chromium client-side phishing detection and component updates instead of disabling them.
- Bounds website-controlled titles, URLs, origins and favicon URLs before they cross CDP into the Tekzite UI/state layer.
- Streams favicon responses with a hard 512 KiB cutoff instead of downloading an unlimited response before checking its size.
- Blocks direct opening of downloads unless Chromium reports a completed, safe/accepted state.
- Rejects DNS rebinding from ordinary public hostnames to private, loopback, link-local or other non-global addresses, and connects to the exact validated DNS result.
- Caps CDP WebSocket frames/messages to prevent oversized local DevTools messages from exhausting memory.
- Hash-locks the official Windows runtime/build dependencies and pins GitHub Actions to immutable commit SHAs.
- Hardens `main.py` customization-preset import and persisted homepage/search settings with type and size limits.


## New in v10.5.11

- Verifies stale Chromium PID markers before termination, preventing PID-reuse from killing an unrelated Windows process.
- Uses Chromium-assigned ephemeral CDP ports via `--remote-debugging-port=0` and validates `DevToolsActivePort`, listener ownership and loopback WebSocket URLs.
- Removes the broad `--remote-allow-origins=*` DevTools switch.
- Hardens website-controlled favicon decoding with format, compressed-size and decoded-dimension limits.
- Replaces silent private-profile deletion with retrying, verified cleanup and abandoned-profile scavenging.
- Caps proxy request headers and concurrent client threads, and rejects malformed authorities/headers.
- Pins runtime/build/development dependencies and adds `pip-audit` and Bandit checks to CI.
- Adds optional Authenticode signing support to the Windows build script and removes cache artifacts before builds.
- Updates `SECURITY.md` to match the extension's actual permissions and current CDP boundary.


## New in v10.5.10

- Tabs are wider by default, using a 150–290 px normal range before UI scaling instead of the previous 112–230 px range.
- Soft and Classic tabs now share the same pixel-width calculation.
- Customize Tekzite → Tabs & layout now exposes minimum and maximum tab widths.
- Pinned tabs stay compact and the `+` button remains directly beside the open tabs.


## New in v10.5.9

- Prevents the raw white Tekzite DWM destination from flashing during initial native page reveal.
- The layered DWM host is shown transparent first and becomes opaque only after the first compositor beat.
- Deferred DWM geometry updates preserve that transparency until reveal completes.


## New in v10.5.7

- Preserves Chromium single/double/triple-click semantics across the DWM input plane, including word and paragraph selection.
- Coalesces held-left drag motion while preserving the final pointer position before release, improving sliders, scrollbars and text selection under fast mouse movement.
- Adds browser-style middle-click link opening without depending on Chromium's hidden native chrome; non-link middle clicks still reach page auxclick/autoscroll handlers.
- Right-click now focuses the exact editable under the pointer before Tekzite builds its context menu, so Cut/Copy/Paste apply to the intended field.
- Shift+wheel is forwarded as horizontal scrolling and wheel modifier state is preserved through CDP.
- Printable AltGr characters are inserted correctly on European Windows keyboard layouts where Tk reports AltGr as Ctrl+Alt.
- Keeps all v10.5.6 native-pixel/CSS-pixel alignment fixes.

## New in v10.5.6

- Fixes DWM clicks being vertically displaced on scaled Windows displays.
- Pointer input now converts from the live native DWM/RenderWidgetHost pixel plane to Chromium CSS viewport coordinates.
- The scale is measured from the actual renderer and `window.innerWidth` / `window.innerHeight`, with `devicePixelRatio` as fallback.
- Browser zoom is not double-counted because Chromium already includes it in the effective device scale.
- The v10.5.5 crop-origin correction remains active before the CSS conversion.

## New in v10.5.5

- Fixes DWM click hit-testing when Chromium's live RenderWidgetHost origin differs from the currently committed visual crop.
- Pointer coordinates now use `crop origin - renderer origin` before native zoom conversion, so clicking a visible text field focuses that exact field instead of an element lower on the page.
- The correction is refreshed on full DWM crop discovery and retained across the fast resize path.

## New in v10.5.4

### DWM pointer interaction hardening

- The visible DWM page mirror remains a presentation surface, while Tekzite forwards pointer input to Chromium through CDP.
- A native Windows pointer watchdog now fills in missed hover, click, drag and release transitions if the separate DWM popup fails to pass a mouse event through to the Tk input plane.
- Fallback input is state-deduplicated, so normal Tk delivery does not produce double clicks.
- All DWM pointer paths share one crop- and zoom-aware coordinate transform, keeping the cursor aligned with links, buttons, text boxes and other page elements.
- Clicks send a pointer-move packet first, improving controls that arm or reveal behavior on hover.
- CSS cursor mirroring remains active for pointer, text, resize and other common web cursors.
- Includes the v10.5.3 Chromium chrome crop hotfix.

## New in v10.5.3

### Chromium chrome leak hotfix

- Fixes Chromium's own tab strip and omnibox appearing inside the Tekzite page area when Chromium reports native top chrome taller than the previous 160 px crop guard.
- The DWM page crop now accepts sane top-chrome insets up to 360 px while preserving at least a real page-sized renderer.
- Keeps the existing 1:1 DWM mirror, off-screen Chromium source, input mapping and presenter quarantine.
- Inherits the v10.5.2 UltraSpeed cleanup and release hardening.

## New in v10.5.2

### UltraSpeed cleanup and release hardening

- Keeps the v10.5.1 UltraSpeed runtime: 1 ms Windows timer request, above-normal process/UI scheduling, cached privacy hot paths and coalesced privacy-stat writes.
- Explicitly shuts down and reaps the bundled `tekzite-network.exe` helper before PyInstaller OneFile removes its temporary `_MEI...` directory.
- Uses a Windows process-tree fallback only when graceful helper shutdown does not complete in time.
- Keeps the DWM presentation path unchanged, avoiding risky window-hook or compositor changes.
- Synchronizes Windows executable metadata, Chromium extension metadata, installer metadata, tests and documentation on v10.5.2.
- The release artifact remains a single Windows x64 executable: `TekziteBrowser.exe`.

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

