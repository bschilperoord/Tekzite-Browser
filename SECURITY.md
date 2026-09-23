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
- website-controlled title/URL/favicon metadata is length-bounded before it crosses CDP, favicon transfer is cut off at 512 KiB while streaming, and CDP WebSocket frame/message sizes are capped;
- direct download opening is allowed only after Chromium reports a completed download with a safe/accepted danger state;
- Tekzite does not disable Chromium client-side phishing detection or component updates;
- official Windows runtime/build dependencies are exact-version and SHA-256 hash locked, GitHub Actions use immutable commit SHAs, and CI runs `pip-audit` plus high-severity Bandit checks;
- the Live Socket View UDP peer monitor consumes Kernel-Network ETW metadata only while the view is open, filters it to Tekzite-owned PIDs, retains a bounded short-lived peer ledger in RAM, and does not store packet payloads;
- release executables can be Authenticode-signed by setting `TEKZITE_SIGN_CERT_SHA1` during `build_windows.ps1`.

Please report any behavior that breaks these assumptions.
