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
