import json
from pathlib import Path

import hagezi_privacy
import tekzite_network


def _domain_blob(count=20):
    return "".join(f"ad{i}.tracker-example.test\n" for i in range(count))


def test_hagezi_parser_normalizes_and_deduplicates():
    parsed = hagezi_privacy.parse_domain_list(
        """
        # comment
        Example.COM.
        *.ads.example.net
        ||pixel.example.org^
        example.com
        invalid host
        """,
        min_entries=3,
    )
    assert parsed == frozenset({
        "example.com",
        "ads.example.net",
        "pixel.example.org",
    })


def test_hagezi_update_is_atomic_and_last_known_good_survives_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(hagezi_privacy, "MIN_VALID_ENTRIES", 3)

    headers = {"ETag": '"abc"', "Last-Modified": "Wed, 30 Sep 2026 10:00:00 GMT"}

    def good_download(_url, _headers, _timeout):
        return 200, _domain_blob(4).encode("utf-8"), headers

    first = hagezi_privacy.update_if_due(
        tmp_path,
        enabled=True,
        auto_update=True,
        force=True,
        now=1000,
        downloader=good_download,
    )
    assert first["result"] == "updated"
    assert first["entries"] == 4
    original = hagezi_privacy.list_path(tmp_path).read_text(encoding="utf-8")

    def broken_download(_url, _headers, _timeout):
        raise OSError("offline")

    failed = hagezi_privacy.update_if_due(
        tmp_path,
        enabled=True,
        auto_update=True,
        force=True,
        now=2000,
        downloader=broken_download,
    )
    assert failed["result"] == "error"
    assert failed["available"] is True
    assert hagezi_privacy.list_path(tmp_path).read_text(encoding="utf-8") == original


def test_hagezi_failed_update_retries_on_short_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(hagezi_privacy, "MIN_VALID_ENTRIES", 3)

    def broken(_url, _headers, _timeout):
        raise OSError("offline")

    first = hagezi_privacy.update_if_due(
        tmp_path, force=True, now=1000, downloader=broken
    )
    assert first["result"] == "error"
    assert first["next_check_seconds"] == hagezi_privacy.RETRY_INTERVAL_SECONDS

    waiting = hagezi_privacy.update_if_due(
        tmp_path, now=1000 + 60, downloader=broken
    )
    assert waiting["result"] == "retry-wait"
    assert waiting["next_check_seconds"] < hagezi_privacy.RETRY_INTERVAL_SECONDS

    calls = {"count": 0}

    def recovered(_url, _headers, _timeout):
        calls["count"] += 1
        return 200, _domain_blob(3).encode(), {}

    result = hagezi_privacy.update_if_due(
        tmp_path,
        now=1000 + hagezi_privacy.RETRY_INTERVAL_SECONDS + 1,
        downloader=recovered,
    )
    assert calls["count"] == 1
    assert result["result"] == "updated"


def test_hagezi_update_falls_back_to_next_official_source(tmp_path, monkeypatch):
    monkeypatch.setattr(hagezi_privacy, "MIN_VALID_ENTRIES", 3)
    calls = []

    def downloader(url, _headers, _timeout):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("primary mirror unavailable")
        return 200, _domain_blob(3).encode(), {"ETag": '"fallback"'}

    result = hagezi_privacy.update_if_due(
        tmp_path,
        force=True,
        now=1500,
        downloader=downloader,
    )
    assert result["result"] == "updated"
    assert result["entries"] == 3
    assert len(calls) == 2
    assert calls[0] == hagezi_privacy.HAGEZI_SOURCE_URLS[0]
    assert calls[1] == hagezi_privacy.HAGEZI_SOURCE_URLS[1]
    assert result["source"] == hagezi_privacy.HAGEZI_SOURCE_URLS[1]


def test_hagezi_conditional_update_uses_etag(tmp_path, monkeypatch):
    monkeypatch.setattr(hagezi_privacy, "MIN_VALID_ENTRIES", 3)

    def initial(_url, _headers, _timeout):
        return 200, _domain_blob(3).encode(), {"ETag": '"etag-1"'}

    hagezi_privacy.update_if_due(
        tmp_path, force=True, now=1000, downloader=initial
    )

    seen = {}

    def not_modified(_url, headers, _timeout):
        seen.update(headers)
        return 304, b"", {}

    result = hagezi_privacy.update_if_due(
        tmp_path, force=True, now=2000, downloader=not_modified
    )
    assert result["result"] == "not-modified"
    assert seen["If-None-Match"] == '"etag-1"'


def test_hagezi_proxy_matches_parent_domains_and_allowlist(tmp_path, monkeypatch):
    blocked = tmp_path / "hagezi.txt"
    allowed = tmp_path / "allow.txt"
    blocked.write_text("tracker.example.com\n", encoding="utf-8")
    allowed.write_text("safe.tracker.example.com\n", encoding="utf-8")

    monkeypatch.setattr(tekzite_network, "HAGEZI_ENABLED", True)
    monkeypatch.setattr(tekzite_network, "HAGEZI_LIST_PATH", str(blocked))
    monkeypatch.setattr(tekzite_network, "HAGEZI_ALLOWLIST_PATH", str(allowed))
    monkeypatch.setattr(tekzite_network, "_HAGEZI_LIST_SIGNATURE", None)
    monkeypatch.setattr(tekzite_network, "_HAGEZI_ALLOWLIST_SIGNATURE", None)
    monkeypatch.setattr(tekzite_network, "_HAGEZI_DOMAINS", frozenset())
    monkeypatch.setattr(tekzite_network, "_HAGEZI_ALLOWLIST", frozenset())

    assert tekzite_network._is_hagezi_host("pixel.tracker.example.com")
    assert not tekzite_network._is_hagezi_host("safe.tracker.example.com")
    assert not tekzite_network._is_hagezi_host("cdn.example.com")


def test_hagezi_runtime_writes_clean_allowlist_and_environment(tmp_path, monkeypatch):
    for key in ("TEKZITE_HAGEZI_ENABLED", "TEKZITE_HAGEZI_LIST", "TEKZITE_HAGEZI_ALLOWLIST"):
        monkeypatch.delenv(key, raising=False)

    runtime = hagezi_privacy.configure_runtime(
        tmp_path,
        enabled=True,
        allowlist=["Example.com", "*.safe.example.net", "bad value"],
    )
    assert runtime["enabled"] is True
    assert Path(runtime["allowlist_path"]).read_text(encoding="utf-8").splitlines() == [
        "example.com",
        "safe.example.net",
    ]


def test_extension_counter_permission_and_api_are_present():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "chromium_zoom_extension" / "manifest.json").read_text(encoding="utf-8"))
    background = (root / "chromium_zoom_extension" / "background.js").read_text(encoding="utf-8")
    features = (root / "chromium_zoom_extension" / "features.js").read_text(encoding="utf-8")
    assert "declarativeNetRequestFeedback" in manifest["permissions"]
    assert "onRuleMatchedDebug" in background
    assert "tekziteGetPrivacyCounters" in background
    assert 'action === "privacyStats"' in features


def test_privacy_shield_merges_extension_proxy_and_hagezi_counters():
    root = Path(__file__).resolve().parents[2]
    browser_features = (root / "browser_features.py").read_text(encoding="utf-8")
    main = (root / "main.py").read_text(encoding="utf-8")
    assert "def _combined_privacy_stats" in browser_features
    assert "_refresh_privacy_extension_stats_async" in browser_features
    assert "HaGeZi blocked" in main
    assert "_combined_privacy_stats()" in main
    assert "callback=finished" in main
    assert "hagezi_last_error:" in main
    assert "hagezi_updating:" in main



def test_live_helper_privacy_stats_endpoint_reads_ram(monkeypatch):
    token = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(tekzite_network, "INSTANCE_TOKEN", token)
    monkeypatch.setattr(
        tekzite_network,
        "_PRIVACY_STATS",
        {
            "started_at": 123.0,
            "telemetry_blocked": 2,
            "trackers_blocked": 3,
            "ads_blocked": 4,
            "hagezi_blocked": 5,
            "https_upgrades": 6,
        },
    )
    monkeypatch.setattr(tekzite_network, "_HAGEZI_DOMAINS", frozenset({"one.test", "two.test"}))
    monkeypatch.setattr(tekzite_network, "_HAGEZI_ALLOWLIST", frozenset({"safe.test"}))
    monkeypatch.setattr(tekzite_network, "_refresh_hagezi_sets", lambda: None)

    class Client:
        def __init__(self):
            self.data = b""
        def sendall(self, value):
            self.data += value

    client = Client()
    handled = tekzite_network._serve_internal_privacy_stats(
        client,
        "GET",
        "http://tekzite.internal/__privacy_stats",
        [("X-Tekzite-Instance-Token", token)],
    )
    assert handled is True
    head, body = client.data.split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 200")
    payload = json.loads(body.decode("utf-8"))
    assert payload["ads_blocked"] == 4
    assert payload["trackers_blocked"] == 3
    assert payload["hagezi_blocked"] == 5
    assert payload["hagezi_domains_loaded"] == 2
    assert payload["hagezi_allowlist_loaded"] == 1


def test_extension_privacy_stats_heals_from_chromium_matched_rules():
    root = Path(__file__).resolve().parents[2]
    features = (root / "chromium_zoom_extension" / "features.js").read_text(encoding="utf-8")
    assert "getMatchedRules()" in features
    assert "rulesMatchedInfo" in features
    assert 'ruleset === "ads"' in features
    assert 'ruleset === "trackers"' in features
    assert "Math.max" in features


def test_privacy_shield_exposes_live_counter_source_and_hagezi_runtime():
    root = Path(__file__).resolve().parents[2]
    main = (root / "main.py").read_text(encoding="utf-8")
    net = (root / "engine" / "net.py").read_text(encoding="utf-8")
    assert "Counter source" in main
    assert "HaGeZi runtime" in main
    assert "Total blocked" in main
    assert "__privacy_stats" in net
    assert '"source": "live-helper"' in net
