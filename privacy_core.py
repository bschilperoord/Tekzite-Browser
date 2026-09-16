"""Tekzite privacy primitives that do not depend on UI or Chromium internals."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import ipaddress

# Deliberately narrow to known marketing/click identifiers. Avoid generic keys
# such as ``ref`` or ``source`` because those can be functional site state.
TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "dclid", "msclkid", "twclid", "ttclid", "li_fat_id",
    "igshid", "mc_cid", "mc_eid", "mkt_tok", "vero_conv", "vero_id",
    "oly_anon_id", "oly_enc_id", "rb_clickid", "s_cid", "wickedid",
    "_hsenc", "_hsmi", "ga_source", "ga_medium", "ga_term", "ga_content",
    "ga_campaign", "yclid", "gbraid", "wbraid", "epik", "irclickid",
    "ref_src", "ref_url", "spm", "scm", "campaign_id", "ad_id", "adset_id",
}
TRACKING_QUERY_PREFIXES = ("utm_",)


def strip_tracking_parameters(url: str):
    """Return ``(clean_url, removed_count)`` for an HTTP(S) URL.

    The function is intentionally deterministic and conservative. It never
    rewrites non-web schemes and never drops unknown query keys.
    """
    text = str(url or "").strip()
    try:
        parts = urlsplit(text)
    except Exception:
        return text, 0
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc or not parts.query:
        return text, 0

    kept = []
    removed = 0
    try:
        pairs = parse_qsl(parts.query, keep_blank_values=True)
    except Exception:
        return text, 0
    for key, value in pairs:
        lowered = key.casefold()
        if lowered in TRACKING_QUERY_KEYS or any(lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            removed += 1
            continue
        kept.append((key, value))
    if not removed:
        return text, 0
    query = urlencode(kept, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment)), removed


def upgrade_to_https(url: str):
    """Upgrade an ordinary HTTP URL to HTTPS without touching other schemes."""
    text = str(url or "").strip()
    try:
        parts = urlsplit(text)
    except Exception:
        return text
    if parts.scheme.lower() != "http" or not parts.netloc:
        return text
    # Loopback is intentionally left alone; local developer/device endpoints
    # may not offer TLS. Tekzite's strict loopback policy is a separate guard.
    host = (parts.hostname or "").casefold()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith((".local", ".lan")):
        return text
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return text
    except ValueError:
        pass
    return urlunsplit(("https", parts.netloc, parts.path, parts.query, parts.fragment))
