# Tekzite v6.0 Chromium backend

Tekzite no longer implements a web rendering engine. Chromium owns HTML parsing, CSS, layout, JavaScript, media, storage, cookies, accessibility, canvas/WebGL, networking-visible page behavior and browser compatibility.

`engine/net.py` is an integration layer only: Chromium process/session management, CDP, DWM presentation, input forwarding and Tekzite network/privacy plumbing. It is not a separate page renderer.
