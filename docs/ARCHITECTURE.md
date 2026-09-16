# Tekzite Browser architecture

## Overview

Tekzite is a Windows browser shell around Chromium. It does not implement HTML, CSS or JavaScript itself.

### Browser shell

`main.py` owns the Tk UI: tabs, omnibox, menus, preferences, keyboard shortcuts, Find in Page, tab metadata display and UI animation.

### Chromium integration

`engine/net.py` discovers and launches a Chromium-family executable with:

- a dedicated Tekzite profile;
- a local CDP endpoint;
- the local native-zoom extension;
- the Tekzite loopback network helper as Chromium's proxy.

It also owns target creation/activation, input forwarding, page metadata, native zoom control and DWM presentation.

### DWM presentation

Chromium remains a top-level source window parked off-screen. Tekzite creates a destination window and uses `DwmRegisterThumbnail` / `DwmUpdateThumbnailProperties` to mirror Chromium into the Tekzite content viewport.

The source and destination are kept at a 1:1 presentation scale. Native Chromium zoom changes page layout; DWM does not perform page zoom.

### Input

The visible DWM thumbnail does not directly receive Chromium input. Tekzite forwards mouse and keyboard interaction through CDP. Pointer coordinates are corrected for verified native Chromium zoom before being dispatched.

### Network helper

`tekzite_network.py` is a loopback HTTP proxy with HTTPS CONNECT tunneling. It provides:

- end-to-end HTTPS tunneling;
- vendor telemetry blocking (ad filtering moved to the local extension in v10.0);
- a narrow browser/vendor telemetry deny-list;
- buffered bidirectional CONNECT relay for backpressure-safe HTTP/2 traffic.

See `NETWORK_ENGINE.md` for implementation history and diagnostics.

### UltraSpeed runtime and OneFile packaging

Windows release builds enter through `ultraspeed_launcher.py`. Before importing the Tk/browser stack, `ultraspeed_runtime.py` applies conservative process-local latency tuning. The current layer requests 1 ms timer resolution while Tekzite is running, gives the browser process and UI thread above-normal scheduling priority, and disables Windows execution-speed power throttling where supported.

`tekzite_network_fast.py` wraps the normal network helper policy rather than replacing it. It accelerates repeated host classification, policy-file checks and privacy-stat persistence while retaining the blocking semantics implemented by `tekzite_network.py`.

The release executable is a PyInstaller OneFile package. Its bundled `tekzite-network.exe` runs as a child process from PyInstaller's temporary `_MEI...` extraction directory. On browser shutdown the UltraSpeed launcher explicitly stops and reaps that child before the bootloader removes the extraction directory.

### Native zoom bridge

`chromium_zoom_extension/` is a local Manifest V3 extension used only to control Chromium's actual tab zoom through `chrome.tabs.setZoom()`. It has no host permissions.

## State on disk

Tekzite preferences and Chromium profile data live under `%LOCALAPPDATA%\Tekzite Browser` on Windows. Contributors should not commit those files.

### v10.0 browser services

`browser_features.py` owns downloads/history dialogs, pins, quiet mode and periodic state checkpoints. `browser_state.py` writes atomic JSON files beside preferences. `engine/features.py` serializes extension requests through a dedicated DevTools connection to the existing extension service worker; it creates no page or window. As of v10.0.2, startup launches the requested page directly, and optional services initialize after successful presentation. Proxy fallback protection remains until extension rules are confirmed.

The extension adds downloads and declarativeNetRequest permissions to tabs/storage, without host permissions. Packaged static rules block the existing ad domains. Higher-priority dynamic main-frame allowAllRequests rules implement hostname exceptions. The proxy retains independent telemetry filtering and end-to-end CONNECT tunnels. In v10.0.1 it also filters ads until the extension confirms its configuration, using a local atomic fallback-policy file. Optional extension initialization errors are recorded without aborting launch.

### v10.1 private windows, site privacy and user extensions

Private windows are separate Tekzite processes started with `--private`. `main.py` creates a process-unique temporary Chromium user-data directory and exports it through `TEKZITE_CHROMIUM_PROFILE`; `engine/net.py` uses that override instead of the persistent profile. Private windows skip session restoration, history recording and state checkpoints, and always erase the temporary Chromium profile on close.

Enabled unpacked user extensions are persisted in Tekzite preferences. Before Chromium starts, `main.py` exports their validated directories as JSON in `TEKZITE_USER_EXTENSIONS`. `engine/net.py` combines those directories with the mandatory bundled local-services extension when constructing Chromium's `--disable-extensions-except` and `--load-extension` switches. Invalid/missing paths are ignored at launch.

Site Info uses the existing persistent per-tab CDP channels. It requests non-secret cookie metadata, security state when Chromium exposes it, and origin storage usage/quota. Clearing site data uses `Storage.clearDataForOrigin` for the active origin; Tekzite never needs cookie values for this UI.

### v10.3 customization layer

`main.py` keeps all Tekzite-owned chrome customization in the profile-local `preferences.json` under the `customization` object. `_normalized_customization()` validates colors, clamps dimensions/scales, de-duplicates toolbar ordering and supplies safe defaults before any widget consumes the values.

The customization layer deliberately styles only Tekzite browser chrome. Website content remains Chromium-owned and is not rewritten. Runtime preview updates the palette, typography, toolbar packing, tab rendering and chrome visibility without restarting Chromium or recreating page targets. The omnibox search template is stored separately as `search_url_template` and must contain `{query}`.

A hidden toolbar/address bar remains recoverable with `Ctrl+L`. `Ctrl+Shift+Alt+R` resets only interface customization, leaving browsing data, bookmarks, history and Chromium profile data untouched. JSON preset import/export carries customization only and is portable between Tekzite profiles.
