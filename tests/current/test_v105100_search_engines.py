import inspect

import main


CUSTOMIZE_SOURCE = inspect.getsource(main.BrowserApp._show_customize_browser)


def test_builtin_search_engine_presets_are_available():
    expected = {
        "Startpage",
        "DuckDuckGo",
        "Google",
        "Bing",
        "Brave Search",
        "Ecosia",
        "Qwant",
    }
    assert expected.issubset(main.SEARCH_ENGINE_PRESETS)
    assert all("{query}" in value for value in main.SEARCH_ENGINE_PRESETS.values())


def test_search_engine_name_is_derived_from_saved_template():
    for name, template in main.SEARCH_ENGINE_PRESETS.items():
        assert main._search_engine_name_for_template(template) == name
    assert main._search_engine_name_for_template(
        "http://127.0.0.1:8080/search?q={query}"
    ) == main.CUSTOM_SEARCH_ENGINE


def test_customize_browser_has_search_engine_picker_and_custom_template():
    assert '"Search engine"' in CUSTOMIZE_SOURCE
    assert "values=list(SEARCH_ENGINE_PRESETS) + [CUSTOM_SEARCH_ENGINE]" in CUSTOMIZE_SOURCE
    assert '"Search URL template"' in CUSTOMIZE_SOURCE
    assert "search_var.trace_add" in CUSTOMIZE_SOURCE
    assert "select_search_engine" in CUSTOMIZE_SOURCE


def test_selecting_builtin_engine_drives_the_omnibox_template():
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.preferences = {
        **main.DEFAULT_PREFERENCES,
        "search_url_template": main.SEARCH_ENGINE_PRESETS["DuckDuckGo"],
    }
    assert app._search_url("two words") == "https://duckduckgo.com/?q=two+words"


def test_custom_search_engine_remains_supported():
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.preferences = {
        **main.DEFAULT_PREFERENCES,
        "search_url_template": "http://127.0.0.1:8080/search?q={query}",
    }
    assert app._search_url("local search") == (
        "http://127.0.0.1:8080/search?q=local+search"
    )
