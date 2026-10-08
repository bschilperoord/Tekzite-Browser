from pathlib import Path
import time

import main
import engine.net as net


def test_external_auth_recognizes_common_oauth_providers():
    assert main.BrowserApp._is_external_auth_url(
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=x&redirect_uri=https%3A%2F%2Fexample.com%2Fcallback",
        "https://example.com/"
    )
    assert main.BrowserApp._is_external_auth_url(
        "https://github.com/login/oauth/authorize?client_id=x&redirect_uri=https%3A%2F%2Fexample.com%2Fcallback",
        "https://example.com/"
    )
    assert main.BrowserApp._is_external_auth_url(
        "https://tenant.eu.auth0.com/authorize?client_id=x&redirect_uri=https%3A%2F%2Fexample.com%2Fcallback&response_type=code",
        "https://example.com/"
    )


def test_first_party_login_is_not_forced_out_to_standalone_chromium():
    assert not main.BrowserApp._is_external_auth_url(
        "https://example.com/login",
        "https://example.com/"
    )


def test_generic_handoff_prefers_explicit_oauth_redirect_uri():
    launch, return_url = main.BrowserApp._external_auth_handoff_urls(
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=x&redirect_uri=https%3A%2F%2Fexample.com%2Foauth%2Fcallback",
        "https://example.com/dashboard",
    )
    assert launch.startswith("https://login.microsoftonline.com/")
    assert return_url == "https://example.com/oauth/callback"


def test_outlook_handoff_uses_outlook_redirect_not_microsoft_marketing_page():
    source = (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
        "client_id=9199bf20-a13f-4107-85dc-02114787ef48&"
        "redirect_uri=https%3A%2F%2Foutlook.live.com%2Fmail%2F&"
        "response_type=code&scope=openid%20profile%20offline_access"
    )
    launch, return_url = main.BrowserApp._external_auth_handoff_urls(
        source,
        "https://www.microsoft.com/nl-nl/microsoft-365/outlook/email-and-calendar-software-microsoft-outlook",
    )
    assert launch.startswith("https://login.microsoftonline.com/")
    assert return_url == "https://outlook.live.com/mail/"


def test_github_oauth_prefers_registered_callback_over_previous_page():
    source = (
        "https://github.com/login/oauth/authorize?"
        "client_id=abc&redirect_uri=https%3A%2F%2Fapp.example.com%2Fauth%2Fgithub%2Fcallback"
    )
    _launch, return_url = main.BrowserApp._external_auth_handoff_urls(
        source, "https://app.example.com/settings"
    )
    assert return_url == "https://app.example.com/auth/github/callback"


def test_auth0_oauth_prefers_callback_over_previous_page():
    source = (
        "https://tenant.eu.auth0.com/authorize?"
        "client_id=abc&response_type=code&"
        "redirect_uri=https%3A%2F%2Fportal.example.com%2Fcallback"
    )
    _launch, return_url = main.BrowserApp._external_auth_handoff_urls(
        source, "https://portal.example.com/"
    )
    assert return_url == "https://portal.example.com/callback"


def test_okta_oauth_prefers_callback_over_previous_page():
    source = (
        "https://tenant.okta.com/oauth2/default/v1/authorize?"
        "client_id=abc&response_type=code&"
        "redirect_uri=https%3A%2F%2Fapp.example.com%2Foidc%2Fcallback"
    )
    _launch, return_url = main.BrowserApp._external_auth_handoff_urls(
        source, "https://app.example.com/home"
    )
    assert return_url == "https://app.example.com/oidc/callback"


def test_generic_return_detection_accepts_cross_host_login_callback(monkeypatch):
    handle = {
        "profile": "profile",
        "url": "https://id.example-idp.test/oauth2/authorize",
        "return_url": "https://app.example.test/login/callback",
        "history_visit_baseline": ("https://app.example.test/", 100, 1),
        "history_return_visit_baseline": ("https://app.example.test/", 100, 1),
        "history_return_launch_visit": ("https://app.example.test/", 100, 1),
    }
    monkeypatch.setattr(
        net, "_snapshot_chromium_latest_visit",
        lambda _profile, _target="": ("https://app.example.test/login/callback?code=ok", 200, 2),
    )
    assert net._auth_navigation_has_returned(handle)
    assert handle["auth_return_url_seen"].startswith("https://app.example.test/login/callback")


def test_generic_site_cookie_change_alone_cannot_complete_auth(monkeypatch):
    baseline = {("example.test", "session"): "old"}
    current = {("example.test", "session"): "new"}
    handle = {
        "profile": "profile",
        "url": "https://identity.vendor.test/oauth2/authorize",
        "return_url": "https://example.test/",
        "auth_cookie_baseline": baseline,
        "google_auth_success_signal": ("site-cookie", tuple(sorted(current.items()))),
        "google_auth_cookie_change_at": time.monotonic() - 2.0,
    }
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: False)
    monkeypatch.setattr(net, "_snapshot_auth_cookie_state", lambda _profile, _return: dict(current))
    assert not net.standalone_google_auth_succeeded(handle, 1.0)
    assert not handle.get("auth_provider_independent_success")
