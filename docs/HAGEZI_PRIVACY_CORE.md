# HaGeZi in Tekzite Privacy Core

Tekzite Privacy Core can optionally use the **HaGeZi Multi PRO Mini** domain
blocklist as an additional local blocking layer.

- Project: https://github.com/hagezi/dns-blocklists
- List: Multi PRO Mini, Wildcard Domains / only-domains format
- Runtime source:
  `https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/pro.mini-onlydomains.txt`
- Upstream license: GPL-3.0

Tekzite does not send browsing history or visited URLs to HaGeZi. The browser
periodically downloads the public list in the background, validates it, and
atomically stores a local copy. Tekzite Network performs browsing-time hostname
matching entirely against that local copy.

## Update and failure behavior

The normal refresh interval is eight hours. HTTP validators such as ETag and
Last-Modified are reused when available. Failed refreshes retain the
last-known-good list and retry on a shorter interval. A malformed, unexpectedly
small, or oversized response is rejected before it can replace the working
copy.

## User exceptions

The HaGeZi allowlist is stored locally. An allowlisted hostname also exempts its
subdomains from the HaGeZi layer. Tekzite's built-in telemetry/ad/tracker rules
remain separate from HaGeZi so disabling or updating the external list cannot
silently remove Tekzite's own protections.

## Statistics

Privacy Shield combines counters from both enforcement paths:

- Chromium DNR counters for Tekzite's bundled ad/tracker rules.
- Tekzite Network counters for telemetry, HaGeZi blocks, proxy-side
  ad/tracker blocks, and HTTPS upgrades.

This avoids the historical zero-counter problem where Chromium could block a
request before it ever reached the local proxy.
