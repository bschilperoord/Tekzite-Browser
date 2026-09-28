# Tekzite Browser

<img width="1440" height="900" alt="Tekzite Browser" src="https://github.com/user-attachments/assets/88364722-0d94-4430-a42a-63769e5ff262" />

Tekzite Browser is an experimental desktop browser shell built in Python/Tk around a real Chromium renderer.

Tekzite owns the browser interface, including tabs, the address bar, menus, settings and interaction layer. Chromium handles the web itself: HTML, JavaScript, media, cookies, WebGL and page rendering.

> **Current release:** v10.5.106 UltraSpeed  
> **Platforms:** Windows 10/11 and Linux  
> **Status:** experimental and actively developed

## What makes Tekzite different?

Tekzite is built around a custom browser interface without trying to replace Chromium's web engine.

Some of the main features are:

- Custom tabs, omnibox, menus and window chrome
- Chromium rendering with native web compatibility
- Local omnibox suggestions
- Tab groups, sleeping tabs and pinned tabs
- Private windows and isolated profiles
- Per-site permissions and privacy controls
- Downloads, bookmarks and history
- Custom themes, layouts, fonts and UI scaling
- Google/YouTube authentication handoff
- Windows DWM-based Chromium presentation
- Linux support
- Built-in diagnostics and network inspection

## Network Connections

**Tools → Network Connections** shows live browser networking in a way that is meant to be understandable rather than mysterious.

Where enough evidence is available, Tekzite can connect:

`process → socket → hostname → request → JavaScript caller → response`

It can show current TCP/UDP activity, process ownership, requested hostnames, request purpose, Chromium initiators and selected response metadata.

The monitor is designed as a debugging and transparency tool, not a packet sniffer. Its working ledgers are bounded and kept in memory while the monitor is open. Tekzite does not use it to retain page contents, cookies, request bodies or complete script source.

If Tekzite cannot confidently explain a connection, it stays **Unattributed** instead of being guessed as telemetry.

## HTML Inspector

**Inspect Chromium HTML** provides a read-only view of the current page source.

For Chromium pages it can inspect the live DOM after JavaScript has run. Native-source paths retain the original response source where available.

The inspector includes syntax coloring, search navigation, document statistics and a compact source-oriented layout.

## Privacy

Tekzite is designed to make browser behavior visible and configurable.

Privacy-related features include:

- Local-first address suggestions
- Per-site permission controls
- Optional browsing-data cleanup
- Temporary profiles for private windows
- Tracking-parameter stripping and blocking controls
- A browser-owned favicon fetch path that does not reuse page cookies or authorization headers
- Network inspection that avoids storing full URLs, headers, cookies or payloads

Tekzite is still experimental software, so privacy-sensitive users should review the source and configuration for their own requirements.

## Interface

Tekzite has its own customizable browser chrome rather than exposing Chromium's normal tab strip and omnibox.

You can customize things such as:

- Colors and visual presets
- Tabs and toolbar layout
- UI and display fonts
- Corner radii
- Density and scaling
- Window controls
- Animations
- Homepage and search provider

The goal is to keep the interface flexible without turning normal browsing into a settings dashboard.

## Building from source

Clone the repository and install the required dependencies for your platform.

### Windows

```powershell
.\build_windows.ps1
```

### Linux

```bash
bash build_linux.sh
```

Release builds are also produced by GitHub Actions and published on the repository's **Releases** page.

## Project layout

A few useful places to start:

- `main.py` — Tekzite UI and browser shell
- `engine/` — Chromium/native browser integration
- `tekzite_network.py` — Tekzite Network helper
- `chromium_zoom_extension/` — bundled Chromium-side browser services
- `tests/current/` — active regression suite
- `CHANGELOG.md` — detailed release history
- `SECURITY.md` — security notes and reporting information

## Releases

The README intentionally stays focused on what Tekzite is today.

Detailed version-by-version notes live in [CHANGELOG.md](CHANGELOG.md), and downloadable Windows/Linux builds are available from [GitHub Releases](https://github.com/bschilperoord/Tekzite-Browser/releases).

## License

See the repository license for the terms that apply to Tekzite Browser.
