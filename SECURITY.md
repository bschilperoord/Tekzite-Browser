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
- HTTPS CONNECT is tunneled without TLS decryption;
- Chromium uses a dedicated Tekzite profile;
- the local zoom extension has `tabs` and `storage` permissions and no host permissions;
- remote debugging is intended for Tekzite's local Chromium instance only.

Please report any behavior that breaks these assumptions.
