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
- conservative host-based ad blocking;
- a narrow browser/vendor telemetry deny-list;
- buffered bidirectional CONNECT relay for backpressure-safe HTTP/2 traffic.

See `NETWORK_ENGINE.md` for implementation history and diagnostics.

### Native zoom bridge

`chromium_zoom_extension/` is a local Manifest V3 extension used only to control Chromium's actual tab zoom through `chrome.tabs.setZoom()`. It has no host permissions.

## State on disk

Tekzite preferences and Chromium profile data live under `%LOCALAPPDATA%\Tekzite Browser` on Windows. Contributors should not commit those files.
