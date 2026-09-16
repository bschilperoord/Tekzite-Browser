from __future__ import annotations

"""Performance wrapper for Tekzite's privacy-preserving loopback proxy.

The underlying proxy and its privacy behavior remain in tekzite_network.py.
This wrapper removes avoidable per-request filesystem work and accelerates
repeated hostname classification while keeping the same blocking semantics.
"""

import atexit
from functools import lru_cache
import json
import os
import threading
import time

import tekzite_network as core

STATS_FLUSH_SECONDS = 0.20

_policy_lock = threading.RLock()
_policy_mtime_ns = None
_policy_cached_enabled = None

_stats_timer = None
_stats_dirty = False


def _normalize_host(host: str) -> str:
    return (host or "").strip().rstrip(".").lower()


@lru_cache(maxsize=8192)
def _matches_ad_host(host: str) -> bool:
    return host in core.ADBLOCK_HOSTS or host.endswith(core.ADBLOCK_SUFFIXES)


@lru_cache(maxsize=8192)
def _matches_tracker_host(host: str) -> bool:
    return host in core.TRACKER_HOSTS or host.endswith(core.TRACKER_SUFFIXES)


@lru_cache(maxsize=4096)
def _matches_telemetry_host(host: str) -> bool:
    return host in core.TELEMETRY_HOSTS or host.endswith(core.TELEMETRY_SUFFIXES)


def _adblock_enabled() -> bool:
    """Preserve instant live policy updates while avoiding repeated JSON parsing."""
    global _policy_mtime_ns, _policy_cached_enabled

    with _policy_lock:
        default = bool(core.ADBLOCK_ENABLED)
        path = core.ADBLOCK_POLICY
        if not path:
            _policy_mtime_ns = None
            _policy_cached_enabled = default
            return default

        try:
            stat = os.stat(path)
            # Atomic policy writes can replace the file. Include size as part of
            # the change key so same-tick edits are still detected robustly.
            signature = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            _policy_mtime_ns = None
            _policy_cached_enabled = default
            return default

        # os.stat() is cheap; only open/parse JSON when the policy changed.
        if _policy_cached_enabled is not None and signature == _policy_mtime_ns:
            return bool(_policy_cached_enabled)

        enabled = default
        try:
            with open(path, "r", encoding="utf-8") as handle:
                policy = json.load(handle)
            value = policy.get("enabled") if isinstance(policy, dict) else None
            if isinstance(value, bool):
                enabled = value
        except (OSError, ValueError, TypeError, AttributeError):
            enabled = default

        _policy_mtime_ns = signature
        _policy_cached_enabled = bool(enabled)
        return bool(enabled)


def _is_ad_host(host: str) -> bool:
    if not _adblock_enabled():
        return False
    return _matches_ad_host(_normalize_host(host))


def _is_tracker_host(host: str) -> bool:
    if not core.TRACKER_BLOCKING:
        return False
    return _matches_tracker_host(_normalize_host(host))


def _is_browser_telemetry_host(host: str) -> bool:
    if core.ALLOW_BROWSER_TELEMETRY:
        return False
    return _matches_telemetry_host(_normalize_host(host))


def _flush_privacy_stats() -> None:
    global _stats_timer, _stats_dirty
    with core._PRIVACY_STATS_LOCK:
        _stats_timer = None
        if not _stats_dirty:
            return
        _stats_dirty = False
        core._write_privacy_stats()


def _privacy_stat(key: str) -> None:
    """Keep counters in RAM and coalesce disk writes during request bursts."""
    global _stats_timer, _stats_dirty
    with core._PRIVACY_STATS_LOCK:
        core._PRIVACY_STATS[key] = int(core._PRIVACY_STATS.get(key, 0) or 0) + 1
        _stats_dirty = True
        if _stats_timer is None:
            timer = threading.Timer(STATS_FLUSH_SECONDS, _flush_privacy_stats)
            timer.daemon = True
            _stats_timer = timer
            timer.start()


def _flush_at_exit() -> None:
    global _stats_timer
    timer = _stats_timer
    if timer is not None:
        try:
            timer.cancel()
        except Exception:
            pass
    _flush_privacy_stats()


def _reset_fast_caches_for_tests() -> None:
    """Internal test seam; harmless in production."""
    global _policy_mtime_ns, _policy_cached_enabled
    global _stats_timer, _stats_dirty

    with _policy_lock:
        _policy_mtime_ns = None
        _policy_cached_enabled = None
    _matches_ad_host.cache_clear()
    _matches_tracker_host.cache_clear()
    _matches_telemetry_host.cache_clear()

    with core._PRIVACY_STATS_LOCK:
        if _stats_timer is not None:
            try:
                _stats_timer.cancel()
            except Exception:
                pass
        _stats_timer = None
        _stats_dirty = False


def install() -> None:
    # 128 KiB reduces relay syscall overhead while keeping interactive latency
    # low and preserving the existing backpressure design.
    core.BUF = max(int(core.BUF), 128 * 1024)

    # Replace only hot-path helpers. The proxy protocol, TLS tunnel behavior,
    # privacy lists, request parsing and connection lifecycle stay unchanged.
    core._is_ad_host = _is_ad_host
    core._is_tracker_host = _is_tracker_host
    core._is_browser_telemetry_host = _is_browser_telemetry_host
    core._privacy_stat = _privacy_stat


install()
atexit.register(_flush_at_exit)


def main(argv=None) -> int:
    return int(core.main(argv) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
