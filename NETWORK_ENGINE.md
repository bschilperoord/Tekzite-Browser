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
## Live connection overview

v10.5.71 adds a RAM-only destination ledger to the loopback proxy. Every allowed upstream HTTP/HTTPS connection and every host-level privacy decision updates a bounded in-memory row containing only hostname, port, protocol, status, count, active-tunnel count and timestamps. URL paths, query strings, request headers and payloads are never stored in the ledger.

Tekzite Python reads the snapshot through a private `GET http://tekzite.internal/__connections` control request on the existing proxy listener. The request must carry the random per-launch network-helper instance token; invalid or missing tokens receive a 404. The control request is served locally and is never forwarded upstream. No connection-overview file is written to disk.

For HTTPS, the proxy can see the CONNECT destination hostname and port but does not decrypt tunnel contents. The displayed count therefore represents upstream CONNECT tunnels, not every encrypted HTTP request multiplexed inside a tunnel.
## Full live socket view

v10.5.72 extends the proxy destination ledger with a Windows process-level owner-table monitor. `engine/net.py` enumerates `GetExtendedTcpTable` and `GetExtendedUdpTable` for IPv4 and IPv6, then filters the result to Tekzite's own PID plus its complete live descendant process tree. This captures the Tekzite UI process, Chromium browser/render/GPU/utility children, the Tekzite Network helper, and temporary child processes such as the standalone authentication Chromium while they remain descendants.

The dashboard reports role/process, PID, protocol/family, local endpoint, remote endpoint, TCP state and a route label. A public socket owned by Chromium instead of the network helper is labeled **Direct external**, making proxy bypasses visible. Chromium-to-proxy and CDP/DevTools loopback sockets remain visible rather than being hidden as implementation details.

For helper upstream TCP sockets, `tekzite_network.py` keeps an additional RAM-only association between the exact live socket tuple and the original requested hostname. The association is removed as soon as that upstream socket closes. This lets the UI display the requested site/subdomain instead of relying on CDN reverse DNS. For other remote IPs the UI can perform bounded asynchronous PTR enrichment; disabling that checkbox prevents those extra reverse-DNS lookups.

The owner tables remain the baseline for socket ownership. TCP exposes local/remote endpoints and state and is sampled every 250 ms, so an extremely short-lived TCP socket can theoretically exist entirely between samples. Windows' owner-PID UDP table exposes only the local endpoint, so v10.5.73 augments UDP with a live `Microsoft-Windows-Kernel-Network` ETW consumer while the dashboard is open.

Kernel-Network UDP send/receive metadata is filtered to Tekzite/Chromium/helper PIDs and correlated back to the owning local UDP endpoint. Each distinct recent remote IP/port is represented as its own peer row, including TX/RX packet and byte counters and last-seen age. This matters because one connectionless UDP socket can legitimately communicate with several peers. Remote peer IPs can use the same bounded background PTR enrichment as TCP destinations.

The ETW peer ledger is bounded, short-lived and RAM-only; no packet payload is copied into the monitor. Closing the Live Socket View stops the ETW session and discards its peer metadata. If Windows denies or cannot start the ETW session, the UI reports that status and falls back to the local UDP owner-table endpoint instead of guessing a peer.

