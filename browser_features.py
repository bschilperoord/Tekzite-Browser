"""Browser feature dialogs and local session/history housekeeping."""
import loopback_policy
import json
import os
import time
import re
import hashlib
import urllib.request
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from urllib.parse import urlsplit
from pathlib import Path
from browser_state import read_json, write_json, valid_url, session_snapshot
from engine import features


def site_host(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return ''
        return parsed.hostname.encode('idna').decode('ascii').lower().rstrip('.')
    except (ValueError, UnicodeError):
        return ''


def record_visit(rows, url, title, now=None):
    url = str(url or '')[:32768]
    title = str(title or url)[:1024]
    if not valid_url(url):
        return rows
    return [{'url': url, 'title': title, 'visited': now or time.time()}] + [r for r in rows if r.get('url') != url][:4999]


def omnibox_suggestions(query, *, visits=None, bookmarks=None, tabs=None, recent_inputs=None, limit=6):
    """Return ranked, local-only omnibox suggestions.

    The matcher intentionally performs no network I/O.  It combines persistent
    Tekzite history when available with bookmarks, open tabs, per-tab in-memory
    history and raw searches/addresses entered during this browser session.
    """
    query = str(query or '').strip()
    if not query:
        return []
    needle = query.casefold()
    try:
        limit = max(1, min(12, int(limit)))
    except Exception:
        limit = 6

    ranked = []
    seen = set()
    serial = 0

    def searchable_parts(value, title):
        value = str(value or '').strip()
        title = str(title or '').strip()
        parts = [title, value]
        try:
            parsed = urlsplit(value)
            host = str(parsed.hostname or '')
            if host:
                parts.extend([host, host[4:] if host.lower().startswith('www.') else host])
            if parsed.netloc:
                tail = parsed.netloc + (parsed.path or '')
                parts.append(tail)
        except Exception:
            pass
        return [part.casefold() for part in parts if part]

    def match_score(value, title):
        best = None
        for part in searchable_parts(value, title):
            if part == needle:
                score = 0
            elif part.startswith(needle):
                score = 8
            else:
                at = part.find(needle)
                if at < 0:
                    continue
                score = 32 + min(24, at)
            best = score if best is None else min(best, score)
        return best

    def add(kind, value, title='', source_rank=20, visited=0.0, secondary=''):
        nonlocal serial
        value = str(value or '').strip()[:32768]
        title = str(title or value).strip()[:1024]
        if not value:
            return
        score = match_score(value, title)
        if score is None:
            return
        key = value.casefold()
        if key in seen:
            return
        seen.add(key)
        serial += 1
        ranked.append((
            score + int(source_rank),
            -float(visited or 0.0),
            serial,
            {
                'kind': str(kind),
                'title': title or value,
                'value': value,
                'secondary': str(secondary or value),
            },
        ))

    # Raw inputs are useful for repeated searches even in Privacy Lockdown,
    # where browsing history is deliberately not persisted.
    for index, value in enumerate(list(recent_inputs or [])[:100]):
        add('recent', value, value, 2 + min(index, 18), secondary='Recent input')

    for item in list(bookmarks or []):
        if isinstance(item, dict):
            add('bookmark', item.get('url'), item.get('title'), 0, secondary=item.get('url'))

    for tab in list(tabs or []):
        if not isinstance(tab, dict):
            continue
        tab_url = tab.get('url')
        add('tab', tab_url, tab.get('title') or tab_url, 4, secondary=tab_url)
        for offset, value in enumerate(reversed(list(tab.get('history') or [])[-40:])):
            add('history', value, value, 11 + min(offset, 16), secondary='This session')

    for item in list(visits or []):
        if isinstance(item, dict):
            add('history', item.get('url'), item.get('title'), 8, item.get('visited', 0), item.get('url'))

    ranked.sort(key=lambda row: (row[0], row[1], row[2]))
    # Always reserve the last slot for the user's literal query. That keeps the
    # omnibox predictable: suggestions never make the search action disappear.
    result = [row[3] for row in ranked[:max(0, limit - 1)]]
    result.append({
        'kind': 'search',
        'title': f'Search for “{query[:160]}”',
        'value': query,
        'secondary': 'Search',
    })
    return result[:limit]


def download_progress(item):
    received = max(0, item.get('bytesReceived', 0))
    total = item.get('totalBytes', 0)
    if total > 0:
        return f'{min(100, received * 100 / total):.0f}% ({received / 1048576:.1f} / {total / 1048576:.1f} MB)'
    return f'{received / 1048576:.1f} MB (size unknown)'


class BrowserFeatures:
    def _init_features(self):
        rows = [] if (getattr(self, '_private_mode', False) or self.preferences.get('privacy_lockdown', False)) else read_json(self._state_directory / 'history.json', [])
        self.visits = [r for r in rows if isinstance(r, dict) and valid_url(r.get('url')) and isinstance(r.get('visited'), (int, float))][:5000] if isinstance(rows, list) else []
        self._history_dirty = False
        self._session_encoded = None
        self._checkpoint_job = None
        self._network_health_after_id = None
        self._network_health_future = None
        self._network_health_failures = 0
        self._closing = False
        self._configure_feature_preferences()

    def _start_optional_services(self, session):
        if self._closing or session is not features.net._EDGE_SESSION:
            return
        if session.get('feature_services_scheduled'):
            return
        session['feature_services_scheduled'] = True
        # This callback runs after the first page was shown, never during HWND selection.
        self._executor.submit(features.initialize_optional, session)

    def _configure_feature_preferences(self):
        features.set_config(
            self.preferences.get('adblock_enabled', True),
            self.preferences.get('adblock_sites', []),
            tracker_blocking=self.preferences.get('tracker_blocking_enabled', True),
            strip_referrer=self.preferences.get('strip_referrer', True),
            https_first=self.preferences.get('https_first', True),
        )

    def _feature_startup(self, action):
        action()
        self._apply_quiet_mode()
        if not getattr(self, '_private_mode', False) and not self.preferences.get('privacy_lockdown', False):
            self._checkpoint_job = self.root.after(2000, self._checkpoint_features)
        self._schedule_network_health_watch(3000)
        scheduler = getattr(self, '_schedule_sleeping_tabs', None)
        if callable(scheduler):
            scheduler(15000)

    def _schedule_network_health_watch(self, delay_ms=4000):
        if self._closing:
            return
        try:
            self._network_health_after_id = self.root.after(int(delay_ms), self._network_health_tick)
        except Exception:
            self._network_health_after_id = None

    def _network_health_tick(self):
        """Keep Chromium's fixed local proxy alive without touching the UI thread."""
        self._network_health_after_id = None
        if self._closing:
            return
        # Do not start the proxy just because a blank browser window is open.
        # Once Chromium exists, however, its --proxy-server URL is fixed and the
        # helper must be recovered on the same port if it ever crashes.
        if features.net._EDGE_SESSION is None:
            self._schedule_network_health_watch(4000)
            return

        future = self._network_health_future
        if future is None:
            try:
                self._network_health_future = self._executor.submit(features.net.ensure_network_engine)
            except Exception:
                self._network_health_future = None
            self._schedule_network_health_watch(1200)
            return

        if not future.done():
            self._schedule_network_health_watch(1200)
            return

        self._network_health_future = None
        try:
            state = future.result() or {}
            self._network_health_failures = 0
            if state.get('recovered_same_port') and not state.get('_recovery_reported'):
                state['_recovery_reported'] = True
                self.status_var.set('Network engine recovered automatically')
        except Exception as exc:
            self._network_health_failures += 1
            writer = getattr(self, '_write_stability_log', None)
            if callable(writer):
                writer('Network engine recovery error', f'{type(exc).__name__}: {exc}')
            if self._network_health_failures == 1:
                self.status_var.set('Network engine recovery pending…')

        self._schedule_network_health_watch(2500 if self._network_health_failures else 4000)

    def _checkpoint_features(self):
        if self._closing or getattr(self, '_private_mode', False) or self.preferences.get('privacy_lockdown', False):
            return
        try:
            if self.preferences.get('restore_tabs', True):
                snapshot = session_snapshot(self.tabs, self.active_tab_id)
                snapshot['clean_exit'] = False
                encoded = json.dumps(snapshot, sort_keys=True)
                if encoded != self._session_encoded:
                    write_json(self._state_directory / 'session.json', snapshot)
                    self._session_encoded = encoded
            else:
                (self._state_directory / 'session.json').unlink(missing_ok=True)
            if self._history_dirty:
                write_json(self._state_directory / 'history.json', self.visits)
                self._history_dirty = False
        except OSError as exc:
            self.status_var.set(f'Could not save browser state: {exc}')
        self._checkpoint_job = self.root.after(2000, self._checkpoint_features)

    def _record_page_visit(self, tab):
        if getattr(self, '_private_mode', False) or self.preferences.get('privacy_lockdown', False):
            return
        url = tab.get('url', '')
        if tab.get('ready_state') not in ('interactive', 'complete') or not valid_url(url):
            return
        previous = tab.get('_history_recorded')
        title = tab.get('title') or url
        self._apply_permissions_for_tab(tab)
        if previous != url:
            self.visits = record_visit(self.visits, url, title)
            tab['_history_recorded'] = url
            self._history_dirty = True
        else:
            for row in self.visits:
                if row['url'] == url and row.get('title') != title:
                    row['title'] = title
                    self._history_dirty = True
                    break

    def _toggle_pin(self, tab_id):
        tab = next((t for t in self.tabs if t['id'] == tab_id), None)
        if tab is None:
            return
        tab['pinned'] = not tab.get('pinned', False)
        self.tabs.sort(key=lambda t: not t.get('pinned', False))
        self._refresh_tab_strip()

    def _toggle_quiet_mode(self):
        self.preferences['quiet_mode'] = not self.preferences.get('quiet_mode', False)
        try:
            self._persist_preferences()
        except OSError as exc:
            self.status_var.set(f'Quiet mode changed for this session; save failed: {exc}')
        self._apply_quiet_mode()

    def _apply_quiet_mode(self):
        quiet = self.preferences.get('quiet_mode', False)
        self._ui_animation_jobs.clear()
        try:
            self.debug_group.pack_forget()
        except Exception:
            pass
        repack = getattr(self, '_repack_browser_chrome', None)
        fully_built = getattr(self, 'content_frame', None) is not None and getattr(self, 'app_bar', None) is not None
        if callable(repack) and fully_built:
            repack()
        else:
            if quiet:
                self.status_bar.pack_forget()
            elif self.preferences.get('show_status_bar', True):
                self.status_bar.pack(fill='x')
            else:
                self.status_bar.pack_forget()
        self._refresh_tab_strip()

    def _feature_async(self, job, success, parent=None):
        future = self._executor.submit(job)
        def finish():
            if self._closing or (parent is not None and not parent.winfo_exists()):
                return
            if not future.done():
                self.root.after(50, finish)
                return
            try:
                result = future.result()
            except Exception as exc:
                self.status_var.set(str(exc))
                self._show_message("error", 'Tekzite', str(exc), parent=parent or self.root)
            else:
                success(result)
        self.root.after(50, finish)

    def _update_site_menu(self, menu):
        host = site_host((self._active_tab() or {}).get('url', ''))
        sites = self.preferences.get('adblock_sites', [])
        exempt = any(host == s or host.endswith('.' + s) for s in sites)
        enabled = self.preferences.get('adblock_enabled', True)
        label = ('Enable' if exempt else 'Disable') + ' Ad Blocking for ' + (host or 'This Site')
        if hasattr(self, '_menu_item_text'):
            label = self._menu_item_text(label, '◇')
        menu.entryconfigure(1, label=label, state='normal' if host and enabled else 'disabled')

    def _toggle_site_adblock(self):
        url = (self._active_tab() or {}).get('url', '')
        host = site_host(url)
        if not host or ':' in host:
            self.status_var.set('Open a website with a domain name to set a site exception')
            return
        sites = set(self.preferences.get('adblock_sites', []))
        # An exception covers this hostname and its subdomains.
        matched = {s for s in sites if host == s or host.endswith('.' + s)}
        enabling = bool(matched)
        if matched:
            sites -= matched
        else:
            sites.add(host)
        proposed = sorted(sites)
        enabled = self.preferences.get('adblock_enabled', True)
        if not enabled:
            self.status_var.set('Enable global ad blocking in Preferences first')
            return
        def apply():
            return features.call('configure', {'enabled': enabled, 'sites': proposed})
        def saved(_):
            self.preferences['adblock_sites'] = proposed
            self._configure_feature_preferences()
            try:
                self._persist_preferences()
            except OSError as exc:
                self._show_message("error", 'Site exception', f'Applied for this session, but could not save: {exc}', parent=self.root)
            self.status_var.set(f'Ad blocking {"on" if enabling else "off"} for {host}')
            # Reload the intended site only; the user may have switched tabs meanwhile.
            if site_host((self._active_tab() or {}).get('url', '')) == host:
                self._reload_current()
        self._feature_async(apply, saved)

    def _feature_window(self, title, columns, widths):
        win = self._new_animated_toplevel(self.root)
        win.title('Tekzite ' + title)
        win.geometry('850x460')
        win.transient(self.root)
        win.configure(bg=self.ui['bg'])
        controls = tk.Frame(win, bg=self.ui['bg'])
        controls.pack(side='bottom', fill='x', padx=18, pady=(10, 16))
        tree = ttk.Treeview(win, columns=columns, show='headings', selectmode='browse')
        for col, width in zip(columns, widths):
            tree.heading(col, text=col)
            tree.column(col, width=width)
        scrollbar = ttk.Scrollbar(win, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        tree.pack(fill='both', expand=True, padx=18, pady=(8, 12))
        win.bind('<Escape>', lambda event: win.destroy())
        return win, tree, controls

    def _feature_button(self, controls, text, command):
        button = tk.Button(controls, text=text, command=command, bg=self.ui['chrome_2'], fg=self.ui['text'],
                           activebackground=self.ui['chrome_hover'], activeforeground=self.ui['text'],
                           relief='flat', bd=0, padx=14, pady=7, cursor='hand2')
        button.pack(side='left', padx=4)
        return button

    @staticmethod
    def _format_storage_bytes(value):
        if not isinstance(value, (int, float)) or value < 0:
            return 'Unknown'
        units = ('B', 'KB', 'MB', 'GB')
        amount = float(value)
        for unit in units:
            if amount < 1024.0 or unit == units[-1]:
                return f'{amount:.0f} {unit}' if unit == 'B' else f'{amount:.1f} {unit}'
            amount /= 1024.0
        return f'{amount:.1f} GB'

    def _show_site_info(self):
        tab = self._active_tab() or {}
        target_id = tab.get('chromium_target_id')
        url = tab.get('url') or self.url_var.get()
        if not target_id or not url:
            self.status_var.set('Open a webpage to view site information')
            return 'break'

        previous = getattr(self, '_site_info_window', None)
        if previous is not None and previous.winfo_exists():
            previous.destroy()

        win = self._new_animated_toplevel(self.root)
        self._site_info_window = win
        win.title('Tekzite Site Info & Privacy')
        win.geometry('650x560')
        win.transient(self.root)
        win.configure(bg=self.ui['bg'])
        win.bind('<Escape>', lambda event: win.destroy())

        header = tk.Frame(win, bg=self.ui['bg'])
        header.pack(fill='x', padx=18, pady=(18, 8))
        tk.Label(header, text='◈', fg=self.ui['accent'], bg=self.ui['bg'],
                 font=('Segoe UI Symbol', 20)).pack(side='left', padx=(0, 10))
        title_var = tk.StringVar(value='Loading site information…')
        tk.Label(header, textvariable=title_var, fg=self.ui['text'], bg=self.ui['bg'],
                 font=(self._ui_display_font_family, 13, 'bold'), anchor='w').pack(side='left', fill='x', expand=True)

        body = tk.Frame(win, bg=self.ui['chrome'], highlightbackground=self.ui['border'], highlightthickness=1)
        body.pack(fill='both', expand=True, padx=18, pady=8)
        details = tk.Text(
            body, bg=self.ui['chrome'], fg=self.ui['text'], insertbackground=self.ui['text'],
            relief='flat', bd=0, highlightthickness=0, wrap='word',
            font=(self._ui_font_family, 10), padx=14, pady=12,
        )
        details.pack(fill='both', expand=True)
        details.insert('1.0', 'Reading Chromium security and storage state…')
        details.configure(state='disabled')

        note_var = tk.StringVar(value='Cookie values are never shown in this panel.')
        tk.Label(win, textvariable=note_var, bg=self.ui['bg'], fg=self.ui['muted'], anchor='w').pack(fill='x', padx=18)
        controls = tk.Frame(win, bg=self.ui['bg'])
        controls.pack(fill='x', padx=14, pady=(8, 16))

        clear_button = self._feature_button(controls, 'Clear site data', lambda: clear_site_data())
        adblock_button = self._feature_button(controls, 'Toggle ad blocking', lambda: toggle_adblock())
        self._feature_button(controls, 'Refresh', lambda: load())
        self._feature_button(controls, 'Close', win.destroy)

        state = {'info': None}

        def set_text(text):
            if not win.winfo_exists():
                return
            details.configure(state='normal')
            details.delete('1.0', 'end')
            details.insert('1.0', text)
            details.configure(state='disabled')

        def render(info):
            state['info'] = info or {}
            info = state['info']
            host = info.get('host') or site_host(url) or 'Current page'
            title_var.set(str(info.get('title') or host))
            scheme = str(info.get('scheme') or '').lower()
            security = str(info.get('securityState') or '').lower()
            crypto = bool(info.get('schemeIsCryptographic'))
            if scheme == 'https' and crypto:
                connection = f'Secure HTTPS ({security or "secure"})'
            elif scheme == 'http':
                connection = 'Not encrypted (HTTP)'
            else:
                connection = f'{scheme or "Internal"} page'

            cookie_count = int(info.get('cookieCount') or 0)
            local_count = int(info.get('localStorageEntries') or 0)
            session_count = int(info.get('sessionStorageEntries') or 0)
            usage = self._format_storage_bytes(info.get('usageBytes'))
            quota = self._format_storage_bytes(info.get('quotaBytes'))
            adblock_enabled = self.preferences.get('adblock_enabled', True)
            exceptions = self.preferences.get('adblock_sites', [])
            exempt = any(host == item or host.endswith('.' + item) for item in exceptions)
            if not adblock_enabled:
                adblock = 'Off globally'
            elif exempt:
                adblock = 'Off for this site'
            else:
                adblock = 'On for this site'

            cookie_names = [str(row.get('name') or '') for row in info.get('cookies', []) if row.get('name')]
            cookie_preview = ', '.join(cookie_names[:12]) if cookie_names else 'None reported'
            if len(cookie_names) > 12:
                cookie_preview += f' … +{len(cookie_names) - 12}'

            mode = ('Private window: temporary profile; history/session '
                    'are not written to disk.' if getattr(self, '_private_mode', False)
                    else 'Normal window: persistent profile with your exit policy.')
            lines = [
                f'Address\n  {info.get("url") or url}',
                f'\nConnection\n  {connection}',
                f'\nCookies\n  {cookie_count} available to this URL\n  Names: {cookie_preview}',
                f'\nOrigin storage\n  Chromium usage: {usage}\n  Chromium quota: {quota}\n'
                f'  localStorage entries: {local_count}\n  sessionStorage entries: {session_count}',
                f'\nAd blocking\n  {adblock}',
                '\nDefault privacy controls\n'
                '  Do Not Track: on\n'
                '  Global Privacy Control: on\n'
                '  Third-party cookie controls: restricted where supported\n'
                '  Camera, mic, location, notifications, sensors: blocked',
                f'\nWindow privacy\n  {mode}',
            ]
            explanations = [x for x in info.get('securityExplanations', []) if x]
            if explanations:
                lines.append('\nChromium security notes\n  ' + '\n  '.join(explanations))
            set_text('\n'.join(lines))
            clear_button.configure(state='normal' if str(info.get('origin') or '').startswith(('http://', 'https://')) else 'disabled')
            adblock_button.configure(state='normal' if site_host(info.get('url') or url) else 'disabled')
            note_var.set('Site data is origin-scoped. Cookie values stay hidden.')

        def load():
            set_text('Reading Chromium security and storage state…')
            note_var.set('Loading…')
            self._feature_async(
                lambda: features.net.get_embedded_chromium_site_info(target_id=target_id),
                render,
                win,
            )

        def clear_site_data():
            info = state.get('info') or {}
            origin = info.get('origin') or site_host(url)
            if not self._ask_yes_no(
                'Clear site data',
                f'Clear cookies, local storage, IndexedDB, caches and other Chromium data for\n{origin}?',
                parent=win,
            ):
                return
            def done(result):
                if not result:
                    note_var.set('No clearable site data found.')
                    return
                note_var.set('Site data cleared. Reloading…')
                active = self._active_tab() or {}
                if active.get('chromium_target_id') == target_id:
                    self._reload_current()
                win.after(700, load)
            self._feature_async(
                lambda: features.net.clear_embedded_chromium_site_data(target_id=target_id),
                done,
                win,
            )

        def toggle_adblock():
            current_host = site_host((state.get('info') or {}).get('url') or url)
            if not current_host:
                return
            self._toggle_site_adblock()
            win.after(500, load)

        load()
        return 'break'

    @staticmethod
    def _extension_metadata(path):
        path = Path(path)
        manifest_path = path / 'manifest.json'
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('manifest.json must contain a JSON object')
        name = str(data.get('name') or path.name)
        if name.startswith('__MSG_') and name.endswith('__'):
            key = name[6:-2]
            locale = str(data.get('default_locale') or '').strip()
            if locale:
                try:
                    messages = json.loads((path / '_locales' / locale / 'messages.json').read_text(encoding='utf-8'))
                    resolved = ((messages.get(key) or {}).get('message')) if isinstance(messages, dict) else None
                    if resolved:
                        name = str(resolved)
                except Exception:
                    pass
        permissions = []
        for field in ('permissions', 'optional_permissions', 'host_permissions', 'optional_host_permissions'):
            values = data.get(field) or []
            if isinstance(values, list):
                permissions.extend(str(value) for value in values)
        return {
            'name': name,
            'version': str(data.get('version') or '?'),
            'manifest_version': data.get('manifest_version'),
            'permissions': permissions,
        }

    def _show_extension_manager(self):
        previous = getattr(self, '_extensions_window', None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            return 'break'

        win, tree, controls = self._feature_window(
            'Extension Manager', ('Extension', 'Version', 'State', 'Folder'), (220, 90, 100, 390)
        )
        self._extensions_window = win
        win.geometry('940x520')
        lockdown = bool(self.preferences.get('privacy_lockdown', True))
        note = tk.StringVar(value=(
            'Privacy Lockdown: user extensions are saved but not loaded.'
            if lockdown else
            'Extensions load at startup. Restart after changes.'
        ))
        tk.Label(win, textvariable=note, bg=self.ui['bg'], fg=self.ui['muted'], anchor='w').pack(side='bottom', fill='x', padx=12)
        state = {'rows': {}}

        def persist(entries):
            self.preferences['extensions'] = entries
            try:
                self._persist_preferences()
            except OSError as exc:
                self._show_message("error", 'Extension Manager', f'Could not save extensions:\n{exc}', parent=win)
                return False
            selected_paths = [row.get('path') for row in entries if row.get('enabled') and row.get('path')]
            os.environ['TEKZITE_USER_EXTENSIONS'] = json.dumps([] if self.preferences.get('privacy_lockdown', True) else selected_paths)
            note.set(
                'Extension settings saved. Privacy Lockdown keeps user extensions disabled.'
                if self.preferences.get('privacy_lockdown', True) else
                'Extension settings saved. Restart Tekzite to apply the new extension set.'
            )
            return True

        def refresh(select_path=None):
            tree.delete(*tree.get_children())
            state['rows'].clear()
            try:
                builtin_path = features.net._zoom_extension_dir()
                builtin = self._extension_metadata(builtin_path)
                tree.insert('', 'end', iid='builtin', values=(
                    builtin['name'], builtin['version'], 'Built-in', str(builtin_path)
                ))
                state['rows']['builtin'] = {'builtin': True, 'path': str(builtin_path), 'meta': builtin}
            except Exception:
                pass

            entries = self.preferences.get('extensions', [])
            for index, row in enumerate(entries):
                path = str(row.get('path') or '')
                iid = f'user:{index}'
                try:
                    meta = self._extension_metadata(path)
                    if row.get('enabled') and self.preferences.get('privacy_lockdown', True):
                        state_label = 'Blocked by Privacy Lockdown'
                    else:
                        state_label = 'Enabled' if row.get('enabled') else 'Disabled'
                except Exception as exc:
                    meta = {'name': Path(path).name or 'Missing extension', 'version': '?', 'permissions': []}
                    state_label = 'Missing / invalid'
                    meta['error'] = str(exc)
                tree.insert('', 'end', iid=iid, values=(meta['name'], meta['version'], state_label, path))
                state['rows'][iid] = {'builtin': False, 'index': index, 'path': path, 'meta': meta}
                if select_path and os.path.normcase(path) == os.path.normcase(select_path):
                    tree.selection_set(iid)
                    tree.focus(iid)
            if not tree.selection() and tree.exists('builtin'):
                tree.selection_set('builtin')

        def selected():
            rows = tree.selection()
            return state['rows'].get(rows[0]) if rows else None

        def add_unpacked():
            folder = filedialog.askdirectory(parent=win, title='Select unpacked Chromium extension folder')
            if not folder:
                return
            path = str(Path(folder).resolve())
            if ',' in path:
                self._show_message("error", 'Extension Manager', 'Chromium cannot safely load an extension from a folder containing a comma.', parent=win)
                return
            try:
                meta = self._extension_metadata(path)
            except Exception as exc:
                self._show_message("error", 'Extension Manager', f'This folder is not a valid unpacked Chromium extension:\n{exc}', parent=win)
                return
            entries = list(self.preferences.get('extensions', []))
            for row in entries:
                if os.path.normcase(str(row.get('path') or '')) == os.path.normcase(path):
                    row['enabled'] = True
                    if persist(entries):
                        refresh(path)
                    return
            entries.append({'path': path, 'enabled': True})
            if persist(entries):
                refresh(path)
                note.set(f'Added {meta["name"]}. Restart Tekzite to load it.')

        def toggle_selected():
            item = selected()
            if not item or item.get('builtin'):
                note.set('Tekzite Local Browser Services is built in and always enabled.')
                return
            entries = list(self.preferences.get('extensions', []))
            index = item['index']
            entries[index] = dict(entries[index])
            entries[index]['enabled'] = not bool(entries[index].get('enabled'))
            path = entries[index].get('path')
            if persist(entries):
                refresh(path)

        def remove_selected():
            item = selected()
            if not item or item.get('builtin'):
                note.set('The built-in Tekzite service extension cannot be removed.')
                return
            entries = list(self.preferences.get('extensions', []))
            row = entries[item['index']]
            if not self._ask_yes_no('Remove extension', f'Remove this extension from Tekzite?\n\n{row.get("path")}', parent=win):
                return
            del entries[item['index']]
            if persist(entries):
                refresh()

        def open_folder():
            item = selected()
            if not item:
                return
            path = item.get('path')
            if not path or not Path(path).is_dir():
                note.set('Extension folder is missing.')
                return
            try:
                if hasattr(os, 'startfile'):
                    os.startfile(path)
                else:
                    note.set(path)
            except Exception as exc:
                note.set(str(exc))

        def show_details(event=None):
            item = selected()
            if not item:
                return
            meta = item.get('meta') or {}
            permissions = meta.get('permissions') or []
            message = (
                f'{meta.get("name", "Extension")}\n'
                f'Version: {meta.get("version", "?")}\n'
                f'Manifest: {meta.get("manifest_version", "?")}\n'
                f'Folder: {item.get("path", "")}\n\n'
                'Declared permissions:\n' + ('\n'.join(f'• {p}' for p in permissions) if permissions else 'None declared')
            )
            if meta.get('error'):
                message += f'\n\nValidation error:\n{meta["error"]}'
            self._show_message("info", 'Extension details', message, parent=win)

        tree.bind('<Double-1>', show_details)
        tree.bind('<Return>', show_details)
        self._feature_button(controls, 'Add unpacked…', add_unpacked)
        self._feature_button(controls, 'Enable / Disable', toggle_selected)
        self._feature_button(controls, 'Remove', remove_selected)
        self._feature_button(controls, 'Details', show_details)
        self._feature_button(controls, 'Open folder', open_folder)
        restart = self._feature_button(controls, 'Restart Tekzite', self._restart_browser)
        restart.configure(bg=self.ui['accent'])
        self._feature_button(controls, 'Close', win.destroy)
        refresh()
        return 'break'

    def _show_history(self):
        if getattr(self, '_private_mode', False):
            self._show_message("info", 
                'Private Window',
                'Browsing history is not recorded in this private window.',
                parent=self.root,
            )
            return 'break'
        win, tree, controls = self._feature_window('History', ('Page', 'Address', 'Last visit'), (240, 390, 170))
        query = tk.StringVar()
        entry = tk.Entry(controls, textvariable=query, bg=self.ui['field'], fg=self.ui['text'], insertbackground=self.ui['text'])
        entry.pack(side='left', fill='x', expand=True, padx=5)
        tk.Label(win, text='Search by page name or address. Clear browsing data on exit also clears this history.', bg=self.ui['bg'], fg=self.ui['muted']).pack(side='bottom')
        visible = {}
        def refresh(*_):
            visible.clear()
            tree.delete(*tree.get_children())
            term = query.get().casefold()
            for i, row in enumerate(self.visits):
                if term in (str(row.get('title', '')) + ' ' + row['url']).casefold():
                    visible[str(i)] = row['url']
                    tree.insert('', 'end', iid=str(i), values=(row.get('title'), row['url'], time.strftime('%Y-%m-%d %H:%M', time.localtime(row['visited']))))
        def open_row(event=None):
            selected = tree.selection()
            if selected:
                url = visible[selected[0]]
                win.destroy()
                self._new_tab(url=url)
        def clear():
            try:
                write_json(self._state_directory / 'history.json', [])
            except OSError as exc:
                self._show_message("error", 'History', str(exc), parent=win)
                return
            self.visits = []
            self._history_dirty = False
            refresh()
        query.trace_add('write', refresh)
        tree.bind('<Double-1>', open_row)
        tree.bind('<Return>', open_row)
        self._feature_button(controls, 'Open', open_row)
        self._feature_button(controls, 'Clear history', clear)
        refresh()
        entry.focus_set()
        return 'break'

    def _show_downloads(self):
        previous = getattr(self, '_downloads_window', None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            return 'break'
        win, tree, controls = self._feature_window('Downloads', ('File', 'Status', 'Progress'), (380, 170, 270))
        self._downloads_window = win
        state = {'items': {}, 'busy': False}
        note = tk.StringVar(value='Loading downloads…')
        tk.Label(win, textvariable=note, bg=self.ui['bg'], fg=self.ui['muted']).pack(side='bottom')
        def update_rows(items):
            state['items'] = {str(item['id']): item for item in items}
            # Update rows in place: retain selection and scroll position.
            for row in tree.get_children():
                if row not in state['items']:
                    tree.delete(row)
            for row, item in state['items'].items():
                status = item.get('error') or ('paused' if item.get('paused') else item.get('state'))
                if item.get('danger') not in (None, 'safe', 'accepted', 'deepScannedSafe'):
                    status = str(status) + ' — ' + item['danger']
                values = (Path(item.get('filename') or item.get('url', '')).name, status, download_progress(item))
                if tree.exists(row):
                    tree.item(row, values=values)
                else:
                    tree.insert('', 'end', iid=row, values=values)
            note.set('No downloads yet' if not items else 'Downloaded files remain on disk when browser data is cleared.')
        def poll():
            if not win.winfo_exists() or self._closing:
                return
            if state['busy']:
                win.after(1000, poll)
                return
            state['busy'] = True
            future = self._executor.submit(features.call, 'downloads')
            def finish():
                if not win.winfo_exists() or self._closing:
                    return
                if not future.done():
                    win.after(50, finish)
                    return
                state['busy'] = False
                try:
                    update_rows(future.result() or [])
                except Exception as exc:
                    note.set(str(exc))
                win.after(1000, poll)
            win.after(50, finish)
        def action(name):
            rows = tree.selection()
            if not rows:
                return
            item = state['items'].get(rows[0])
            if item:
                if name == 'open':
                    danger = str(item.get('danger') or '')
                    if item.get('state') != 'complete' or danger not in {'safe', 'accepted', 'deepScannedSafe'}:
                        self._show_message("warning", 
                            'Tekzite Download Protection',
                            f'Tekzite will not open this file because Chromium reports its danger status as "{danger or "unknown"}".\n\nUse Open folder if you need to inspect it manually.',
                            parent=win,
                        )
                        return
                self._feature_async(lambda: features.call(name, {'id': item['id']}), lambda _: note.set('Download updated'), win)
        for label, name in [('Pause', 'pause'), ('Resume', 'resume'), ('Cancel', 'cancel'), ('Retry', 'retry'), ('Open file', 'open'), ('Open folder', 'show'), ('Remove from list', 'erase')]:
            self._feature_button(controls, label, lambda n=name: action(n))
        self._feature_button(controls, 'Close', win.destroy)
        poll()
        return 'break'


    @staticmethod
    def _origin_for_url(url):
        try:
            parsed = urlsplit(str(url or ''))
            if parsed.scheme not in ('http', 'https') or not parsed.hostname:
                return ''
            port = f':{parsed.port}' if parsed.port else ''
            return f'{parsed.scheme}://{parsed.hostname}{port}'
        except Exception:
            return ''

    def _permission_rules(self):
        rules = self.preferences.get('site_permissions', {})
        return rules if isinstance(rules, dict) else {}

    def _apply_permissions_for_tab(self, tab):
        origin = self._origin_for_url(tab.get('url'))
        if not origin or tab.get('_permissions_origin_applied') == origin:
            return
        tab['_permissions_origin_applied'] = origin
        rule = self._permission_rules().get(origin)
        if not isinstance(rule, dict):
            return
        mapping = {
            'notifications': 'notifications',
            'location': 'geolocation',
            'microphone': 'audioCapture',
            'camera': 'videoCapture',
            'clipboard': 'clipboardReadWrite',
            'sensors': 'sensors',
        }
        setting_map = {'allow': 'granted', 'block': 'denied', 'ask': 'prompt'}
        def apply_all():
            applied = 0
            for key, cdp_name in mapping.items():
                value = str(rule.get(key) or 'block').lower()
                try:
                    features.net.set_embedded_chromium_permission(
                        origin, cdp_name, setting_map.get(value, 'denied')
                    )
                    applied += 1
                except Exception:
                    pass
            return applied
        try:
            self._executor.submit(apply_all)
        except Exception:
            pass

    def _show_permissions_manager(self):
        tab = self._active_tab() or {}
        origin = self._origin_for_url(tab.get('url') or self.url_var.get())
        if not origin:
            self._show_message("info", 'Permissions', 'Open a normal http/https page first.', parent=self.root)
            return 'break'
        win = self._new_animated_toplevel(self.root)
        win.title('Tekzite Permissions Manager')
        win.geometry('560x500')
        win.transient(self.root)
        win.configure(bg=self.ui['bg'])
        tk.Label(win, text='Site permissions', bg=self.ui['bg'], fg=self.ui['text'],
                 font=(self._ui_display_font_family, 17, 'bold')).pack(anchor='w', padx=18, pady=(18, 3))
        tk.Label(win, text=origin, bg=self.ui['bg'], fg=self.ui['muted']).pack(anchor='w', padx=18, pady=(0, 12))
        rules = self._permission_rules()
        current = rules.get(origin, {}) if isinstance(rules.get(origin), dict) else {}
        fields = {}
        for key, label in (
            ('notifications', 'Notifications'), ('location', 'Location'),
            ('microphone', 'Microphone'), ('camera', 'Camera'),
            ('clipboard', 'Clipboard read/write'), ('sensors', 'Motion / sensors'),
        ):
            row = tk.Frame(win, bg=self.ui['bg']); row.pack(fill='x', padx=18, pady=4)
            tk.Label(row, text=label, width=24, anchor='w', bg=self.ui['bg'], fg=self.ui['text']).pack(side='left')
            var = tk.StringVar(value=str(current.get(key) or 'block').title())
            ttk.Combobox(row, textvariable=var, values=('Allow', 'Block', 'Ask'), state='readonly', width=16).pack(side='right')
            fields[key] = var
        note = tk.StringVar(value='Default Tekzite policy is Block. Site-specific rules override it.')
        tk.Label(win, textvariable=note, bg=self.ui['bg'], fg=self.ui['muted'], wraplength=500, justify='left').pack(anchor='w', padx=18, pady=(10, 6))
        buttons = tk.Frame(win, bg=self.ui['bg']); buttons.pack(side='bottom', fill='x', padx=18, pady=16)
        def save():
            updated = dict(self._permission_rules())
            updated[origin] = {key: var.get().lower() for key, var in fields.items()}
            self.preferences['site_permissions'] = updated
            try:
                self._persist_preferences()
            except Exception as exc:
                self._show_message("error", 'Permissions', f'Could not save permissions:\n{exc}', parent=win)
                return
            tab['_permissions_origin_applied'] = None
            self._apply_permissions_for_tab(tab)
            note.set('Permissions saved and applied to the current Chromium session.')
        def reset():
            updated = dict(self._permission_rules()); updated.pop(origin, None)
            self.preferences['site_permissions'] = updated
            try: self._persist_preferences()
            except Exception: pass
            for var in fields.values(): var.set('Block')
            # Explicitly re-apply Tekzite's privacy-first default for this session.
            self.preferences['site_permissions'][origin] = {key: 'block' for key in fields}
            tab['_permissions_origin_applied'] = None; self._apply_permissions_for_tab(tab)
            self.preferences['site_permissions'].pop(origin, None)
            note.set('Site override removed; Tekzite default Block policy is active.')
        self._feature_button(buttons, 'Save', save)
        self._feature_button(buttons, 'Reset to default', reset)
        self._feature_button(buttons, 'Close', win.destroy)
        return 'break'

    @staticmethod
    def _parse_release_version(value):
        numbers = re.findall(r'\d+', str(value or ''))[:4]
        return tuple(int(n) for n in numbers) if numbers else (0,)

    def _check_for_updates(self):
        repo = str(self.preferences.get('update_repository') or '').strip()
        repo = re.sub(r'^https?://github\.com/', '', repo, flags=re.I).strip('/ ')
        if repo.endswith('.git'): repo = repo[:-4]
        if repo.count('/') != 1:
            self._show_message("info", 
                'Tekzite Update',
                'Set the GitHub repository in Settings first.',
                parent=self.root,
            )
            return 'break'
        owner_repo = repo
        self.status_var.set('Checking GitHub for Tekzite updates…')
        def fetch():
            request = urllib.request.Request(
                f'https://api.github.com/repos/{owner_repo}/releases/latest',
                headers={'User-Agent': 'Tekzite-Browser-Update-Checker', 'Accept': 'application/vnd.github+json'},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        def done(data):
            tag = str(data.get('tag_name') or data.get('name') or '')
            current = self._parse_release_version(getattr(self, 'browser_version', '') or '')
            latest = self._parse_release_version(tag)
            assets = data.get('assets') if isinstance(data.get('assets'), list) else []
            win_asset = next((a for a in assets if isinstance(a, dict) and re.search(r'(windows|win|x64)', str(a.get('name') or ''), re.I)), None)
            if win_asset is None:
                win_asset = next((a for a in assets if isinstance(a, dict) and str(a.get('name') or '').lower().endswith(('.zip','.exe','.msi'))), None)
            lines = [f'Installed: {".".join(map(str,current))}', f'Latest release: {tag or "unknown"}']
            if latest > current: lines.append('A newer Tekzite release is available.')
            elif latest == current: lines.append('You are already on the latest published release.')
            else: lines.append('Your installed build is newer than the latest published release.')
            if win_asset and win_asset.get('digest'):
                lines.append(f'Published digest: {win_asset.get("digest")}')
            win = self._new_animated_toplevel(self.root); win.title('Tekzite Update'); win.geometry('620x300'); win.transient(self.root); win.configure(bg=self.ui['bg'])
            tk.Label(win, text='Update Checker', bg=self.ui['bg'], fg=self.ui['text'], font=(self._ui_display_font_family, 17, 'bold')).pack(anchor='w', padx=18, pady=(18, 8))
            tk.Label(win, text='\n'.join(lines), bg=self.ui['bg'], fg=self.ui['text'], justify='left', wraplength=570).pack(anchor='w', padx=18)
            bar = tk.Frame(win, bg=self.ui['bg']); bar.pack(side='bottom', fill='x', padx=18, pady=18)
            if win_asset and win_asset.get('browser_download_url'):
                def download_asset():
                    url = win_asset['browser_download_url']; name = Path(str(win_asset.get('name') or 'Tekzite-update.bin')).name
                    target_dir = Path.home() / 'Downloads'; target_dir.mkdir(parents=True, exist_ok=True)
                    stem, suffix = Path(name).stem, Path(name).suffix
                    target = target_dir / name
                    counter = 1
                    while target.exists():
                        target = target_dir / f'{stem} ({counter}){suffix}'
                        counter += 1
                    partial = target.with_name(target.name + '.part')
                    def work():
                        req = urllib.request.Request(url, headers={'User-Agent':'Tekzite-Browser-Updater'})
                        digest = hashlib.sha256()
                        try:
                            with urllib.request.urlopen(req, timeout=30) as src, open(partial, 'wb') as dst:
                                while True:
                                    chunk = src.read(1024*1024)
                                    if not chunk: break
                                    dst.write(chunk); digest.update(chunk)
                            actual = digest.hexdigest()
                            expected = str(win_asset.get('digest') or '')
                            verified = None
                            if expected.lower().startswith('sha256:'):
                                verified = actual.lower() == expected.split(':',1)[1].lower()
                                if not verified:
                                    raise RuntimeError('SHA-256 verification failed; the downloaded file was removed.')
                            os.replace(partial, target)
                            return str(target), actual, verified
                        except Exception:
                            try: partial.unlink(missing_ok=True)
                            except OSError: pass
                            raise
                    def saved(result):
                        path, digest, verified = result
                        self._show_message("info", 'Tekzite Update', f'Downloaded to:\n{path}\n\nSHA-256: {digest}\n' + ('Verified against GitHub digest.' if verified else 'GitHub did not publish a SHA-256 digest for this asset.'), parent=win)
                    self._feature_async(work, saved, win)
                self._feature_button(bar, 'Download update', download_asset)
            release_url = str(data.get('html_url') or '')
            if release_url:
                self._feature_button(bar, 'Open release page', lambda: self._new_tab(url=release_url))
            self._feature_button(bar, 'Close', win.destroy)
            self.status_var.set('Update check complete')
        self._feature_async(fetch, done)
        return 'break'

    def _show_diagnostics(self):
        win = self._new_animated_toplevel(self.root); win.title('Tekzite Diagnostics'); win.geometry('820x620'); win.transient(self.root); win.configure(bg=self.ui['bg'])
        text = tk.Text(win, bg=self.ui['field'], fg=self.ui['text'], insertbackground=self.ui['text'], wrap='word', relief='flat')
        text.pack(fill='both', expand=True, padx=12, pady=12)
        state = []
        version = str(getattr(self, 'browser_version', '') or '')
        state.append(f'Tekzite Browser v{version}' if version else 'Tekzite Browser')
        state.append(f'Profile: {getattr(self, "_profile_name", "Default")}')
        state.append(f'Private window: {bool(getattr(self, "_private_mode", False))}')
        state.append(f'Open tabs: {len(getattr(self, "tabs", []))}')
        state.append(f'Sleeping tabs: {sum(1 for t in getattr(self, "tabs", []) if t.get("sleeping"))}')
        state.append(f'Chromium session active: {bool(features.net._EDGE_SESSION)}')
        if features.net._EDGE_SESSION:
            session = features.net._EDGE_SESSION
            state.append(f'Chromium DevTools port: {session.get("port")}')
            state.append(f'Chromium profile: {session.get("profile")}')
            state.append(f'Current target: {session.get("target_id")}')
            if sys.platform.startswith("linux"):
                policy = dict(session.get("gpu_policy") or {})
                gpu = dict(session.get("gpu_info") or {})
                vendors = ", ".join(policy.get("vendors") or []) or "not detected"
                requested = "hardware" if policy.get("hardware_requested") else "software"
                actual = (
                    "hardware"
                    if gpu.get("hardware_active")
                    else "software"
                    if gpu and not gpu.get("probe_error")
                    else "unknown"
                )
                state.append(f'Linux GPU vendors: {vendors}')
                state.append(f'Linux Chromium GPU request: {requested}')
                state.append(f'Linux Chromium GPU active: {actual}')
                if gpu.get("renderer"):
                    state.append(f'Linux Chromium renderer: {gpu.get("renderer")}')
                state.append(
                    f'Linux hardware video requested: '
                    f'{bool(policy.get("video_decode_requested"))}'
                )
                state.append('Linux presentation: CDP software compositor')
        try:
            network = features.net._NETWORK_ENGINE or {}
            state.append(f'Network engine: {network.get("proxy_url") or "not started"}')
        except Exception:
            network = {}
        try:
            policy = loopback_policy.snapshot()
            state.append(f'Python loopback guard: {"ENABLED" if policy.get("enabled") else "disabled"}')
            for row in policy.get("allowed", []):
                state.append(f'  allow 127.0.0.1:{row.get("port")} — {row.get("purpose")}')
            if policy.get("blocked"):
                state.append(f'Blocked Python loopback attempts: {len(policy.get("blocked", []))} retained')
        except Exception:
            pass
        state.append('\nTabs:')
        for tab in getattr(self, 'tabs', []):
            state.append(f'  #{tab.get("id")} {"[sleeping] " if tab.get("sleeping") else ""}{tab.get("title") or "New Tab"} | {tab.get("url") or "blank"} | target={tab.get("chromium_target_id")}')
        log_path = self._state_directory / 'stability.log'
        if log_path.exists():
            try:
                tail = log_path.read_text(encoding='utf-8', errors='replace')[-12000:]
                state.append('\nRecent stability.log:\n' + tail)
            except OSError: pass
        text.insert('1.0', '\n'.join(state)); text.configure(state='disabled')
        return 'break'

    def _show_network_connections(self):
        """Show a live platform socket view for Tekzite and Chromium children."""
        previous = getattr(self, '_network_connections_window', None)
        if previous is not None and previous.winfo_exists():
            try:
                previous.lift()
                previous.focus_force()
            except Exception:
                pass
            return 'break'

        win, tree, controls = self._feature_window(
            'Live Socket View',
            ('Role', 'Process', 'PID', 'Proto', 'Local endpoint', 'Hostname', 'Relation', 'Remote endpoint', 'State', 'Purpose', 'Resource', 'Initiator', 'Script caller', 'Match', 'Traffic', 'Seen', 'Path'),
            (120, 150, 65, 60, 185, 220, 140, 185, 85, 150, 125, 200, 300, 105, 160, 80, 175),
        )
        self._network_connections_window = win
        win.geometry('2500x700')
        try:
            win.minsize(980, 480)
        except Exception:
            pass

        scope_note = tk.Label(
            win,
            text=(
                ('Live Tekzite/Chromium sockets. ' if os.name == 'nt' else
                 'Live Tekzite/Chromium sockets. ') +
                'Hostnames are exact; request attribution stays in RAM.'
            ),
            bg=self.ui['bg'], fg=self.ui['muted'], anchor='w', justify='left',
            wraplength=1650,
        )
        scope_note.pack(side='top', fill='x', padx=18, pady=(12, 0), before=tree)

        status_var = tk.StringVar(value='Reading live socket tables…')
        auto_var = tk.BooleanVar(value=True)
        dns_var = tk.BooleanVar(value=True)
        refresh_after = {'id': None}
        snapshot_future = {'value': None}
        last_rows = {'rows': []}
        dns_cache = {}
        dns_pending = {}
        window_alive = {'value': True}

        def endpoint(address, port):
            address = str(address or '')
            try:
                port = int(port or 0)
            except Exception:
                port = 0
            if not address:
                return ''
            shown = f'[{address}]' if ':' in address and not address.startswith('[') else address
            return f'{shown}:{port}' if port else shown

        def queue_dns(address):
            address = str(address or '').split('%', 1)[0]
            if not address or not dns_var.get() or address in dns_cache or address in dns_pending:
                return
            # Keep DNS enrichment deliberately bounded so a page with many CDN
            # endpoints cannot starve browser work in the shared executor.
            if len(dns_pending) >= 6:
                return
            try:
                import ipaddress as _ipaddress
                ip = _ipaddress.ip_address(address)
                if ip.is_loopback:
                    dns_cache[address] = 'localhost'
                    return
                if ip.is_unspecified:
                    dns_cache[address] = ''
                    return
            except Exception:
                return
            dns_pending[address] = self._executor.submit(features.net.reverse_dns_hostname, address)

        def harvest_dns():
            changed = False
            for address, future in list(dns_pending.items()):
                if not future.done():
                    continue
                try:
                    dns_cache[address] = str(future.result() or '')[:253]
                except Exception:
                    dns_cache[address] = ''
                dns_pending.pop(address, None)
                changed = True
            return changed

        def hostname_for(row):
            if str(row.get('state') or '') == 'LISTEN':
                return ''
            host = str(row.get('hostname') or '')
            destination = str(row.get('destination_host') or '')
            if destination and host == 'Tekzite Network':
                return f'Tekzite Network → {destination}'
            if host:
                return host
            address = str(row.get('remote_address') or '').split('%', 1)[0]
            if not address:
                return ''
            cached = dns_cache.get(address)
            if cached is not None:
                return cached or address
            queue_dns(address)
            return address

        def _format_bytes(value):
            try:
                value = max(0, int(value or 0))
            except Exception:
                value = 0
            if value < 1024:
                return f'{value} B'
            if value < 1024 * 1024:
                return f'{value / 1024:.1f} KB'
            return f'{value / (1024 * 1024):.1f} MB'

        def traffic_for(row):
            if str(row.get('protocol') or '') != 'UDP' or str(row.get('state') or '') != 'PEER':
                return ''
            txp = int(row.get('tx_packets') or 0)
            rxp = int(row.get('rx_packets') or 0)
            txb = _format_bytes(row.get('tx_bytes'))
            rxb = _format_bytes(row.get('rx_bytes'))
            return f'↑{txp}/{txb}  ↓{rxp}/{rxb}'

        def seen_for(row):
            try:
                seen = float(row.get('last_seen') or 0.0)
            except Exception:
                seen = 0.0
            if seen <= 0:
                return ''
            age = max(0.0, time.time() - seen)
            if age < 1.0:
                return 'now'
            if age < 10.0:
                return f'{age:.1f}s ago'
            return f'{int(age)}s ago'

        def row_values(row):
            return (
                row.get('role') or '',
                row.get('process') or '',
                row.get('pid') or '',
                f"{row.get('protocol') or ''}/{row.get('family') or ''}",
                endpoint(row.get('local_address'), row.get('local_port')),
                hostname_for(row),
                row.get('request_domain_relation') or '',
                endpoint(row.get('remote_address'), row.get('remote_port')),
                row.get('state') or '',
                row.get('request_purpose') or '',
                row.get('request_resource') or '',
                row.get('request_initiator') or '',
                row.get('request_script') or '',
                row.get('request_match_quality') or '',
                traffic_for(row),
                seen_for(row),
                row.get('path') or '',
            )

        def apply_snapshot(snapshot):
            if not window_alive['value'] or not win.winfo_exists():
                return
            if not (snapshot or {}).get('supported'):
                status_var.set(str((snapshot or {}).get('reason') or 'Live socket view is unavailable.'))
                return
            rows = list((snapshot or {}).get('sockets') or [])
            last_rows['rows'] = rows
            live_iids = set()
            for index, row in enumerate(rows):
                key = str(row.get('key') or f'{index}:{row}')
                iid = 'sock:' + hashlib.sha1(key.encode('utf-8', 'replace')).hexdigest()[:20]
                live_iids.add(iid)
                values = row_values(row)
                if tree.exists(iid):
                    tree.item(iid, values=values)
                    tree.move(iid, '', index)
                else:
                    tree.insert('', index, iid=iid, values=values)
            for iid in list(tree.get_children()):
                if iid not in live_iids:
                    tree.delete(iid)

            tcp = sum(1 for row in rows if row.get('protocol') == 'TCP')
            udp = sum(1 for row in rows if row.get('protocol') == 'UDP')
            established = sum(1 for row in rows if row.get('state') == 'ESTABLISHED')
            listeners = sum(1 for row in rows if row.get('state') == 'LISTEN')
            recent_tcp = sum(1 for row in rows if row.get('protocol') == 'TCP' and row.get('state') == 'RECENT')
            direct = sum(1 for row in rows if str(row.get('path') or '').startswith('Direct'))
            udp_peers = sum(1 for row in rows if row.get('protocol') == 'UDP' and row.get('state') == 'PEER')
            pids = {int(row.get('pid') or 0) for row in rows if int(row.get('pid') or 0) > 0}
            direct_text = f' • {direct} Direct external' if direct else ''
            peer_text = (f' • {udp_peers} UDP peer(s)' if udp_peers else '') + (f' • {recent_tcp} recent TCP' if recent_tcp else '')
            udp_monitor = (snapshot or {}).get('udp_peer_monitor') or {}
            etw_status = str(udp_monitor.get('status') or '')
            etw_reason = str(udp_monitor.get('reason') or '')
            etw_text = ' • Network ETW active' if etw_status == 'running' else ''
            if etw_status in {'error', 'permission', 'unsupported'} and etw_reason:
                etw_text = f' • Network ETW: {etw_reason}'
            audit = (snapshot or {}).get('request_audit') or {}
            audit_status = str(audit.get('status') or '')
            audit_reason = str(audit.get('reason') or '')
            audit_text = ''
            if audit_status in {'running', 'starting'}:
                audit_text = f" • CDP attribution {int(audit.get('target_count') or 0)} target(s)/{int(audit.get('request_count') or 0)} req"
            elif audit_reason:
                audit_text = f' • CDP attribution: {audit_reason}'
            status_var.set(
                f'{len(rows)} live socket(s) • {len(pids)} process(es) • '
                f'{tcp} TCP • {udp} UDP • {established} established • {listeners} listener(s)'
                f'{peer_text}{direct_text}{etw_text}{audit_text} • 250 ms snapshots'
            )

        def collect_snapshot():
            auth = getattr(self, '_google_auth_handle', None) or {}
            extra_pids = list(auth.get('browser_pids') or [])
            launch_pid = auth.get('launch_pid')
            if launch_pid:
                extra_pids.append(launch_pid)
            return features.net.live_socket_snapshot(include_proxy_names=True, extra_pids=extra_pids)

        def schedule_next(delay=250):
            if not window_alive['value'] or not win.winfo_exists() or not auto_var.get():
                return
            refresh_after['id'] = win.after(delay, refresh)

        def finish_snapshot():
            if not window_alive['value'] or not win.winfo_exists():
                return
            future = snapshot_future.get('value')
            if future is None:
                return
            if not future.done():
                win.after(25, finish_snapshot)
                return
            snapshot_future['value'] = None
            try:
                apply_snapshot(future.result())
            except Exception as exc:
                status_var.set(f'Could not read live sockets: {exc}')
            harvest_dns()
            # Hostnames resolved after the snapshot can be painted immediately
            # without waiting for another OS socket-table query.
            if last_rows.get('rows'):
                for index, row in enumerate(last_rows['rows']):
                    key = str(row.get('key') or f'{index}:{row}')
                    iid = 'sock:' + hashlib.sha1(key.encode('utf-8', 'replace')).hexdigest()[:20]
                    if tree.exists(iid):
                        tree.item(iid, values=row_values(row))
            schedule_next(250)

        def refresh():
            if not window_alive['value'] or not win.winfo_exists():
                return
            harvest_dns()
            future = snapshot_future.get('value')
            if future is not None and not future.done():
                return
            snapshot_future['value'] = self._executor.submit(collect_snapshot)
            win.after(10, finish_snapshot)

        def copy_rows():
            rows = last_rows.get('rows') or []
            lines = ['Role\tProcess\tPID\tProtocol\tLocal endpoint\tHostname\tRelation\tRemote endpoint\tState\tPurpose\tResource\tInitiator\tScript caller\tMatch\tTraffic\tSeen\tPath']
            for row in rows:
                values = row_values(row)
                lines.append('\t'.join(str(value) for value in values))
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append('\n'.join(lines))
                status_var.set(f'Copied {len(rows)} live socket row(s).')
            except Exception:
                status_var.set('Could not copy live socket view.')

        def show_selected_details(_event=None):
            selection = tree.selection()
            if not selection:
                status_var.set('Select a socket row first.')
                return 'break'
            try:
                index = tree.index(selection[0])
                row = (last_rows.get('rows') or [])[index]
            except Exception:
                status_var.set('That socket row is no longer present.')
                return 'break'

            detail = self._new_animated_toplevel(win)
            detail.title('Tekzite Socket Attribution')
            detail.geometry('920x650')
            detail.transient(win)
            detail.configure(bg=self.ui['bg'])
            text = tk.Text(
                detail, bg=self.ui['field'], fg=self.ui['text'], insertbackground=self.ui['text'],
                wrap='word', relief='flat', font=(self._ui_monospace_font_family, self._font_size(9)),
                padx=14, pady=12,
            )
            text.pack(fill='both', expand=True, padx=12, pady=(12, 6))
            lines = [
                'SOCKET',
                f"Role:              {row.get('role') or ''}",
                f"Process / PID:     {row.get('process') or ''} / {row.get('pid') or ''}",
                f"Protocol:          {row.get('protocol') or ''}/{row.get('family') or ''}",
                f"State:             {row.get('state') or ''}",
                f"Local endpoint:    {endpoint(row.get('local_address'), row.get('local_port'))}",
                f"Remote endpoint:   {endpoint(row.get('remote_address'), row.get('remote_port'))}",
                f"Hostname:          {hostname_for(row)}",
                f"Path:              {row.get('path') or ''}",
                '',
                'REQUEST ATTRIBUTION',
                f"Match:              {row.get('request_match_quality') or 'Unattributed'}",
                f"Domain relation:    {row.get('request_domain_relation') or 'Unknown'}",
                f"Purpose:            {row.get('request_purpose') or ''}",
                f"Method / resource:  {(row.get('request_method') or '')} / {(row.get('request_resource') or '')}",
                f"Target host:        {row.get('request_target_host') or ''}",
                f"Initiator:          {row.get('request_initiator') or ''}",
                f"Script caller:      {row.get('request_script') or '(none observed)'}",
                f"HTTP transport:     {row.get('request_transport') or ''}",
                f"CDP connection ID:  {row.get('request_connection_id') or ''}",
                f"Connection reused:  {row.get('request_connection_reused') if row.get('request_connection_reused') is not None else 'unknown'}",
                f"Response:           {row.get('request_response_status') or ''} {row.get('request_response_mime') or ''}".rstrip(),
                f"Encoded bytes:      {_format_bytes(row.get('request_encoded_bytes')) if row.get('request_encoded_bytes') else ''}",
                f"Delivery:           {'service worker' if row.get('request_from_service_worker') else ('cache' if row.get('request_from_cache') else ('network' if row.get('request_response_status') else ''))}",
                f"TLS:                {' / '.join(v for v in (str(row.get('request_security_state') or ''), str(row.get('request_tls_protocol') or ''), str(row.get('request_tls_cipher') or ''), str(row.get('request_tls_issuer') or '')) if v)}",
                f"Observed headers:   {', '.join(name for name, present in (('Cookie', row.get('request_observed_cookie')), ('Authorization', row.get('request_observed_authorization')), ('Origin', row.get('request_observed_origin')), ('Referer', row.get('request_observed_referer')), ('Set-Cookie response', row.get('request_observed_set_cookie'))) if present) or '(none exposed by this CDP event)'}",
                f"Redirect:           {(row.get('request_redirect_from_host') or '') + (' → ' if row.get('request_redirect_from_host') and row.get('request_redirect_to_host') else '') + (row.get('request_redirect_to_host') or '')}",
                f"Failure:            {(row.get('request_blocked_reason') or row.get('request_failure_text') or '') if row.get('request_loading_failed') else ''}",
            ]
            stack = list(row.get('request_script_stack') or [])
            if stack:
                lines.extend(['', 'SANITIZED JAVASCRIPT CALL CHAIN'])
                for number, frame in enumerate(stack, 1):
                    lines.append(f"  {number:>2}. {frame.get('label') or ''}")
            lines.extend([
                '',
                'INTERPRETATION',
                'Match labels estimate how strongly this request maps to the socket.',
                'No payloads or full script source are retained.',
            ])
            text.insert('1.0', '\n'.join(lines))
            text.configure(state='disabled')
            bar = tk.Frame(detail, bg=self.ui['bg'])
            bar.pack(fill='x', padx=12, pady=(0, 12))

            # v10.5.76 compatibility: features.net.get_network_request_script_excerpt remains available for callers that need the raw bounded excerpt.
            def show_script_source():
                target_id = str(row.get('request_target_id') or '')
                script_id = str(row.get('request_script_id') or '')
                line = int(row.get('request_script_line') or 0)
                column = int(row.get('request_script_column') or 0)
                source_win = self._new_animated_toplevel(detail)
                source_win.title('Tekzite JavaScript Inspector')
                source_win.geometry('1080x620')
                source_win.transient(detail)
                source_win.configure(bg=self.ui['bg'])
                source_text = tk.Text(
                    source_win, bg=self.ui['field'], fg=self.ui['text'], insertbackground=self.ui['text'],
                    wrap='none', relief='flat', font=(self._ui_monospace_font_family, self._font_size(9)),
                    padx=14, pady=12,
                )
                ybar = ttk.Scrollbar(source_win, orient='vertical', command=source_text.yview)
                xbar = ttk.Scrollbar(source_win, orient='horizontal', command=source_text.xview)
                source_text.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
                ybar.pack(side='right', fill='y', padx=(0, 12), pady=(12, 44))
                xbar.pack(side='bottom', fill='x', padx=(12, 24), pady=(0, 4))
                source_text.pack(fill='both', expand=True, padx=(12, 0), pady=(12, 0))
                source_text.insert('1.0', 'Reading the live script from Chromium…')
                source_text.configure(state='disabled')
                source_status = tk.StringVar(value='Source is analyzed in memory only.')
                source_bar = tk.Frame(source_win, bg=self.ui['bg'])
                source_bar.pack(side='bottom', fill='x', padx=12, pady=(4, 10))
                tk.Label(
                    source_bar, textvariable=source_status, bg=self.ui['bg'], fg=self.ui['muted'], anchor='w',
                ).pack(side='left', fill='x', expand=True, padx=(4, 8))

                copied = {'text': ''}
                def copy_excerpt():
                    if not copied['text']:
                        return
                    try:
                        self.root.clipboard_clear(); self.root.clipboard_append(copied['text'])
                        source_status.set('Copied the displayed JavaScript analysis report.')
                    except Exception:
                        source_status.set('Could not copy the source excerpt.')

                copy_button = self._feature_button(source_bar, 'Copy report', copy_excerpt)
                copy_button.configure(state='disabled')
                self._feature_button(source_bar, 'Close', source_win.destroy)
                source_win.bind('<Escape>', lambda event: source_win.destroy())

                if not target_id or not script_id:
                    source_text.configure(state='normal')
                    source_text.delete('1.0', 'end')
                    source_text.insert('1.0', 'No JavaScript caller source is available for this request.')
                    source_text.configure(state='disabled')
                    source_status.set('No JavaScript source is available for this row.')
                    return

                future = self._executor.submit(
                    features.net.get_network_request_script_analysis,
                    target_id, script_id, line, column, 8,
                )
                def finish_source():
                    if not source_win.winfo_exists():
                        return
                    if not future.done():
                        source_win.after(30, finish_source)
                        return
                    try:
                        result = future.result() or {}
                    except Exception as exc:
                        result = {'ok': False, 'reason': str(exc), 'text': ''}
                    source_text.configure(state='normal')
                    source_text.delete('1.0', 'end')
                    if result.get('ok'):
                        source_map = result.get('source_map') if isinstance(result.get('source_map'), dict) else {}
                        mapped = source_map.get('mapped') if isinstance(source_map.get('mapped'), dict) else {}
                        report = [
                            f"Caller: {row.get('request_script') or '(script)'}",
                            f"Generated source: {int(result.get('source_chars') or 0):,} characters, {int(result.get('line_count') or 0):,} lines",
                            f"Pretty caller: line {int(result.get('pretty_line') or 0)}:{int(result.get('pretty_column') or 0)}" if result.get('pretty_ok') else f"Pretty-print: unavailable ({result.get('pretty_reason') or 'formatter limit'})",
                            f"Containing function: {result.get('function_signature') or '(not confidently identified)'}",
                            f"Source map: {source_map.get('label') or 'No source map advertised'}",
                        ]
                        if source_map.get('kind') == 'external':
                            report.append('Source-map policy: external map advertised but not fetched automatically, so inspection creates no extra network request.')
                        if mapped:
                            original = f"{mapped.get('source_file') or '(original source)'}:{mapped.get('line') or 0}:{mapped.get('column') or 0}"
                            if mapped.get('name'):
                                original += f"  name={mapped.get('name')}"
                            report.append(f"Original source-map position: {original}")

                        primitives = list(result.get('network_primitives') or [])
                        report.extend(['', 'NETWORK PRIMITIVE TRACE'])
                        if primitives:
                            for number, primitive in enumerate(primitives, 1):
                                distance = int(primitive.get('distance') or 0)
                                delta = f"+{distance}" if distance >= 0 else str(distance)
                                report.append(
                                    f"  {number:>2}. {primitive.get('name') or 'network API'} @ generated "
                                    f"{primitive.get('line') or 0}:{primitive.get('column') or 0} "
                                    f"({primitive.get('direction') or ''}, offset {delta})"
                                )
                        else:
                            report.append('  No direct fetch/XHR/WebSocket/EventSource/sendBeacon/WebTransport primitive was visible inside the identified function or nearby source window.')

                        if result.get('pretty_text'):
                            report.extend(['', 'PRETTY-PRINTED CALLER CONTEXT', str(result.get('pretty_text') or '')])
                        if result.get('function_text'):
                            report.extend(['', 'CONTAINING FUNCTION CONTEXT', str(result.get('function_text') or '')])
                        if source_map.get('original_excerpt'):
                            report.extend(['', 'ORIGINAL SOURCE VIA INLINE SOURCE MAP', str(source_map.get('original_excerpt') or '')])
                        if result.get('raw_text'):
                            report.extend(['', 'RAW GENERATED CALLER CONTEXT', str(result.get('raw_text') or '')])
                        report.extend([
                            '',
                            'PRIVACY / EVIDENCE',
                            'Script source is analyzed on demand and not stored.',
                            'Inline source maps are decoded locally.',
                            'CDP caller coordinates remain authoritative.',
                        ])
                        shown = '\n'.join(report)
                        source_text.insert('1.0', shown)
                        copied['text'] = shown
                        copy_button.configure(state='normal')
                        source_status.set('Analysis complete. Source discarded.')
                    else:
                        source_text.insert('1.0', str(result.get('reason') or 'The live script source is no longer available.'))
                        source_status.set('Source unavailable; the page may have changed.')
                    source_text.configure(state='disabled')
                source_win.after(10, finish_source)

            source_button = self._feature_button(bar, 'Show script source', show_script_source)
            if not row.get('request_script'):
                source_button.configure(state='disabled')
            self._feature_button(bar, 'Close', detail.destroy)
            detail.bind('<Escape>', lambda event: detail.destroy())
            return 'break'

        def show_request_timeline():
            timeline, req_tree, req_controls = self._feature_window(
                'Causal Request Timeline',
                ('Time', 'Hostname', 'Relation', 'Method', 'Resource', 'Status', 'Bytes', 'Delivery', 'Purpose', 'Initiator', 'Script caller', 'Connection'),
                (110, 230, 150, 70, 105, 70, 90, 120, 150, 190, 310, 150),
            )
            timeline.geometry('1900x720')
            timeline.transient(win)
            try:
                timeline.minsize(980, 480)
            except Exception:
                pass
            req_status = tk.StringVar(value='Reading Chromium request timeline…')
            req_search = tk.StringVar(value='')
            req_live = tk.BooleanVar(value=True)
            req_rows = {'rows': []}
            req_after = {'id': None}
            req_alive = {'value': True}

            note = tk.Label(
                timeline,
                text=(
                    'RAM-only request timeline. Sensitive payloads are not retained. '
                    'Relation labels are informational; byte counts come from Chromium.'
                ),
                bg=self.ui['bg'], fg=self.ui['muted'], anchor='w', justify='left', wraplength=1500,
            )
            note.pack(side='top', fill='x', padx=18, pady=(12, 0), before=req_tree)

            def req_delivery(row):
                if row.get('loading_failed'):
                    reason = row.get('blocked_reason') or row.get('failure_text') or 'failed'
                    return f'failed: {reason}'[:120]
                if row.get('response_from_service_worker'):
                    return 'service worker'
                if row.get('request_served_from_cache') or row.get('response_from_disk_cache') or row.get('response_from_prefetch_cache'):
                    return 'cache'
                if row.get('response_status'):
                    return 'network'
                if row.get('resource_type') == 'WebSocket' and row.get('websocket_closed'):
                    return 'WebSocket closed'
                return 'pending'

            def req_connection(row):
                proto = str(row.get('response_protocol') or '')
                cid = str(row.get('connection_id') or '')
                reused = row.get('connection_reused')
                prefix = 'reused' if reused is True else ('new' if reused is False else 'unknown')
                bits = [prefix]
                if proto: bits.append(proto)
                if cid: bits.append('#' + cid)
                return ' '.join(bits)

            def req_time(row):
                stamp = float(row.get('wall_time') or row.get('first_seen') or 0.0)
                if stamp <= 0:
                    return ''
                lt = time.localtime(stamp)
                ms = int((stamp - int(stamp)) * 1000) % 1000
                return time.strftime('%H:%M:%S', lt) + f'.{ms:03d}'

            def req_values(row):
                initiator = str(row.get('initiator_label') or '') or str(row.get('initiator_type') or '')
                if not row.get('initiator_label') and row.get('initiator_host'):
                    initiator += f" @ {row.get('initiator_host')}"
                return (
                    req_time(row), row.get('host') or '', row.get('domain_relation') or 'Unknown',
                    row.get('method') or '', row.get('resource_type') or '',
                    row.get('response_status') or ('ERR' if row.get('loading_failed') else ''),
                    _format_bytes(row.get('encoded_data_length')) if row.get('encoded_data_length') else '',
                    req_delivery(row), row.get('purpose') or '', initiator,
                    row.get('script_source') or '', req_connection(row),
                )

            def apply_requests(snapshot):
                if not req_alive['value'] or not timeline.winfo_exists():
                    return
                rows = list((snapshot or {}).get('requests') or [])
                query = req_search.get().strip().casefold()
                if query:
                    rows = [row for row in rows if query in ' '.join(str(row.get(k) or '') for k in (
                        'host', 'domain_relation', 'method', 'resource_type', 'purpose', 'initiator_host',
                        'script_source', 'response_mime_type', 'failure_text', 'blocked_reason', 'tls_issuer'
                    )).casefold()]
                rows.sort(key=lambda row: float(row.get('first_seen') or 0.0), reverse=True)
                req_rows['rows'] = rows
                for iid in req_tree.get_children():
                    req_tree.delete(iid)
                for index, row in enumerate(rows):
                    req_tree.insert('', 'end', iid=f'req:{index}', values=req_values(row))
                req_status.set(
                    f"{len(rows)} shown • {int((snapshot or {}).get('request_count') or 0)} retained • "
                    f"{int((snapshot or {}).get('target_count') or 0)} target(s) • RAM only"
                )

            def req_refresh():
                if not req_alive['value'] or not timeline.winfo_exists():
                    return
                try:
                    apply_requests(features.net.network_request_audit_snapshot())
                except Exception as exc:
                    req_status.set(f'Could not read request timeline: {exc}')
                if req_live.get() and req_alive['value'] and timeline.winfo_exists():
                    req_after['id'] = timeline.after(400, req_refresh)

            def selected_request():
                sel = req_tree.selection()
                if not sel:
                    return None
                try:
                    return req_rows['rows'][req_tree.index(sel[0])]
                except Exception:
                    return None

            def show_request_details(_event=None):
                row = selected_request()
                if row is None:
                    req_status.set('Select a request first.')
                    return 'break'
                detail = self._new_animated_toplevel(timeline)
                detail.title('Tekzite Causal Request Details')
                detail.geometry('960x720')
                detail.transient(timeline)
                detail.configure(bg=self.ui['bg'])
                body = tk.Text(
                    detail, bg=self.ui['field'], fg=self.ui['text'], insertbackground=self.ui['text'],
                    wrap='word', relief='flat', font=(self._ui_monospace_font_family, self._font_size(9)),
                    padx=14, pady=12,
                )
                body.pack(fill='both', expand=True, padx=12, pady=(12, 6))
                redirect = ''
                if row.get('redirect_from_host') or row.get('redirect_to_host'):
                    redirect = f"{row.get('redirect_from_host') or '?'} --{row.get('redirect_status') or ''}--> {row.get('redirect_to_host') or row.get('host') or '?'}"
                failure = row.get('blocked_reason') or row.get('cors_error') or row.get('failure_text') or ''
                causal = [
                    str(row.get('target_host') or '(target)'),
                    str(row.get('script_source') or (row.get('initiator_type') or 'request')),
                    f"{row.get('method') or ''} {row.get('resource_type') or ''}".strip(),
                    str(row.get('host') or '(destination)'),
                    req_connection(row),
                ]
                lines = [
                    'CAUSAL REQUEST TRACE',
                    '  ' + '  →  '.join(part for part in causal if part),
                    '',
                    f"Time:              {req_time(row)}",
                    f"Destination:       {row.get('host') or ''}:{row.get('port') or ''}",
                    f"Domain relation:   {row.get('domain_relation') or 'Unknown'}",
                    f"Purpose:           {row.get('purpose') or ''}",
                    f"Method/resource:   {row.get('method') or ''} / {row.get('resource_type') or ''}",
                    f"Has request body:  {bool(row.get('has_post_data'))}",
                    f"Initial priority:  {row.get('initial_priority') or ''}",
                    f"Initiator:         {row.get('initiator_label') or ((str(row.get('initiator_type') or '') + (' @ ' + str(row.get('initiator_host')) if row.get('initiator_host') else '')).strip())}",
                    f"Internal source:   {row.get('internal_source_id') or ''}",
                    f"Script caller:     {row.get('script_source') or '(none observed)'}",
                    f"Redirect:          {redirect}",
                    '',
                    'RESPONSE / DELIVERY',
                    f"Status / MIME:     {row.get('response_status') or ''} / {row.get('response_mime_type') or ''}",
                    f"Encoded bytes:     {_format_bytes(row.get('encoded_data_length')) if row.get('encoded_data_length') else ''}",
                    f"Delivery:          {req_delivery(row)}",
                    f"Transport:         {row.get('response_protocol') or ''}",
                    f"Connection:        {req_connection(row)}",
                    f"Remote endpoint:   {endpoint(row.get('remote_address'), row.get('remote_port'))}",
                    f"TLS:               {' / '.join(v for v in (str(row.get('security_state') or ''), str(row.get('tls_protocol') or ''), str(row.get('tls_cipher') or ''), str(row.get('tls_issuer') or '')) if v)}",
                    f"Observed headers:  {', '.join(name for name, present in (('Cookie', row.get('observed_cookie_header')), ('Authorization', row.get('observed_authorization_header')), ('Origin', row.get('observed_origin_header')), ('Referer', row.get('observed_referer_header')), ('Set-Cookie response', row.get('observed_set_cookie_header'))) if present) or '(none exposed by this CDP event)'}",
                    f"Failure:           {failure}",
                ]
                stack = list(row.get('script_stack') or [])
                if stack:
                    lines.extend(['', 'SANITIZED JAVASCRIPT CALL CHAIN'])
                    for number, frame in enumerate(stack, 1):
                        lines.append(f"  {number:>2}. {frame.get('label') or ''}")
                lines.extend([
                    '', 'PRIVACY BOUNDARY',
                    'No payloads or full script source are retained. Header names are presence hints only.',
                ])
                body.insert('1.0', '\n'.join(lines)); body.configure(state='disabled')
                bar = tk.Frame(detail, bg=self.ui['bg']); bar.pack(fill='x', padx=12, pady=(0, 12))
                self._feature_button(bar, 'Close', detail.destroy)
                detail.bind('<Escape>', lambda event: detail.destroy())
                return 'break'

            def copy_requests():
                lines = ['Time\tHostname\tRelation\tMethod\tResource\tStatus\tBytes\tDelivery\tPurpose\tInitiator\tScript caller\tConnection']
                lines.extend('\t'.join(str(value) for value in req_values(row)) for row in req_rows['rows'])
                try:
                    self.root.clipboard_clear(); self.root.clipboard_append('\n'.join(lines))
                    req_status.set(f"Copied {len(req_rows['rows'])} request row(s).")
                except Exception:
                    req_status.set('Could not copy request timeline.')

            def close_timeline():
                req_alive['value'] = False
                if req_after.get('id'):
                    try: timeline.after_cancel(req_after['id'])
                    except Exception: pass
                timeline.destroy()

            self._feature_button(req_controls, 'Refresh now', req_refresh)
            self._feature_button(req_controls, 'Copy all', copy_requests)
            self._feature_button(req_controls, 'Details', show_request_details)
            req_tree.bind('<Double-1>', show_request_details)
            tk.Label(req_controls, text='Filter:', bg=self.ui['bg'], fg=self.ui['muted']).pack(side='left', padx=(10, 4))
            entry = tk.Entry(req_controls, textvariable=req_search, width=26, bg=self.ui['field'], fg=self.ui['text'], insertbackground=self.ui['text'], relief='flat')
            entry.pack(side='left', padx=(0, 6))
            entry.bind('<Return>', lambda event: req_refresh())
            tk.Checkbutton(
                req_controls, text='Live', variable=req_live, command=req_refresh,
                bg=self.ui['bg'], fg=self.ui['text'], selectcolor=self.ui['field'], activebackground=self.ui['bg'],
                activeforeground=self.ui['text'], highlightthickness=0, bd=0,
            ).pack(side='left', padx=(4, 4))
            self._feature_button(req_controls, 'Close', close_timeline)
            tk.Label(req_controls, textvariable=req_status, bg=self.ui['bg'], fg=self.ui['muted'], anchor='e').pack(side='right', fill='x', expand=True, padx=(12, 4))
            timeline.protocol('WM_DELETE_WINDOW', close_timeline)
            req_refresh()
            return 'break'

        def toggle_auto():
            if auto_var.get():
                refresh()
            else:
                after_id = refresh_after.get('id')
                if after_id:
                    try:
                        win.after_cancel(after_id)
                    except Exception:
                        pass
                    refresh_after['id'] = None

        def toggle_dns():
            if not dns_var.get():
                dns_pending.clear()
            if last_rows.get('rows'):
                apply_snapshot({'supported': True, 'sockets': last_rows['rows']})

        def close():
            window_alive['value'] = False
            after_id = refresh_after.get('id')
            if after_id:
                try:
                    win.after_cancel(after_id)
                except Exception:
                    pass
            try:
                features.net.stop_live_socket_peer_monitor()
            except Exception:
                pass
            self._network_connections_window = None
            win.destroy()

        self._feature_button(controls, 'Refresh now', refresh)
        self._feature_button(controls, 'Copy all', copy_rows)
        self._feature_button(controls, 'Details', show_selected_details)
        self._feature_button(controls, 'Request timeline', show_request_timeline)
        tree.bind('<Double-1>', show_selected_details)
        tk.Checkbutton(
            controls, text='Live', variable=auto_var, command=toggle_auto,
            bg=self.ui['bg'], fg=self.ui['text'], selectcolor=self.ui['field'],
            activebackground=self.ui['bg'], activeforeground=self.ui['text'],
            highlightthickness=0, bd=0,
        ).pack(side='left', padx=(8, 4))
        tk.Checkbutton(
            controls, text='Resolve hostnames (PTR)', variable=dns_var, command=toggle_dns,
            bg=self.ui['bg'], fg=self.ui['text'], selectcolor=self.ui['field'],
            activebackground=self.ui['bg'], activeforeground=self.ui['text'],
            highlightthickness=0, bd=0,
        ).pack(side='left', padx=(8, 4))
        self._feature_button(controls, 'Close', close)
        tk.Label(
            controls, textvariable=status_var, bg=self.ui['bg'], fg=self.ui['muted'],
            anchor='e', justify='right',
        ).pack(side='right', fill='x', expand=True, padx=(12, 4))

        footer = tk.Label(
            win,
            text='Attribution is RAM-only. Details fetch source on demand; PTR may use DNS.',
            bg=self.ui['bg'], fg=self.ui['muted_dim'], anchor='w', justify='left', wraplength=1650,
        )
        footer.pack(side='bottom', fill='x', padx=18, pady=(0, 4), before=controls)

        win.protocol('WM_DELETE_WINDOW', close)
        refresh()
        return 'break'

    def _show_local_ports(self):
        win = self._new_animated_toplevel(self.root)
        win.title('Tekzite Local Ports & Loopback')
        win.geometry('900x660')
        win.transient(self.root)
        win.configure(bg=self.ui['bg'])
        text = tk.Text(
            win, bg=self.ui['field'], fg=self.ui['text'], insertbackground=self.ui['text'],
            wrap='word', relief='flat', font=(self._ui_monospace_font_family, self._font_size(9)),
        )
        text.pack(fill='both', expand=True, padx=12, pady=12)

        policy = loopback_policy.snapshot()
        lines = [
            'TEKZITE PYTHON LOOPBACK POLICY',
            f"Guard: {'ENABLED' if policy.get('enabled') else 'disabled'}",
            '',
            'Allowed Python loopback destinations:',
        ]
        allowed = policy.get('allowed') or []
        if allowed:
            for row in allowed:
                lines.append(f"  127.0.0.1:{row.get('port')}  [{row.get('owner')}]  {row.get('purpose')}")
        else:
            lines.append('  No Tekzite loopback destination is registered yet.')

        lines.extend([
            '',
            'What these ports do:',
            '  Tekzite Network proxy: local HTTP/HTTPS proxy used for filtering, ad blocking and browser network policy.',
            '  Chromium DevTools/CDP: private control channel used by Tekzite Python to control tabs, input, zoom and diagnostics.',
            '',
            'About numbers such as 127.0.0.1:49563:',
            '  Windows assigns temporary client/source ports for TCP connections. A number like 49563 can therefore be the',
            '  short-lived source side of an allowed connection, not a service listening for outside traffic. Tekzite',
            '  authorizes the stable destination/service port, never the random source port.',
            '',
            'Live loopback TCP rows for Tekzite Python processes:',
        ])
        pids = [os.getpid()]
        try:
            network = features.net._NETWORK_ENGINE or {}
            process = network.get('process')
            helper_pid = getattr(process, 'pid', None)
            if helper_pid:
                pids.append(int(helper_pid))
        except Exception:
            pass
        rows = loopback_policy.live_windows_loopback_connections(pids)
        if rows:
            for row in rows:
                note = row.get('remote_purpose') or row.get('local_purpose')
                purpose = f" — {note.get('purpose')}" if note else ''
                lines.append(
                    f"  PID {row.get('pid')}  {row.get('local')} -> {row.get('remote')}  {row.get('state')}{purpose}"
                )
        elif os.name == 'nt':
            lines.append('  No active loopback TCP row was visible at this instant.')
        else:
            lines.append('  Live TCP enumeration is shown on Windows builds.')

        blocked = loopback_policy.shared_blocked_events() or policy.get('blocked') or []
        lines.extend(['', 'Recent blocked Python loopback attempts:'])
        if blocked:
            for row in blocked:
                lines.append(f"  {row.get('time')}  {row.get('host')}:{row.get('port')}  pid={row.get('pid')} role={row.get('role')} thread={row.get('thread')}")
        else:
            lines.append('  None.')

        lines.extend([
            '',
            'Scope:',
            '  Restricts Tekzite Python loopback only; normal internet and Chromium traffic are unchanged.',
        ])
        text.insert('1.0', '\n'.join(lines))
        text.configure(state='disabled')
        return 'break'

    @staticmethod
    def _memory_mb_for_pid(pid):
        if os.name != 'nt':
            return ''
        try:
            import ctypes
            from ctypes import wintypes
            class PMC(ctypes.Structure):
                _fields_ = [
                    ('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t),
                ]
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            psapi = ctypes.WinDLL('psapi', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            handle = kernel.OpenProcess(0x1000 | 0x0010, False, int(pid))
            if not handle:
                return ''
            try:
                pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
                if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                    return f'{pmc.WorkingSetSize / 1048576:.1f} MB'
            finally:
                kernel.CloseHandle(handle)
        except Exception:
            pass
        return ''

    def _show_task_manager(self):
        win, tree, controls = self._feature_window(
            'Task Manager', ('Type / Tab', 'PID / Target', 'CPU / task time', 'Memory'),
            (300, 190, 140, 130),
        )
        note = tk.StringVar(value='Loading Chromium process information…')
        tk.Label(win, textvariable=note, bg=self.ui['bg'], fg=self.ui['muted']).pack(side='bottom')
        rows = {}

        def refresh():
            tree.delete(*tree.get_children()); rows.clear()
            tab_targets = []
            for tab in self.tabs:
                iid = f'tab:{tab.get("id")}'
                rows[iid] = ('tab', tab.get('id'))
                tree.insert('', 'end', iid=iid, values=(
                    ('☾ ' if tab.get('sleeping') else '') + (tab.get('title') or 'New Tab'),
                    tab.get('chromium_target_id') or 'sleeping / blank', '', '',
                ))
                if tab.get('chromium_target_id'):
                    tab_targets.append((iid, tab.get('chromium_target_id')))
            if not features.net._EDGE_SESSION:
                note.set('Chromium has not started yet.')
                return

            def collect():
                process_info = features.net.get_embedded_chromium_process_info()
                tab_metrics = {}
                for iid, target_id in tab_targets:
                    try:
                        tab_metrics[iid] = features.net.get_embedded_chromium_target_metrics(target_id)
                    except Exception:
                        tab_metrics[iid] = {}
                return process_info, tab_metrics

            future = self._executor.submit(collect)
            def finish():
                if not win.winfo_exists(): return
                if not future.done(): win.after(50, finish); return
                try:
                    info, tab_metrics = future.result()
                except Exception as exc:
                    note.set(str(exc)); return
                for iid, metrics in tab_metrics.items():
                    if not tree.exists(iid): continue
                    values = list(tree.item(iid, 'values'))
                    task_time = float(metrics.get('TaskDuration') or 0.0)
                    heap = float(metrics.get('JSHeapUsedSize') or 0.0)
                    values[2] = f'{task_time:.1f}s'
                    values[3] = f'{heap / 1048576:.1f} MB JS' if heap > 0 else ''
                    tree.item(iid, values=values)
                for index, item in enumerate(info):
                    pid = int(item.get('id') or 0); typ = str(item.get('type') or 'chromium')
                    iid = f'proc:{index}:{pid}'; rows[iid] = ('proc', pid)
                    cpu = float(item.get('cpuTime') or 0.0)
                    tree.insert('', 'end', iid=iid, values=(
                        f'Chromium {typ}', pid, f'{cpu:.1f}s', self._memory_mb_for_pid(pid),
                    ))
                note.set(f'{len(self.tabs)} Tekzite tabs • {len(info)} Chromium processes')
            win.after(20, finish)

        def close_tab():
            sel = tree.selection()
            if not sel: return
            kind, value = rows.get(sel[0], (None, None))
            if kind == 'tab':
                self._close_tab(value); refresh()
            else:
                note.set('For safety, close a tab instead of killing a Chromium process that may be shared.')

        self._feature_button(controls, 'Refresh', refresh)
        self._feature_button(controls, 'Close selected tab', close_tab)
        self._feature_button(controls, 'Close', win.destroy)
        refresh()
        return 'break'

    def _show_profile_manager(self):
        if getattr(self, '_private_mode', False):
            self._show_message("info", 'Profiles','Profile switching is unavailable inside a private window.',parent=self.root); return 'break'
        base=Path(os.environ.get('LOCALAPPDATA') or Path.home())/'Tekzite Browser'; profiles_dir=base/'Profiles'; profiles_dir.mkdir(parents=True,exist_ok=True)
        win,tree,controls=self._feature_window('Profiles',('Profile','Current','Storage'),(320,120,300))
        def sanitize(name):
            name=re.sub(r'[^A-Za-z0-9._ -]+','',str(name or '')).strip().replace(' ','-'); name=re.sub(r'-+','-',name).strip('.-_')
            return name[:48]
        def refresh():
            tree.delete(*tree.get_children()); names=['Default']+sorted([p.name for p in profiles_dir.iterdir() if p.is_dir()])
            for i,name in enumerate(names):
                path=base if name=='Default' else profiles_dir/name
                tree.insert('', 'end', iid=str(i), values=(name,'Yes' if name==getattr(self,'_profile_name','Default') else '',str(path)))
        def open_selected():
            sel=tree.selection()
            if not sel:return
            name=str(tree.item(sel[0],'values')[0]); self._spawn_browser_process(profile=name)
        def create():
            name=self._ask_string_animated('New Profile','Profile name:',parent=win); slug=sanitize(name)
            if not slug or slug=='Default': return
            (profiles_dir/slug).mkdir(parents=True,exist_ok=True); refresh()
        def delete():
            sel=tree.selection()
            if not sel:return
            name=str(tree.item(sel[0],'values')[0])
            if name=='Default' or name==getattr(self,'_profile_name','Default'):
                self._show_message("info", 'Profiles','Default or the currently running profile cannot be deleted here.',parent=win); return
            path=profiles_dir/name
            if self._ask_yes_no('Delete Profile',f'Delete profile {name} and its local browser data?',parent=win):
                try:
                    root_resolved=profiles_dir.resolve()
                    path_resolved=path.resolve()
                    if path.is_symlink() or path_resolved.parent != root_resolved:
                        raise ValueError('Refusing to delete a profile path outside the Profiles directory.')
                    if not features.net.remove_profile_tree(path):
                        raise OSError('Profile directory remained after retry cleanup.')
                except Exception as exc:
                    self._show_message("error", 'Delete Profile',f'Could not safely delete {name}: {exc}',parent=win)
                refresh()
        self._feature_button(controls,'Open',open_selected); self._feature_button(controls,'New',create); self._feature_button(controls,'Delete',delete); self._feature_button(controls,'Close',win.destroy)
        refresh(); return 'break'
