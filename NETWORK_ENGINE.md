# Tekzite Chromium backend

Tekzite no longer implements a web rendering engine. Chromium owns HTML parsing, CSS, layout, JavaScript, media, storage, cookies, accessibility, canvas/WebGL, networking-visible page behavior and browser compatibility.

`engine/net.py` is an integration layer only: Chromium process/session management, CDP, DWM presentation, input forwarding and Tekzite network/privacy plumbing. It is not a separate page renderer.


## Privacy boundary

In Privacy Lockdown, Chromium is launched with a process-temporary profile and all ordinary HTTP/HTTPS browsing is routed through Tekzite's loopback proxy. The proxy blocks known vendor telemetry, advertising and dedicated analytics/tracker hosts and upgrades public HTTP requests to HTTPS. It never decrypts HTTPS CONNECT traffic. Built-in Chromium DoH and QUIC are disabled; DNS therefore follows the operating system/router path configured by the user.

This is browser privacy, not network anonymity: visited sites can still observe the public IP address unless an upstream VPN/proxy/Tor layer is used.
