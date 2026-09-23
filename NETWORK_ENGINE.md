# Tekzite Chromium backend

Tekzite no longer implements a web rendering engine. Chromium owns HTML parsing, CSS, layout, JavaScript, media, storage, cookies, accessibility, canvas/WebGL, networking-visible page behavior and browser compatibility.

`engine/net.py` is an integration layer only: Chromium process/session management, CDP, DWM presentation, input forwarding and Tekzite network/privacy plumbing. It is not a separate page renderer.


## Privacy boundary

In Privacy Lockdown, Chromium is launched with a process-temporary profile and all ordinary HTTP/HTTPS browsing is routed through Tekzite's loopback proxy. The proxy blocks known vendor telemetry, advertising and dedicated analytics/tracker hosts and upgrades public HTTP requests to HTTPS. It never decrypts HTTPS CONNECT traffic. Built-in Chromium DoH and QUIC are disabled; DNS therefore follows the operating system/router path configured by the user.

This is browser privacy, not network anonymity: visited sites can still observe the public IP address unless an upstream VPN/proxy/Tor layer is used.

## UltraSpeed helper lifecycle

The Windows OneFile build embeds `tekzite-network.exe` inside `TekziteBrowser.exe`. At startup PyInstaller extracts the bundled files into its temporary `_MEI...` runtime directory and `engine/net.py` launches the network helper from there.

Tekzite therefore treats helper shutdown as part of the OneFile lifecycle. The UltraSpeed launcher stops the helper before Python returns control to the PyInstaller bootloader, waits for the process to release its executable handle, and uses a Windows process-tree termination fallback only when graceful shutdown times out. This lets PyInstaller remove its temporary runtime directory cleanly.

The UltraSpeed proxy layer in `tekzite_network_fast.py` preserves the privacy policy from `tekzite_network.py` while caching repeated hostname classification, avoiding repeated JSON parsing when the ad-block policy file has not changed, coalescing privacy-counter writes during bursts and using a larger relay buffer.
## Browser-owned favicon fetches (v10.5.80)

Tab favicon retrieval is intentionally kept outside webpage execution. Tekzite reads only the resolved favicon URL from the live DOM metadata and then performs a browser-owned GET through Tekzite Network. The request does not import Chromium/page cookies, does not add Tekzite's session cookie jar, and does not send Authorization, Origin or Referer. Any `Set-Cookie` response is ignored.

Because the icon URL is website-controlled input, the helper accepts only bounded `data:` content or public HTTP(S) targets, rejects explicit loopback/private/link-local/local-name destinations before opening a socket, re-checks the final redirect target, and stops reading after 512 KiB. Public-name DNS rebinding remains subject to Tekzite Network's resolved-address policy. A short-lived hostname-only internal-activity record lets the Live Socket View identify this traffic as **Tekzite favicon fetch** without keeping the URL path/query or pretending the request came from page JavaScript.

## Live connection overview

v10.5.71 adds a RAM-only destination ledger to the loopback proxy. Every allowed upstream HTTP/HTTPS connection and every host-level privacy decision updates a bounded in-memory row containing only hostname, port, protocol, status, count, active-tunnel count and timestamps. URL paths, query strings, request headers and payloads are never stored in the ledger.

Tekzite Python reads the snapshot through a private `GET http://tekzite.internal/__connections` control request on the existing proxy listener. The request must carry the random per-launch network-helper instance token; invalid or missing tokens receive a 404. The control request is served locally and is never forwarded upstream. No connection-overview file is written to disk.

For HTTPS, the proxy can see the CONNECT destination hostname and port but does not decrypt tunnel contents. The displayed count therefore represents upstream CONNECT tunnels, not every encrypted HTTP request multiplexed inside a tunnel.
## Full live socket view

v10.5.72 extends the proxy destination ledger with a Windows process-level owner-table monitor. `engine/net.py` enumerates `GetExtendedTcpTable` and `GetExtendedUdpTable` for IPv4 and IPv6, then filters the result to Tekzite's own PID plus its complete live descendant process tree. This captures the Tekzite UI process, Chromium browser/render/GPU/utility children, the Tekzite Network helper, and temporary child processes such as the standalone authentication Chromium while they remain descendants.

The dashboard reports role/process, PID, protocol/family, local endpoint, remote endpoint, TCP state and a route label. A public socket owned by Chromium instead of the network helper is labeled **Direct external**, making proxy bypasses visible. Chromium-to-proxy and CDP/DevTools loopback sockets remain visible rather than being hidden as implementation details.

For helper upstream TCP sockets, `tekzite_network.py` keeps an additional RAM-only association between the exact live socket tuple and the original requested hostname. The association is removed as soon as that upstream socket closes. This lets the UI display the requested site/subdomain instead of relying on CDN reverse DNS. For other remote IPs the UI can perform bounded asynchronous PTR enrichment; disabling that checkbox prevents those extra reverse-DNS lookups.

The owner tables remain the baseline for current socket ownership. TCP exposes local/remote endpoints and state and is sampled every 250 ms. Starting with v10.5.75, the same live `Microsoft-Windows-Kernel-Network` ETW consumer also retains recent TCP connect/accept events, so a flow that disappears between snapshots can remain briefly as a **RECENT** row. Windows' owner-PID UDP table exposes only the local endpoint, so v10.5.73+ augments UDP with ETW send/receive peer events while the dashboard is open.

Kernel-Network UDP send/receive metadata is filtered to Tekzite/Chromium/helper PIDs and correlated back to the owning local UDP endpoint. Each distinct recent remote IP/port is represented as its own peer row, including TX/RX packet and byte counters and last-seen age. This matters because one connectionless UDP socket can legitimately communicate with several peers. Remote peer IPs can use the same bounded background PTR enrichment as TCP destinations.

The ETW network-event ledger is bounded, short-lived and RAM-only; no packet payload is copied into the monitor. Closing the Live Socket View stops the ETW session and discards UDP peer and recent-TCP metadata. If Windows denies or cannot start the ETW session, the UI reports that status and falls back to owner-table data rather than inventing peer or recent-flow information.
## Live request attribution (v10.5.74)

While **Tools -> Network Connections** is open, Tekzite can correlate socket-level data with Chromium DevTools Network metadata. A dedicated observer websocket is used for each exposed page/worker/extension target so the audit stream does not contend with Tekzite's input/control CDP lanes. `Network.requestWillBeSent` contributes destination hostname, target scope, resource type and initiator type/hostname; `Network.responseReceived` may additionally supply a remote address/port for direct-endpoint correlation.

The audit is intentionally metadata-only and RAM-only. Full URLs, paths, query strings, headers, cookies, request bodies and response bodies are not retained. The monitor starts with the Live Socket View and stops with it. Consequently, an already-open connection may initially be **Unattributed** until a new request is observed; refreshing the page after opening the view provides the most complete attribution.

Tekzite Network's active-upstream ledger also records the current Chromium-side loopback endpoint tuple while a proxy tunnel is alive. This permits a `chrome.exe -> 127.0.0.1:<proxy>` socket to be associated with the same destination hostname as the helper's public upstream without decrypting TLS. PyInstaller one-file helper descendants are classified as part of the Tekzite Network process tree, so a payload child that owns the public socket is not mislabeled as a direct bypass.
## Script-to-socket forensics (v10.5.75)

The CDP request monitor now extracts a sanitized initiator stack when Chromium provides one. Each frame is reduced immediately to origin hostname, final script filename, function name and 1-based line/column; full script URLs and directory paths, query strings, fragments and script source text are discarded. CORS preflights can inherit the already-sanitized caller chain from the request that caused them. `Network.webSocketCreated` is also observed so script-created WebSockets are not a blind spot.

A request on the same host is not automatically declared to have opened a socket. Tekzite correlates the proxy's exact upstream-open timestamp with recent Chromium request metadata and, when available, the CDP response's `connectionReused`, `connectionId`, protocol and remote endpoint. **Strong opener** means exact requested hostname + close timing + `connectionReused = false`; **Likely opener** means exact hostname + timing with no reuse verdict; **Probable opener** uses exact endpoint/timing evidence when the hostname is unavailable. Explicitly reused requests are labeled **Reused connection**, while weaker host/endpoint correlations remain **Host activity** or **Endpoint activity**. This is important for HTTP/2, where many requests and scripts can share one TCP/TLS connection.

The Details dialog exposes the sanitized call chain and correlation evidence while preserving the same RAM-only lifetime as the Live Socket View. It does not retain complete request URLs, URL paths, query strings, request/response headers, cookies, request/response bodies, packet payloads or JavaScript source contents.
## On-demand JavaScript source excerpts (v10.5.76)

The request-attribution ledger stores only sanitized script labels plus Chromium's opaque target-local `targetId` / `scriptId`. When the user explicitly presses **Show script source** in the socket Details dialog, Tekzite opens a separate temporary DevTools websocket to that live target, enables the Debugger domain and calls `Debugger.getScriptSource` for that one script. The normal Network observer websocket is not reused, so source inspection cannot swallow or reorder network events.

The complete source returned by Chromium is reduced immediately to a bounded excerpt around the recorded caller line/column. Very long or minified lines are clipped around the caller column and the exact position is marked with a caret. The complete script source is not inserted into the request ledger, written to disk or retained after the source-view operation completes. If the target navigated away, the script was replaced, or the request had no JavaScript caller, the UI reports that source is unavailable.
## v10.5.77 causal request timeline

While **Tools -> Network Connections** is open, the existing dedicated CDP Network observers now keep a bounded RAM-only causal request timeline in addition to host/socket attribution. The timeline stores only sanitized metadata: target/destination hostnames, method/resource type, same-site relation heuristic, initiator/script caller chain, response status/MIME, encoded byte count, cache/service-worker flags, redirect host lineage, failure reason, connection reuse/transport, and TLS protocol/cipher/issuer.

Request/response header **values are never retained**. Tekzite may record only the presence of selected names (`Cookie`, `Authorization`, `Origin`, `Referer`, `Set-Cookie`) when Chromium exposes them in the Network event. Absence is not interpreted as proof that the browser did not send a header. Full URLs, paths, query strings, bodies, cookies, packet payloads and full script source remain outside the live ledger.
## v10.5.78 deep JavaScript caller inspection

On explicit **Show script source** action, Tekzite now uses a dedicated Debugger websocket to capture the requested script's `Debugger.scriptParsed` metadata and `Debugger.getScriptSource` result. The complete generated source remains local to that single operation. A lightweight formatter maps the captured generated line/column into a readable pretty-printed excerpt, while a lexical brace pass finds the smallest credible containing function. Strings, comments, template literals and regex literals are treated as non-code for direct network-primitive scanning, reducing false positives from minified bundles and embedded text.

The inspector recognizes direct browser network APIs including `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `navigator.sendBeacon` and `WebTransport`, reporting their generated positions relative to the captured caller. This is a code-presence trace, not an execution proof beyond the authoritative CDP initiator frame itself, and the UI says so explicitly.

Source-map handling is intentionally evidence-preserving. Inline Source Map v3 data is decoded locally and can map the generated caller back to a sanitized original filename/name/line/column and bounded `sourcesContent` excerpt. External `sourceMapURL` values are reduced to hostname + final filename and are not fetched automatically. This avoids creating extra outbound traffic simply by inspecting existing traffic. Full generated source, inline map payloads and `sourcesContent` are never inserted into the request ledger or written to disk.

