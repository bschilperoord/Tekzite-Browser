"""Auto-updating HaGeZi integration for Tekzite Privacy Core.

The browser process owns update/download policy. Blocking itself remains local
inside Tekzite Network and never depends on HaGeZi being reachable at browse time.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

HAGEZI_NAME = "HaGeZi Multi PRO Mini"
HAGEZI_SOURCE_URL = (
    "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/"
    "wildcard/pro.mini-onlydomains.txt"
)
HAGEZI_PROJECT_URL = "https://github.com/hagezi/dns-blocklists"
UPDATE_INTERVAL_SECONDS = 8 * 60 * 60
RETRY_INTERVAL_SECONDS = 30 * 60
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
MIN_VALID_ENTRIES = 10_000
MAX_VALID_ENTRIES = 250_000

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def privacy_dir(state_directory) -> Path:
    path = Path(state_directory) / "privacy"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_path(state_directory) -> Path:
    return privacy_dir(state_directory) / "hagezi-pro-mini.txt"


def metadata_path(state_directory) -> Path:
    return privacy_dir(state_directory) / "hagezi-pro-mini.meta.json"


def allowlist_path(state_directory) -> Path:
    return privacy_dir(state_directory) / "hagezi-allowlist.txt"


def normalize_domain(value: str) -> str:
    value = str(value or "").strip().lower().rstrip(".")
    if value.startswith("||"):
        value = value[2:]
    if value.startswith("*."):
        value = value[2:]
    value = value.rstrip("^")
    if not value or "/" in value or ":" in value or " " in value:
        return ""
    try:
        value = value.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return ""
    return value if _DOMAIN_RE.fullmatch(value) else ""


def parse_domain_list(text: str, *, min_entries=0, max_entries=MAX_VALID_ENTRIES):
    domains = set()
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!", "[")):
            continue
        # onlydomains output is one domain per line; tolerate trailing comments
        line = line.split("#", 1)[0].strip()
        domain = normalize_domain(line)
        if domain:
            domains.add(domain)
            if len(domains) > int(max_entries):
                raise ValueError("HaGeZi list exceeds the safety entry limit")
    if len(domains) < int(min_entries):
        raise ValueError(
            f"HaGeZi list validation failed: {len(domains)} valid domains"
        )
    return frozenset(domains)


def normalize_allowlist(values):
    if isinstance(values, str):
        values = re.split(r"[,;\n\r\t ]+", values)
    result = []
    seen = set()
    for value in list(values or []):
        domain = normalize_domain(value)
        if domain and domain not in seen:
            seen.add(domain)
            result.append(domain)
    return result[:2048]


def _atomic_write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _atomic_write_json(path: Path, payload):
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_allowlist(state_directory, values):
    domains = normalize_allowlist(values)
    _atomic_write_text(
        allowlist_path(state_directory),
        "".join(domain + "\n" for domain in domains),
    )
    return domains


def _read_metadata(state_directory):
    path = metadata_path(state_directory)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def status(state_directory):
    meta = _read_metadata(state_directory)
    path = list_path(state_directory)
    entries = int(meta.get("entries", 0) or 0)
    if entries <= 0 and path.is_file():
        try:
            entries = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        except Exception:
            entries = 0
    return {
        "name": HAGEZI_NAME,
        "source": HAGEZI_SOURCE_URL,
        "entries": entries,
        "last_checked": meta.get("last_checked"),
        "last_updated": meta.get("last_updated"),
        "last_error": str(meta.get("last_error") or ""),
        "available": bool(path.is_file() and entries > 0),
    }


def configure_runtime(state_directory, *, enabled: bool, allowlist=()):
    """Publish stable paths/settings for the separately packaged network helper."""
    list_file = list_path(state_directory)
    allow_file = allowlist_path(state_directory)
    write_allowlist(state_directory, allowlist)
    os.environ["TEKZITE_HAGEZI_ENABLED"] = "1" if enabled else "0"
    os.environ["TEKZITE_HAGEZI_LIST"] = str(list_file)
    os.environ["TEKZITE_HAGEZI_ALLOWLIST"] = str(allow_file)
    return {
        "enabled": bool(enabled),
        "list_path": str(list_file),
        "allowlist_path": str(allow_file),
    }


def _download(source_url, headers, timeout):
    request = urllib.request.Request(
        source_url,
        headers={
            "User-Agent": "Tekzite-Browser Privacy-Core/1",
            "Accept": "text/plain,*/*;q=0.1",
            **headers,
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=float(timeout)) as response:
        code = int(getattr(response, "status", 200) or 200)
        if code == 304:
            return code, b"", response.headers
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_DOWNLOAD_BYTES:
            raise ValueError("HaGeZi response is larger than the safety limit")
        data = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise ValueError("HaGeZi response is larger than the safety limit")
        return code, data, response.headers


def update_if_due(
    state_directory,
    *,
    enabled=True,
    auto_update=True,
    force=False,
    now=None,
    timeout=15.0,
    source_url=HAGEZI_SOURCE_URL,
    downloader=None,
):
    """Refresh the local list when due and preserve last-known-good on failure."""
    now = float(time.time() if now is None else now)
    meta = _read_metadata(state_directory)
    path = list_path(state_directory)

    if not enabled:
        return {**status(state_directory), "result": "disabled", "next_check_seconds": UPDATE_INTERVAL_SECONDS}
    if not auto_update and not force:
        return {**status(state_directory), "result": "manual", "next_check_seconds": UPDATE_INTERVAL_SECONDS}

    last_checked = float(meta.get("last_checked", 0) or 0)
    age = max(0.0, now - last_checked)
    due_interval = (
        RETRY_INTERVAL_SECONDS if meta.get("last_error") else UPDATE_INTERVAL_SECONDS
    )
    if not force and last_checked and age < due_interval:
        return {
            **status(state_directory),
            "result": "retry-wait" if meta.get("last_error") else "fresh",
            "next_check_seconds": max(60, int(due_interval - age)),
        }

    headers = {}
    if meta.get("etag"):
        headers["If-None-Match"] = str(meta["etag"])
    if meta.get("last_modified"):
        headers["If-Modified-Since"] = str(meta["last_modified"])

    try:
        fetch = downloader or _download
        code, payload, response_headers = fetch(source_url, headers, timeout)
        meta["last_checked"] = now
        meta["source"] = source_url

        if int(code) == 304:
            meta["last_error"] = ""
            _atomic_write_json(metadata_path(state_directory), meta)
            return {
                **status(state_directory),
                "result": "not-modified",
                "next_check_seconds": UPDATE_INTERVAL_SECONDS,
            }

        text = bytes(payload).decode("utf-8", "strict")
        domains = parse_domain_list(text, min_entries=MIN_VALID_ENTRIES)
        normalized = "".join(domain + "\n" for domain in sorted(domains))
        _atomic_write_text(path, normalized)
        meta.update(
            {
                "entries": len(domains),
                "last_updated": now,
                "last_error": "",
                "etag": str(response_headers.get("ETag") or ""),
                "last_modified": str(response_headers.get("Last-Modified") or ""),
            }
        )
        _atomic_write_json(metadata_path(state_directory), meta)
        return {
            **status(state_directory),
            "result": "updated",
            "next_check_seconds": UPDATE_INTERVAL_SECONDS,
        }
    except Exception as exc:
        meta.update(
            {
                "last_checked": now,
                "source": source_url,
                "last_error": f"{type(exc).__name__}: {exc}"[:500],
            }
        )
        try:
            _atomic_write_json(metadata_path(state_directory), meta)
        except Exception:
            pass
        # Crucially, never delete or truncate the existing list on update failure.
        return {
            **status(state_directory),
            "result": "error",
            "next_check_seconds": RETRY_INTERVAL_SECONDS,
        }
