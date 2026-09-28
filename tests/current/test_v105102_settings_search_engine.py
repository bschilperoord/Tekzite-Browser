import inspect

import main


SETTINGS_SOURCE = inspect.getsource(main.BrowserApp.show_preferences)


def test_settings_exposes_search_engine_picker():
    assert 'section("Search engine")' in SETTINGS_SOURCE
    assert "list(SEARCH_ENGINE_PRESETS) + [CUSTOM_SEARCH_ENGINE]" in SETTINGS_SOURCE
    assert '"Custom search URL template"' in SETTINGS_SOURCE


def test_settings_picker_and_template_stay_in_sync():
    assert "def select_settings_search_engine" in SETTINGS_SOURCE
    assert "def sync_settings_search_engine" in SETTINGS_SOURCE
    assert 'search_template.trace_add("write", sync_settings_search_engine)' in SETTINGS_SOURCE
    assert '"<<ComboboxSelected>>", select_settings_search_engine' in SETTINGS_SOURCE


def test_settings_saves_the_same_search_preference_as_customize():
    assert '"search_url_template": selected_search_template' in SETTINGS_SOURCE
    assert '"Search URL template must contain {query}."' in SETTINGS_SOURCE


def test_all_settings_search_presets_have_query_placeholder():
    assert main.SEARCH_ENGINE_PRESETS
    assert all("{query}" in value for value in main.SEARCH_ENGINE_PRESETS.values())
