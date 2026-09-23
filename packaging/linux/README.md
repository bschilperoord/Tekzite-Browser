# Tekzite Browser Linux Preview

The first Linux preview uses Chromium `--headless=new` as the renderer and presents Chromium frames in Tekzite through CDP. This keeps the Tk shell native to Linux and avoids cross-process X11 reparenting, so the same architecture can run under X11, XWayland, or native Wayland.

## Runtime requirements

- Python 3.10+ for source runs, or the packaged `TekziteBrowser` executable
- Tk 8.6+
- a Chromium-family browser (`chromium`, `chromium-browser`, `google-chrome`, etc.)

Connection Forensics uses Linux procfs socket/PID ownership in this preview. It does not yet have the Windows build's ETW-equivalent short-lived event stream; an optional eBPF backend is a future target.
