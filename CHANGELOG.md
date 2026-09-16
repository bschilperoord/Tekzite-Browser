# Tekzite Browser v10.5.1

## UltraSpeed

- Added a low-latency Windows runtime layer.
- Requests 1 ms Windows timer resolution while Tekzite is running.
- Uses above-normal scheduling for the browser process and UI thread.
- Disables Windows execution-speed power throttling where supported.
- Added cached tracker, telemetry and ad-host classification.
- Avoids repeated adblock JSON parsing while preserving instant live policy updates.
- Coalesces privacy-counter disk writes during request bursts.
- Increased proxy relay buffer efficiency.
- Reduced OneFile size and startup overhead by excluding unused heavy Python modules.
- Preserves the existing DWM fast paths and Privacy Core behavior.

# Tekzite Browser v10.5.0

v10.5.0 introduces the **Luxe UI**: rounded Canvas-rendered tabs, optional macOS-style traffic-light window controls, Aurora Glass and OLED Neon themes, and a more layered premium browser chrome while preserving Tekzite's Privacy Core.

# Changelog

## v10.5.0 — Luxe UI

- Added true rounded **Soft Tabs** rendered on Tk Canvas with active accent pills, hover surfaces, favicons and dedicated close hit areas.
- Added **Traffic Lights** window controls with red/yellow/green drawn controls, hover glyphs and macOS-style left-side placement.
- Kept the existing Tekzite window controls as a selectable alternative on the right side.
- Added **Aurora Glass** and **OLED Neon** presets alongside Aurora, Midnight, OLED Black, Graphite and Light.
- Added live customization options for `window_control_style` and `tab_style`; both remain profile-specific and exportable.
- Refined chrome layering, toolbar borders, tab spacing and titlebar proportions without enabling risky whole-window transparency.
- The glass appearance is composited from opaque layered surfaces so Chromium/DWM presentation stays stable.

## v10.4.0 — Privacy Core

- Added **Privacy Lockdown**, enabled by default. Normal browsing history and open-tab sessions are not persisted while it is active.
- Chromium runs from a process-temporary profile in Lockdown, then the profile is erased on shutdown; bookmarks and explicitly downloaded files remain user-owned data.
- User-installed unpacked extensions are disabled in Lockdown so an arbitrary extension cannot silently widen the browser's privacy boundary.
- Changed the default omnibox search provider to Startpage.
- Added conservative tracking-parameter removal for `utm_*`, `fbclid`, `gclid`, `msclkid` and other known click IDs while preserving unknown query parameters.
- Added dedicated tracker/analytics host blocking in both the local network proxy and the bundled Chromium ruleset.
- Added HTTPS-first upgrades for ordinary HTTP browsing, with loopback kept separate for local development/device compatibility.
- Added global DNT + GPC signaling and referrer stripping. Chromium client metadata headers are stripped by the bundled privacy ruleset where supported.
- Blocked/disabled Chromium background networking, sync, crash reporting, domain reliability, prediction/prefetch, built-in DoH, QUIC, non-proxied WebRTC UDP and Privacy Sandbox ad APIs.
- Expanded default-deny device permissions to include camera, microphone, geolocation, notifications, sensors, MIDI SysEx, WebBluetooth/USB/Serial/HID and idle detection paths where Chromium exposes those controls.
- Added **Tools → Privacy Shield** with a live, destination-free audit of enabled protections and aggregate counters for blocked telemetry, trackers, ads, HTTPS upgrades and stripped tracking parameters.
- Privacy counters store totals only, not a browsing destination log. HTTPS CONNECT remains end-to-end encrypted; Tekzite does not MITM TLS.
- Retains the strict Python loopback destination allow-list introduced in v10.3.6.
- Explicitly documents the remaining boundary: without an upstream VPN/proxy/Tor layer, visited websites can still observe the network's public IP address.

## v10.3.6 — Strict Python loopback policy and port diagnostics

- Registers Tekzite Network proxy and Chromium DevTools/CDP ports by purpose before Python connects to them.
- Blocks all other Python-originated loopback destination ports while leaving public internet connections unaffected.
- Revokes transient allow-list entries when services stop or Chromium launch attempts fail.
- Adds **Tools → Local Ports & Loopback** with service-purpose labels, live Windows endpoint rows, temporary source-port explanation and recent denied attempts.
- Records only denied loopback events in a bounded audit log, not normal web destinations.

## v10.3.5 — Tekzite-native window controls

- Replaced plain Windows-style titlebar glyphs with custom-drawn Tekzite minimize, maximize/restore and close controls.
- Added themed hover/pressed states while preserving frameless drag, maximize and DWM behavior.

## v10.3.4 — Reliable Chromium bootstrap target claim

- Starts the cold Chromium bootstrap on `about:blank`, claims the existing app target, then performs normal navigation.
- Prevents redirects/canonicalization from making Tekzite lose the first Chromium target.
- Waits briefly for DevTools target discovery and uses a guarded sole-page fallback.

## v10.3.1 — DWM performance hardening

- Added a low-overhead steady-state DWM thumbnail resize path.
- Avoided `DwmFlush` on normal interactive resize updates.
- Batched native window + DWM-host drag moves into one deferred Win32 commit.
- Prevented move-only DWM updates from generating unnecessary resize work.
- Rate-limited Chromium presenter cleanup while preserving full recovery paths.

## v10.3.0 — Fully customizable Tekzite UI

- Added per-profile customization with live preview, JSON import/export and safe UI-only reset.
- Added editable palette roles and Midnight, OLED Black, Graphite and Light presets.
- Added custom fonts, font sizes, density, UI scale and animation preference.
- Added toolbar ordering, visibility and icon/text/both label modes.
- Added app-bar, branding, menu, window-control, tab-strip, favicon, close-button, group-chip, active-indicator, scrollbar and status-dot toggles.
- Added tab-strip placement, new-tab button placement, tab-title length and configurable chrome heights.
- Added initial/minimum window sizing and start-maximized preference.
- Added configurable omnibox search URL templates while preserving Ctrl+L as a recovery path when toolbar/address chrome is hidden.


## v10.2.1 — Standard browser controls

- Added Back, Forward, Reload/Stop and Home controls to the main toolbar.
- Added a bookmark star in the omnibox with add/remove toggle behavior.
- Added dedicated Downloads and three-dot browser menu buttons.
- Added Chromium `Page.stopLoading` support so Reload becomes Stop during page loads.
- Removed debug buttons from the primary toolbar while preserving them under Tools.

## v10.2.0 — Browser management & productivity suite

- Added real sleeping tabs with configurable inactivity timeout and pinned-tab protection.
- Added persistent tab groups with collapse/expand controls and session restore.
- Added per-origin Permissions Manager for notifications, location, microphone, camera, clipboard and sensors.
- Expanded Downloads with pause/resume, open file/folder, retry, cancel and remove-from-list actions.
- Added configurable download save prompting.
- Added profile isolation for Tekzite state and Chromium browsing data.
- Added GitHub release update checks with optional SHA-256 verification when GitHub publishes an asset digest.
- Added Diagnostics and Task Manager panels.
- Added crash-recovery prompt for sessions left with an unclean-exit checkpoint.
- Extended Preferences with sleeping-tab, download and updater controls.

# v10.1.1

- Serialize Chromium bootstrap/recovery to prevent competing helper launches.
- Confirm DevTools failure twice before replacing a running Chromium session, then dispose stale CDP channels and helper processes cleanly.
- Recover a crashed Tekzite Network Engine on Chromium's existing proxy port and watch its health in the background.
- Retain one previous valid JSON generation and use it when a primary state/preferences file becomes corrupt.
- Contain Tk callback exceptions in a bounded local stability log instead of letting UI callbacks fail silently.
- Make browser shutdown idempotent and cancel queued Tk timers before tearing down native windows.
- Replace stale per-tab Chromium target IDs after helper recovery and reload tabs whose old target disappeared.

# v10.1.0

- Add private windows on Ctrl+Shift+N using process-unique temporary Chromium profiles.
- Prevent private windows from restoring/saving Tekzite sessions or writing browsing history; always erase private Chromium data on close.
- Add Site Info & Privacy with live Chromium security, cookie-count and origin-storage information.
- Add origin-scoped Clear Site Data without exposing cookie values or clearing unrelated sites.
- Add an unpacked Chromium Extension Manager with add, enable/disable, remove, folder, permission/details and safe restart controls.
- Launch enabled user extensions beside Tekzite's mandatory local browser-services extension.
- Keep extension launch configuration validated and ignore stale/invalid extension folders instead of failing browser startup.

# v10.0.2

- Restore the requested direct app launch URL from the v9.8 startup path.
- Defer optional extension services until after successful native/software presentation.
- Retry transient render-owner replacement before attachment and after compositor priming, retaining live-host validation.
- Record retry counts and activation errors for diagnosis.

# v10.0.1

- Prevent optional extension-service readiness failure from aborting Chromium startup.
- Enable/wake the service-worker runtime before readiness checks and recover a missing entry point using bundled local code.
- Retain proxy ad blocking as a fallback until extension configuration succeeds; support live policy changes.
- Include service readiness/error details in debug reports.
- Guard service imports so failure cannot prevent zoom listener registration.

# v10.0

- Add Chromium downloads panel with live progress, cancel, retry/resume and open folder.
- Add searchable local history and Clear History; honor Clear browsing data on exit.
- Move ad filtering into local extension rules with persistent hostname exceptions.
- Add compact pinned tabs, protected from bulk close and retained in sessions.
- Add quiet mode for fewer controls and reduced animation.
- Save session checkpoints every two seconds for crash recovery.
- Configure blocking rules before first webpage navigation. Use the extension worker without creating extra DWM presenters.

# v9.9

- Add persistent bookmarks, Ctrl+D, and an open/rename/remove manager.
- Restore tab order and selected tab after normal exit, loading background tabs on selection.
- Add a preference to disable restoration.
- Keep unsubmitted address-bar text out of saved tab URLs.

## v9.8 black-launch hardening hotfix

- Protects all plausible live `Chrome_WidgetWin_1` presenters from asynchronous late-presenter hiding.
- Keeps the on-screen native black-surface probe enabled when first-frame readiness was proven semantically without a PNG capture.
- Reduces the chance of an intermittent stale/black DWM thumbnail during Chromium startup while preserving the fast startup path.

# v9.8

- Prewarm the native Win32 window-drag path before the first user drag.
- Move the Tekzite top-level HWND directly with SetWindowPos during live dragging.
- Move the DWM Chromium destination in the same native drag frame.
- Suppress redundant Tk Configure -> DWM chase scheduling while the native dual-window drag path is active.
- Keep Tk root.geometry() only as a fallback/final bookkeeping path.

# v9.6

- DevTools startup polling no longer performs a full process-tree/window-hide scan on every miss.
- DevTools readiness now polls at 10 ms and reuses the successful /json/version WebSocket URL for the persistent browser-control channel.
- Chromium HWND discovery uses a cheap root-PID-first path and refreshes descendant PIDs only as a fallback.
- Removed a redundant 12 ms sleep after DwmFlush during DWM source sizing.
- Moved three 40 ms late-presenter parking passes off the first-reveal critical path into a daemon maintenance thread.
- Deferred the cold-start one-pixel resize kick briefly so naturally settling Chromium geometry does not pay an unnecessary compositor flush.

# v9.5

- Clean-profile cold starts skip expensive Win32_Process/CIM recovery scans.
- Full Chromium profile recovery runs only when dirty-session markers exist or a first launch fails.
- Chromium top-level window discovery polling tightened from 100 ms to 10 ms.
- Startup diagnostics now record profile recovery, process spawn, DevTools readiness and window-discovery timings.

## 9.2

- Collapsed native cold startup from two first-frame readiness gates to one hidden attached-frame gate.
- Prefer DOM + native render-host geometry for first-frame proof and capture a screenshot only as fallback.
- Reduced compositor readiness polling from 120 ms sleeps to roughly one frame cadence.
- Warm only the critical input CDP lane before reveal; scroll/hover lanes now warm asynchronously after the page is visible.
- Skip synchronous 100% zoom application on native cold startup and poll the navigation worker at 8 ms instead of 40 ms.

## 9.1

- Added a hot-navigation fast path for already-attached native Chromium tabs.
- Removed repeated first-frame, input-readiness, native-attachment, and synchronous zoom work from ordinary navigations.
- Allowed Chromium DNS prefetch while keeping DNS-over-HTTPS disabled.
- Enabled TCP_NODELAY on Tekzite Network proxy sockets and increased the accept backlog for bursty page loads.

## 8.9 - Lower steady-state interaction latency

- Enabled TCP_NODELAY on local Chromium DevTools WebSockets so tiny CDP input commands are sent immediately.
- Split CSS cursor/computed-style probes onto a dedicated low-priority CDP lane and worker, leaving page hover movement unobstructed.
- Removed the redundant post-click JavaScript focus round-trip from the common click path; Chromium's native CDP mouse gesture now owns focus directly.
- Preserved the v8.8 first-visible-frame interactivity gate and the independent input/scroll/hover lanes.

## 8.8 - First-visible-frame interactivity

- Keeps the DWM destination hidden until Chromium has consumed a real event on the critical CDP input lane.
- Verifies a laid-out DOM plus a harmless `Input.dispatchMouseEvent` round-trip after warming the low-latency channels.
- Removes the startup window where Startpage could already be visible while the first click was still racing renderer readiness.


## 8.7 - Low-latency I/O lanes

- Split clicks/typing, wheel scrolling, and hover/cursor traffic onto independent persistent Chromium CDP WebSockets.
- Pre-warm all latency-sensitive CDP channels before the first native DWM page is revealed.
- Coalesce precision-wheel bursts so stale scroll packets cannot queue ahead of later interaction.
- Warm per-tab I/O channels in the background when switching tabs.
- Reduced browser-chrome metadata polling overhead while keeping live titles/loading state responsive.

## v8.4 — Low-latency interaction and richer tab controls

- Split hover/cursor CDP work from critical click, wheel and keyboard input so cosmetic probes cannot delay real interaction.
- Mouse movement is now latest-value-only with at most one hover dispatch in flight, preventing stale pointer-event queues on busy pages.
- Tightened DWM destination geometry coalescing from ~60 Hz to ~120 Hz while retaining viewport-change checks before Chromium resize.
- Added a tab context menu with Duplicate Tab, Reopen Closed Tab, Copy Tab URL, Close Other Tabs, and Close Tabs to the Right.
- Added Search Selected Text to the webpage context menu.
- Preserved the v8.3 off-Tk-thread synchronized tab activation path.

## v8.3 — Faster synchronized tab presentation

- Moved Chromium target activation off Tk's UI thread so tab switching no longer stalls browser chrome.
- Serialized rapid tab-switch requests to keep Chromium and Tekzite on the same final tab.
- Commit tab highlight, address bar and history only after Chromium target activation succeeds.
- Added a lightweight native redraw + DWM flush after target activation without resizing or rebuilding the embedded Chromium host.
- Preserved v7.5's hot-switch path while reducing the visible old-frame lag between tab chrome and page content.

## v8.2 — GitHub-ready repository

- Reworked the root README into contributor-friendly setup and architecture documentation.
- Added GitHub Actions CI, issue templates and a pull-request template.
- Added CONTRIBUTING, SECURITY, repository ignore/line-ending/editor configuration and release documentation.
- Added a current-architecture test suite while preserving historical version-specific tests under `tests/legacy/`.
- Added `tools/doctor.py`, Windows launch helpers and deterministic build dependencies for the optional network helper executable.
- Browser runtime behavior remains based on v8.1.

Historical release notes preserved from the pre-GitHub Tekzite Browser builds.

## v8.1 — Smooth UI animations

- Lightweight eased hover transitions for tabs, toolbar buttons, the + tab button, and close buttons.
- Animated address-bar focus colors.
- Find in Page now slides open and closed instead of snapping.
- Preferences fades in after it has been measured and centered.
- Loading tabs use a lightweight animated spinner without touching Chromium/DWM.
- Animations are coalesced/cancelled per widget option so rapid mouse movement cannot build a Tk `after()` backlog.
- Chromium rendering, DWM presentation, native zoom, input mapping, networking, and fast tab switching are unchanged.

# Tekzite Browser v8.1 — Browser UX

v8.0 is the first dedicated browser-UX release on top of the Chromium/DWM architecture.

- Live Chromium page titles in the tab strip.
- Favicons are fetched from inside Chromium and displayed per tab.
- Per-tab loading indicator.
- Middle-click a tab to close it.
- Ctrl+Shift+T reopens the most recently closed tab.
- Ctrl+F opens Tekzite Find in Page, with Enter/Shift+Enter for next/previous.
- Ctrl+Tab / Ctrl+Shift+Tab cycles tabs; Ctrl+1..9 jumps directly.
- Address-bar context menu now includes Paste and Go; Ctrl+Shift+V does the same while the omnibox is focused.
- Existing v7.5 fast native tab switching remains intact.

# Tekzite Browser v7.9

## UI polish

- Refined OLED-first browser chrome with clearer active, hover, and muted states.
- Active tabs now use a thin accent indicator instead of a bright boxed border.
- Inactive tabs are quieter and gain contrast only on hover.
- Tab close controls stay understated until interaction and use a clear danger hover state.
- More compact 58 px toolbar and tighter navigation/address-bar spacing.
- Smaller, quieter new-tab control and softer chrome separators.
- No Chromium/DWM, zoom, input, network, or rendering architecture changes in this release.

# Tekzite Browser v7.8

- Chromium background window is now born off-screen and remains off-screen.
- DWM source is parked before it is mapped, preventing Chromium window flashes behind Tekzite.
- Auxiliary Chrome presenter windows are hidden after parking.
- DWM continues to mirror the live Chromium source at 1:1.

# Tekzite Browser v7.7

## Text selection over DWM

- Added full left-button drag forwarding from Tekzite's DWM input plane to Chromium.
- Text on webpages and text inside inputs can now be selected by click-dragging.
- Drag coordinates use the existing native Chromium zoom-aware mapping from v7.2.
- The explicit click-focus bridge is skipped after a real drag so it cannot collapse the selection.
- CDP mouse dispatch now carries Chromium's `buttons` bitfield during press/drag/release.

# Tekzite Browser v7.6

## Built-in Tekzite Adblock

- Built-in ad blocker is enabled by default.
- Blocks dedicated advertising hosts in Tekzite's loopback proxy before DNS/upstream connection.
- HTTPS remains end-to-end; Tekzite does not decrypt or rewrite page traffic.
- Conservative rules cover major ad-serving networks such as DoubleClick, Google ad serving, Xandr/AppNexus, Criteo, Taboola, Outbrain, PubMatic and OpenX.
- Normal YouTube, Google, Microsoft and Startpage hosts are not blanket-blocked.
- Preferences includes **Block ads with Tekzite Adblock**. Restart Tekzite after changing it because the network helper is started per browser session.
- Existing browser/vendor telemetry blocking remains independent of ad blocking.

# Tekzite Browser v7.5

## Faster tab switching
- Existing native Chromium tabs now use a DWM hot-switch path.
- The live DWM host stays visible and keeps its current geometry during normal tab switches.
- No repeated host hide/show, `update_idletasks()`, Chromium viewport resize, or full geometry rebuild when the viewport is unchanged.
- `Target.activateTarget` now uses the persistent browser CDP connection first; `/json/list` is only a fallback if activation fails.
- Native zoom verification for the newly selected tab is deferred until after the visual switch instead of synchronously re-applying zoom to every open tab.
- Full Debug includes `tab_switch_fast_path_count`.

# Tekzite Browser v7.4

- Removed the Microsoft/telemetry explanatory sentence from Preferences.
- Microsoft website access and the existing telemetry protection remain unchanged.
- All v7.3 typography and Chromium/DWM behavior is preserved.

# Tekzite Browser v7.3

## Typography pass

- Keeps Chromium on its native Windows LCD/subpixel text path. Tekzite removes any accidental `--disable-lcd-text`, `--disable-font-subpixel-positioning`, or `--disable-directwrite-for-ui` launch switches before Chromium starts.
- Does not inject global CSS font smoothing or replace website fonts, so page layout, metrics, popovers, and SPA behavior remain Chromium-native.
- DWM remains a 1:1 presentation surface, avoiding resampling blur.
- Tekzite chrome now prefers `Segoe UI Variable Text` and `Segoe UI Variable Display` when Windows provides them, with `Segoe UI` fallback.
- Full Debug reports the active typography safeguards.

# Tekzite Browser v7.2

- Fixes DWM pointer hit-testing after native Chromium browser zoom.
- Converts visible DWM physical-pixel coordinates to Chromium CSS viewport coordinates using the verified native zoom factor.
- The correction is centralized in the shared input transform, so click, focus, hover, cursor probing, context menus and wheel position stay aligned at 125%, 150%, 175%, 200%, etc.
- Falls back to 1:1 input coordinates unless the native zoom extension has actually been verified active.
- Adds `dwm_input_zoom_factor` and `dwm_input_zoom_active` to Full Debug.

# Tekzite Browser v7.1

- Fixes native Chromium zoom not visibly scaling pages.
- Uses `chrome.tabs.setZoomSettings(..., {mode: "automatic", scope: "per-tab"})` before `chrome.tabs.setZoom()`.
- The zoom bridge now verifies every eligible tab with `chrome.tabs.getZoom()` after applying the Preferences value.
- Keeps the v7.0 native Chromium zoom watchdog and DWM 1:1 presentation.

# v7.0 - Native Chromium zoom

- Replaces CSS `documentElement.style.zoom` with Chromium's real `chrome.tabs.setZoom()` API.
- Bundles a local-only Manifest V3 Tekzite Native Zoom Bridge extension.
- Uses `chrome.tabs.onZoomChange` to restore the Preferences zoom immediately if it changes.
- Reapplies zoom on tab creation, navigation/update and activation.
- Keeps DWM at a strict 1:1 presentation scale.
- Fixes fixed/popover UI such as YouTube's profile menu being clipped by CSS-root zoom.
- No page DOM mutation is used for zoom.

# Tekzite Browser v6.9

- Microsoft websites are no longer globally blocked by Tekzite Network.
- Microsoft pages, Microsoft account login, Outlook, Office, OneDrive, Bing, Azure-backed page assets and related Microsoft web/CDN traffic can pass normally.
- The narrow browser/vendor telemetry deny-list remains active, including explicit `*.events.data.microsoft.com` and `*.telemetry.microsoft.com` endpoints.
- Tekzite still uses its dedicated Chromium backend; allowing Microsoft websites does not switch the browser engine to Microsoft Edge.

# v6.8 - Preferences visibility + webpage cursor sync

- Preferences is built hidden, measured, centered on the active monitor, then explicitly shown/focused with safe fallback geometry.
- DWM webpage input now mirrors the effective CSS cursor under the pointer via a coalesced CDP probe.
- Links/buttons show a hand cursor, editable text shows a text cursor, resize/move/crosshair/wait styles are mapped to native Tk/Windows cursors where available.
- Cursor probing is single-flight and piggybacks on the existing coalesced hover path to avoid flooding CDP.

# v6.8 - Preferences visibility fail-safe

- Preferences is built while withdrawn instead of starting as a 1-pixel window.
- Natural content size is measured before the dialog becomes visible.
- The dialog is centered on Tekzite's current monitor work area.
- If Win32 monitor detection fails, a safe Tk screen fallback is used.
- Preferences is explicitly deiconified, raised, grabbed and focused after final geometry is set.
- Keeps v6.7 zoom watchdog behavior.

# v6.7 - Zoom watchdog + monitor-centered Preferences

- Actively monitors every live Chromium tab's effective page zoom every 1.5 seconds.
- Reapplies the authoritative Preferences zoom only when a settled page has changed/reset it.
- Does not mutate pages while `document.readyState` is still `loading`.
- Preferences opens centered on the monitor containing the Tekzite browser window.
- Preferences height follows its actual content height, capped only if the monitor cannot contain it.
- Keeps v6.6 buffered CONNECT relay and v6.5 post-load zoom behavior.

# v6.6 - buffered Chromium CONNECT tunnels

- Fixes a transport bug in Tekzite Network that could stall heavy HTTP/2 sites such as YouTube on skeleton placeholders.
- Replaces non-blocking `sendall()` with a select-driven buffered relay that handles temporary socket backpressure instead of dropping the CONNECT tunnel.
- Preserves half-close semantics and limits queued bytes per direction.
- Keeps v6.5 post-load Preferences zoom, Chromium-only rendering, and DWM presentation unchanged.

# v6.5 - YouTube-safe post-load zoom

- Removes all pre-navigation/document-start zoom mutation.
- Never touches documentElement while document.readyState is `loading`.
- Applies the saved Preferences zoom only after the document becomes interactive/complete.
- Keeps retry checks after navigation so every page still receives the saved zoom once safe.
- Retains Chromium-only architecture and DWM 1:1 presentation.

# v6.4 - SPA-safe universal zoom

- Keeps Preferences zoom universal across all Chromium pages.
- Applies CSS zoom once per document instead of continuously observing/re-writing SPA DOM trees.
- Removes YouTube-specific popup inverse-zoom mutation.
- Keeps new-document bootstrap so redirects and new pages inherit the saved zoom.
- DWM remains a 1:1 presentation layer.

# v6.3 - Preferences zoom is authoritative on every web page

- The saved **Default page zoom** from Preferences is passed into Chromium before each target is created, claimed, or navigated.
- New tabs inherit the saved zoom immediately from the persistent Chromium session instead of starting from a 100% session default.
- Existing tabs install the zoom new-document bootstrap before address-bar navigation, so redirects and renderer swaps inherit the same value.
- Zoom is reasserted after navigation and across the short settle window as a safety net for target/renderer swaps.
- DWM remains a 1:1 presentation mirror and never performs image-level zoom.
- Full Debug now reports the Preferences zoom seed and pre/post-navigation application status.

# v6.2 - Stable navigation viewport

- Stops Chromium/DWM navigation recrops from repeatedly shrinking and expanding the real page viewport.
- Keeps the last proven Chromium custom-chrome height locked while a new site settles.
- A changed chrome measurement must repeat three consecutive times before it can alter the physical source viewport.
- Skips off-screen Chromium source resizes entirely when the current source size already satisfies the 1:1 DWM contract.
- Removes the old two-pass `viewport -> measure -> viewport+chrome` resize cycle that made scrollbars visibly jump during navigation.
- Retains v6.1 hidden startup DWM surface and smoother ~60 Hz window dragging.

# v6.1 - hidden DWM startup + smoother window movement

- Keeps the raw Win32 DWM presentation host hidden until Chromium has produced a usable first frame and received the real Tekzite viewport.
- Coalesces DWM host move/resize traffic to roughly one update every 16 ms instead of reacting to every Tk Configure event.
- Pure top-level window movement now repositions only the DWM destination. Chromium is resized only when the page viewport dimensions actually change.
- DWM host geometry updates preserve z-order instead of repeatedly forcing HWND_TOP while dragging.
- Chromium-only v6 architecture remains unchanged.

# Tekzite Browser v6.0 - Chromium-only architecture

- Chromium is now the **only web engine**.
- Removed Tekzite's legacy HTML parser, CSS/layout engine, painter, TinyJS runtime, webfont/layout debug engine, and automatic native-renderer fallback.
- Tekzite keeps its own browser chrome: tabs, omnibox, menus, preferences, history controls, debug controls, DWM host and input forwarding.
- Every web navigation goes directly to Chromium/CDP.
- DWM remains the native presentation layer, with Tekzite-only right-click handling and Chromium page zoom.
- Preferences no longer expose `auto` or `native` renderer choices.
- Full Debug is now Chromium/DWM-focused rather than reporting the removed renderer pipeline.

# v5.44 - DWM-aware page zoom

- Keeps Tekzite zoom as real Chromium page zoom/reflow rather than scaling the DWM thumbnail.
- Every successful zoom apply schedules short DWM geometry/crop refreshes while Chromium settles.
- DWM remains a strict 1:1 mirror of the current Chromium viewport at every zoom level.
- Full Debug records `dwm_zoom_percent`, `dwm_zoom_refresh_count`, and thumbnail X/Y scale.
- Retains v5.43 source-local crop measurement and v5.41 Tekzite-only context menu.

# v5.43 - DWM source-local renderer crop

- Fixes Chromium title/app chrome reappearing after URL-bar navigation.
- Measures the page RenderWidgetHost directly inside the active DWM source (`Chrome_WidgetWin_1`) instead of reusing the separate presenter window's renderer.
- Uses the source-local renderer Y offset as the authoritative DWM top crop (31 px in the captured YouTube navigation case).
- Re-measures the source-local renderer on every v5.42 navigation recrop pass.
- Keeps the known-good outer DWM source, 1:1 presentation, Tekzite-only context menu, form focus, and presenter quarantine.

# v5.42 - navigation-aware DWM chrome recrop

- Re-measures the live Chromium RenderWidgetHost before every DWM source-crop calculation.
- Adds delayed DWM re-crop passes after navigation so YouTube/consent/SPA geometry can settle without exposing Chromium's custom title bar.
- Keeps the known-good Chrome_WidgetWin_1 DWM source from v5.40/v5.41.
- Retains Tekzite-only right-click menus, form focus, pointer alignment, presenter quarantine, and hands-off RenderWidgetHost behavior.

# v5.41 - Tekzite-only right-click menu

- Chromium no longer receives right-button mousePressed/mouseReleased events from the DWM/native input plane.
- Tekzite still resolves link, image, selection and editable-field context through CDP `elementFromPoint()` and shows its own browser context menu.
- This prevents Chromium's native context menu from ever being triggered, including on pages where JavaScript contextmenu suppression would be unreliable.
- Left-click, typing, wheel, hover and the existing DWM presentation remain unchanged.

# v5.40 - working outer DWM source with dynamic custom-chrome crop

- Reverts the DWM source to the proven `Chrome_WidgetWin_1` path from v5.38.
- Measures the real page RenderWidgetHost height after sizing the source client to the Tekzite viewport.
- Treats a sane render-height shortfall as Chromium custom-drawn top chrome (31 px in the observed Startpage run).
- Expands the parked Chromium source client by that measured amount, then crops exactly that top strip in DWM.
- Keeps a 1:1 page pixel contract and avoids the black presenter-only DWM source from v5.39.
- Adds debug fields for measured custom chrome and render sizes before/after expansion.

# v5.38 - DWM client-area-only source

- Removes Chromium's native title bar / minimize / maximize / close controls from the DWM mirror.
- Uses `DWM_TNP_SOURCECLIENTAREAONLY` with `fSourceClientAreaOnly=True` instead of manually mixing outer-window and presenter coordinates.
- Resizes the parked Chromium outer window so its client area matches the Tekzite viewport 1:1.
- Keeps v5.37 top-page visibility, v5.36 pointer alignment, form focus, context menu placement, and presenter quarantine.

# v5.37 - DWM top-edge visual alignment

- Fixes top-edge webpage UI being clipped in DWM mode, including Startpage's hamburger menu.
- Uses the live page-renderer origin to correct the DWM visual source crop instead of only correcting mouse coordinates.
- Recalculates pointer alignment after the visual crop correction, so the picture and CDP input use the same origin.
- Keeps the v5.34 1:1 pixel contract, v5.35 form focus, and v5.36 dynamic pointer measurement.

# v5.36 - DWM pointer coordinate alignment

- Fixes needing to click below visible controls such as the Startpage search field.
- Measures the live page-renderer offset before Chromium presenters are parked.
- Converts DWM source-crop coordinates into CDP page coordinates instead of assuming both origins are identical.
- Applies the same correction to click, hover, wheel, context-menu hit testing, and editable-element focus.
- Keeps v5.35 form focus, v5.34 1:1 DWM sizing, presenter quarantine, and native DWM presentation.

# v5.35 - DWM form focus + keyboard fallback

- Fixes clicks on Startpage/search/form fields not accepting typed text in DWM mode.
- After mouse release, Tekzite explicitly focuses the editable DOM element under the clicked page coordinate over CDP.
- Adds a root-level DWM keyboard fallback for cases where Tk leaves focus on the toplevel instead of `edge_host`.
- Address-bar editing revokes page keyboard ownership so typing cannot leak into the webpage.
- Retains v5.34 1:1 DWM maximize/zoom behavior and v5.33 context-menu positioning.

# v5.34 - 1:1 DWM viewport / maximize crop fix

- Keeps a stable Chromium app-frame crop instead of recomputing it after maximize/restore.
- Resizes the parked Chromium source window to `Tekzite viewport + stable chrome margins` on every native resize.
- Mirrors an exact page-sized source rectangle into an equal-sized DWM destination, eliminating DWM stretch/softness.
- Prevents Chromium title/window bars from leaking into the thumbnail when Tekzite is maximized.
- Page zoom remains Chromium/CSS zoom; DWM presentation no longer introduces a second visual scale.

# v5.33 - DWM context-menu cursor coordinates

- Fixes the browser context menu appearing at the top-left of the desktop in DWM mode.
- Popup placement now uses Win32 `GetCursorPos()` at right-click time instead of relying on Tk `event.x_root` / `event.y_root`.
- Chromium element hit-testing still uses page-local coordinates, so popup screen placement and page context are kept separate.
- Retains v5.32 click-to-focus, keyboard input, DWM presentation, and presenter quarantine.

# Tekzite Browser v5.32

- Makes the DWM browser viewport focusable and interactive instead of presentation-only.
- Binds click, release, hover, wheel, keyboard and right-click input to `edge_host`, the Tk input plane beneath the hit-test-transparent DWM popup.
- Clicking the webpage now gives the browser surface keyboard focus and forwards the click to Chromium over CDP.
- Printable text uses `Input.insertText`; navigation keys and Ctrl shortcuts use CDP key events.
- Right-click first forwards the gesture to Chromium, then opens Tekzite's browser-style context menu using live DOM metadata for links, images, selections and editable controls.
- DWM presentation, v5.31 presenter quarantine and hands-off RenderWidgetHost behavior remain unchanged.

# Tekzite Browser v5.31

- Keeps the working v5.30 DWM live webpage surface.
- Parks every top-level Chromium `Chrome_WidgetWin_*` presenter from the dedicated Tekzite Chromium process tree, not only the DWM source window.
- Prevents auxiliary `Chrome_WidgetWin_0` windows from leaking onto the desktop as a giant black square.
- Chromium child `Chrome_RenderWidgetHostHWND` surfaces remain completely hands-off.
- Re-scans briefly after DWM registration to catch late-created Chromium presenters.

# Tekzite Browser v5.30

- Replaces the Tkinter DWM thumbnail destination with a genuine raw Win32 `WS_POPUP` HWND owned by Tekzite.
- Avoids Tk `TkTopLevel` wrappers that still report `WS_CHILD` and are rejected by `DwmRegisterThumbnail`.
- The raw DWM host uses `WM_NCHITTEST -> HTTRANSPARENT`, so mouse input falls through to Tekzite's existing CDP input surface.
- Keeps Chromium source presentation untouched and retains strict app-target binding / direct app launch.

# Tekzite Browser v5.29

## Real top-level HWND fix for DWM thumbnails

- Fixes `DwmRegisterThumbnail` failing with `HRESULT=0x80070057` when Tkinter `winfo_id()` returns the inner Tk client HWND rather than the native top-level wrapper.
- Resolves both DWM destination and Chromium source through Win32 `GetAncestor(..., GA_ROOT)` before registration.
- Validates that both resolved handles are top-level (no `WS_CHILD`) and that the destination belongs to the Tekzite process, as required by DWM.
- Full Debug now records requested/resolved HWNDs, window classes, PIDs, and top-level validation.
- Keeps the v5.28 DWM presentation design: no `SetParent`, no RenderWidgetHost mutation, Chromium remains the live DComp source.

# Tekzite Browser v5.28

## DWM thumbnail native presentation

- Chromium remains an untouched top-level DirectComposition source.
- Tekzite creates a borderless owned top-level viewport over its content area because Windows requires DWM thumbnail destinations to be top-level windows.
- `DwmRegisterThumbnail` / `DwmUpdateThumbnailProperties` mirror the Chromium app surface into Tekzite.
- The Chromium source window is parked off-screen and kept mapped; it is not reparented.
- The RenderWidgetHost HWND remains completely hands-off.
- Mouse, wheel, keyboard, and context-menu input continue through the existing CDP input lane.
- Legacy `SetParent` fallback is disabled for this path.

# Tekzite Browser v5.27

Treats Chromium child overflow as valid native geometry. Tekzite now aligns the visible owner/RenderWidgetHost intersection to the viewport instead of rejecting negative raw crop margins, preventing the successful top-level overlay from falling back into legacy SetParent embedding. The RenderWidgetHost remains completely Chromium-owned.

# Tekzite Browser v5.26

Maps and positions the Chromium owner before measuring the untouched RenderWidgetHost. The page RWH remains fully Chromium-owned; Tekzite only shows and positions its top-level owner, preventing hidden-owner 1x1 geometry collapse.

# Tekzite Browser v5.25 — hands-off native RenderWidgetHost

- Chromium's `Chrome_RenderWidgetHostHWND` is now strictly read-only from Tekzite.
- Removed direct `SetWindowPos`, `ShowWindow`, `RedrawWindow`, and `UpdateWindow` operations on the page render host.
- Removed the legacy compositor-prime mutation pass; direct-app launch now lets Chromium establish its own DirectComposition tree.
- Tekzite still positions only the Chromium owner window and keeps strict app-target binding, direct `--app=<URL>` launch, and live owner geometry alignment.
- New debug fields expose `render_host_hands_off`, `render_host_mutation_calls`, and compositor-prime touch state.

# Tekzite Browser v5.24

v5.24 makes the first native Chromium tab a true direct-app launch. Chromium starts with the requested URL in `--app=<URL>` instead of `--app=about:blank`, Tekzite claims that exact original app target, and the first-tab path skips the redundant CDP `Page.navigate` when the launch target is already the requested page. This removes the final about:blank -> navigation compositor transition while preserving strict app-target binding, native GPU defaults, and live-render geometry alignment.

## 9.3
- Reused the persistent critical input CDP channel for first-frame readiness.
- Removed temporary readiness websocket and redundant Page/Runtime domain enable calls.
- Skipped Network-domain setup on latency-only input/scroll/hover/cursor lanes.
- Reused semantic first-frame proof for the initial input readiness check.
- Deferred screenshot fallback and reduced readiness polling latency.
- Avoided DwmFlush in the readiness miss loop.

## 9.7
- Coalesced custom title-bar window dragging so raw high-rate mouse motion keeps only the latest pending position.
- Capped live Tk top-level position commits to roughly 120 Hz instead of calling `root.geometry()` for every mouse report.
- Reduced DWM destination tracking to roughly 60 Hz while an interactive drag is active, with an immediate exact sync on release.
- Pure top-level moves continue to avoid Chromium viewport resize work entirely.
- Added drag-performance regression coverage.
