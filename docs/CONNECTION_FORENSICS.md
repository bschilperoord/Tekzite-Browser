# Connection Forensics

Tekzite Browser's **Tools → Network Connections** is built to answer a question normal browser network panels often leave fragmented across several tools:

> **Why does this connection exist, and what code caused it?**

Tekzite correlates browser request evidence with Windows socket ownership and its local Tekzite Network proxy, producing a causal chain such as:

```
process → socket → proxy → hostname → request → JavaScript caller → response
```

## What the view can correlate

For traffic observed while the monitor is open, Tekzite can combine:

- Windows process/PID and TCP/UDP socket ownership
- local and remote endpoints, TCP state, and short-lived ETW connection events
- the exact hostname requested through Tekzite Network
- page, worker, service-worker, extension, and browser-internal request context
- request purpose and resource type
- sanitized JavaScript caller/function/line/column and async call-chain evidence
- connection-reuse evidence, so activity on an HTTP/2 socket is not automatically called the socket opener
- redirects, response status, MIME type, transfer size, cache/service-worker delivery, and TLS metadata
- on-demand caller source inspection with bounded excerpts, local pretty-printing, and inline source-map decoding

## Evidence, not accusations

An unknown connection is shown as **Unattributed**. Tekzite does not automatically label unknown traffic as telemetry.

Socket-opening confidence is also explicit. Depending on the evidence available, a request may be shown as **Strong opener**, **Likely opener**, **Probable opener**, **Reused connection**, or merely host/endpoint activity.

This distinction matters because one HTTP/2 or HTTP/3 connection can serve many requests from many scripts.

## Privacy boundaries

The forensic view is intentionally metadata-focused rather than a packet sniffer.

Its rolling ledgers are bounded and RAM-only while the monitor is open. Tekzite does not retain packet payloads, full request URLs, query strings, request/response bodies, cookie values, authorization values, or complete JavaScript source.

Header observations are presence-only hints where Chromium exposes them. Script source is retrieved only when the user explicitly requests it, reduced to a bounded excerpt, and not written into the network ledger.

External source maps are reported but not silently downloaded, because creating a new network request while auditing another request would contaminate the evidence.

## Browser-internal traffic is labeled separately

Tekzite v10.5.80 removes the old page-context favicon `fetch(..., credentials:'include')` helper.

The browser now only reads the page's favicon URL, validates it, and performs a small browser-owned request through Tekzite Network without page cookies, Authorization, Origin, or Referer. Private/local targets and redirects into local address space are rejected.

Matching traffic can therefore be labeled explicitly as **Tekzite internal / Tekzite favicon fetch** rather than being mistaken for website JavaScript.

## Why this is useful

The goal is to make browser networking inspectable without requiring the user to manually reconcile DevTools, Task Manager, Resource Monitor, ETW traces, and a proxy log.

Tekzite keeps those layers separate internally, then joins only the minimum evidence needed to explain a connection.
