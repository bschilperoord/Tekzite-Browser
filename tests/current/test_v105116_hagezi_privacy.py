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
