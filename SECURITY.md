# Security Policy

Tekzite Browser is experimental software and has not undergone an independent security audit.

## Reporting a vulnerability

Please avoid posting sensitive exploit details in a public issue. If the GitHub repository has Private Vulnerability Reporting enabled, use that feature. Otherwise contact the repository owner privately and provide:

- affected Tekzite version;
- Windows and Chromium versions;
- reproduction steps;
- security impact;
- whether the issue involves the loopback proxy, CDP/debugging port, Chromium profile, DWM host or local zoom extension.

## Security boundaries

The intended design is:

- the Tekzite network helper listens only on loopback;
- Python-originated loopback egress is restricted by default to Tekzite's registered proxy and Chromium DevTools/CDP destination ports;
- the network-helper Python process may accept its loopback listener but is denied unexpected outbound loopback connects;
- HTTPS CONNECT is tunneled without TLS decryption;
- Chromium uses a dedicated Tekzite profile;
- the bundled local browser-services extension has `tabs`, `storage`, `downloads`, `downloads.open` and `declarativeNetRequest`; it has `http://*/*` and `https://*/*` host access because its privacy content script and declarative network rules operate on ordinary web pages;
- Chromium chooses an ephemeral DevTools port (`--remote-debugging-port=0`); Tekzite accepts the `DevToolsActivePort` endpoint only when it is loopback, the port matches, and on Windows the listener belongs to Chromium using the exact Tekzite profile;
- `--remote-allow-origins=*` is not used; Tekzite's internal CDP WebSocket client connects without an Origin header;
- the network helper receives a per-launch random instance token; a PID discovered from a remembered listener port is never eligible for forced termination unless its Windows process command line matches that token and port;
- public-looking proxy hostnames are resolved once and rejected if any resolved address is private, loopback, link-local, multicast, unspecified or otherwise non-global; explicit IP literals and conventional local names remain local-intent exceptions;
- website-controlled title/URL/favicon metadata is length-bounded before it crosses CDP; v10.5.80 fetches favicons outside page JavaScript with no page/session cookies, Authorization, Origin or Referer, rejects explicit local/private targets and local redirects, cuts transfer off at 512 KiB while streaming, and CDP WebSocket frame/message sizes are capped;
- direct download opening is allowed only after Chromium reports a completed download with a safe/accepted danger state;
- Tekzite does not disable Chromium client-side phishing detection or component updates;
- official Windows runtime/build dependencies are exact-version and SHA-256 hash locked, GitHub Actions use immutable commit SHAs, and CI runs `pip-audit` plus high-severity Bandit checks;
- the Live Socket View network-event monitor consumes Kernel-Network ETW metadata only while the view is open, filters it to Tekzite-owned PIDs, retains bounded short-lived UDP-peer and recent-TCP connect/accept metadata in RAM, and does not store packet payloads;
- the Live Socket View CDP request-attribution monitor runs only while the view is open and retains bounded metadata in RAM; JavaScript initiator frames are immediately reduced to origin hostname, final script filename, function, line/column and opaque target/script IDs, while full URLs/paths, query strings, headers, cookies, bodies and packet payloads are discarded; complete JavaScript source is requested only after explicit user action over a separate temporary DevTools channel; v10.5.78 may transiently pretty-print it, inspect its containing function/network primitives, and decode an inline source map, but only bounded excerpts/metadata are returned to the UI and nothing is written to disk or inserted into the audit ledger; external source maps are never fetched automatically;
- release executables can be Authenticode-signed by setting `TEKZITE_SIGN_CERT_SHA1` during `build_windows.ps1`.

Please report any behavior that breaks these assumptions.
### Live network audit privacy

The Live Socket View and Request timeline are ephemeral diagnostics. They retain bounded metadata in RAM only while the view is active. v10.5.78 may retain hostname-level causal metadata, response/TLS facts, transfer byte counts and presence-only hints for selected header names, but never stores header values, cookies, authorization values, request/response bodies, query strings, packet payloads or complete JavaScript source. On-demand JavaScript inspection may transiently pretty-print the complete generated source and decode an inline source map, but only bounded excerpts and sanitized mapping metadata leave that operation; external source maps are reported but never fetched automatically.

