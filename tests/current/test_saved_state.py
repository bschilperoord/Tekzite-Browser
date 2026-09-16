import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import main
from browser_state import load_bookmarks, load_session, session_snapshot, write_json


class SavedStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_bookmark_roundtrip_and_filtering(self):
        path = self.folder / 'bookmarks.json'
        write_json(path, [{'title': 'Muziek 🎵', 'url': 'https://example.com/#beat'},
                          {'url': 'https://example.com/#beat'}, {'url': 'javascript:alert(1)'}, None])
        self.assertEqual(load_bookmarks(path), [{'title': 'Muziek 🎵', 'url': 'https://example.com/#beat'}])

    def test_failed_replace_keeps_previous_file(self):
        path = self.folder / 'state.json'
        write_json(path, {'old': True})
        with patch('browser_state.os.replace', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                write_json(path, {'new': True})
        self.assertEqual(path.read_text().strip(), '{\n  "old": true\n}')
        self.assertEqual(len(list(self.folder.iterdir())), 1)

    def test_session_keeps_order_duplicates_blank_and_selection(self):
        tabs = [{'id': 2, 'url': 'https://example.com/'}, {'id': 3, 'url': ''},
                {'id': 4, 'url': 'https://example.com/'}]
        snapshot = session_snapshot(tabs, 4)
        path = self.folder / 'session.json'
        write_json(path, snapshot)
        self.assertEqual(load_session(path), snapshot)
        self.assertEqual(snapshot['active'], 2)
        self.assertEqual(len(snapshot['tabs']), 3)

    def test_corrupt_state_falls_back(self):
        path = self.folder / 'state.json'
        for text in ['broken', 'null', '[]', '{"tabs": 42}']:
            path.write_text(text)
            self.assertEqual(load_session(path), {'tabs': [], 'active': 0})
        path.write_text('{"tabs":[null,{"url":"javascript:x"},{"url":"https://example.com"}],"active":2}')
        self.assertEqual(load_session(path)['active'], 0)

    def app(self):
        app = main.BrowserApp.__new__(main.BrowserApp)
        app._state_directory = self.folder
        app.preferences = {'restore_tabs': True}
        app.tabs = [{'id': 0, 'url': ''}]
        app.active_tab_id = 0
        app.url_var = Mock()
        app._refresh_tab_strip = Mock()
        app.navigate_to = Mock()
        app._focus_address = Mock()
        def new_tab(**kwargs):
            tab = {'id': len(app.tabs), 'url': ''}
            app.tabs.append(tab)
            return tab
        app._new_tab = new_tab
        return app

    def test_restore_loads_selected_only(self):
        app = self.app()
        write_json(self.folder / 'session.json', {'tabs': [{'url': 'https://one.test'}, {'url': 'https://two.test'}], 'active': 1})
        fallback = Mock()
        app._restore_startup_tabs(fallback)
        fallback.assert_not_called()
        self.assertEqual(app.active_tab_id, 1)
        self.assertTrue(app.tabs[0]['restore_pending'])
        app.navigate_to.assert_called_once_with('https://two.test', reuse_existing=False)

    def test_disabled_restore_clears_saved_session(self):
        app = self.app()
        path = self.folder / 'session.json'
        write_json(path, {'tabs': [{'url': 'https://example.com'}]})
        app.preferences['restore_tabs'] = False
        fallback = Mock()
        app._restore_startup_tabs(fallback)
        fallback.assert_called_once()
        app._save_session()
        self.assertFalse(path.exists())

    def test_pending_tab_loads_when_selected(self):
        app = self.app()
        app.tabs.append({'id': 1, 'url': 'https://two.test', 'restore_pending': True})
        app._capture_active_tab_state = Mock()
        app._navigation_generation = 0
        app._tab_switch_serial = 0
        app._tab_switch_pending_id = None
        app.update_history_buttons = Mock()
        app._show_native_canvas = Mock()
        app.canvas = Mock()
        app.status_var = Mock()
        app._switch_tab(1)
        app.navigate_to.assert_called_once_with('https://two.test', reuse_existing=False)
        self.assertNotIn('restore_pending', app.tabs[1])

    def test_failed_bookmark_write_does_not_change_memory(self):
        app = self.app()
        app.bookmarks = []
        app.root = Mock()
        with patch('main.write_json', side_effect=OSError('locked')), patch('main.messagebox.showerror'):
            self.assertFalse(app._store_bookmarks([{'url': 'https://example.com'}]))
        self.assertEqual(app.bookmarks, [])

    def test_corrupt_primary_recovers_previous_valid_generation(self):
        path = self.folder / 'state.json'
        write_json(path, {'generation': 1})
        write_json(path, {'generation': 2})
        path.write_text('{broken', encoding='utf-8')
        from browser_state import read_json
        self.assertEqual(read_json(path, {}), {'generation': 1})

    def test_missing_primary_does_not_resurrect_backup(self):
        path = self.folder / 'state.json'
        write_json(path, {'generation': 1})
        write_json(path, {'generation': 2})
        self.assertTrue(path.with_name(path.name + '.bak').exists())
        path.unlink()
        from browser_state import read_json
        self.assertEqual(read_json(path, {'fresh': True}), {'fresh': True})
