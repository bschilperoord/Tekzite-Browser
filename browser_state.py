"""Small, atomic local bookmark and session files, independent of Chromium data."""
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def valid_url(value):
    if not isinstance(value, str) or len(value) > 32768:
        return False
    try:
        parts = urlsplit(value)
        return parts.scheme in ('http', 'https', 'file') and bool(parts.netloc or (parts.scheme == 'file' and parts.path))
    except ValueError:
        return False


def _backup_path(path):
    path = Path(path)
    return path.with_name(path.name + '.bak')


def _decode_json_bytes(payload):
    try:
        return json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, ValueError, TypeError):
        return None


def read_json(path, default):
    """Read local state, falling back to the previous valid generation.

    The primary file remains authoritative.  The .bak file is consulted only
    when the primary exists but cannot be read/decoded, so intentionally
    deleting a state file never resurrects stale data.
    """
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        if not path.exists():
            return default
    try:
        return json.loads(_backup_path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        return default


def _write_backup(path, payload):
    """Best-effort atomic backup; backup failure must not fail the save."""
    backup = _backup_path(path)
    fd, temporary = tempfile.mkstemp(prefix=backup.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(temporary, backup)
    except OSError:
        pass
    finally:
        if os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def write_json(path, value):
    """Atomically commit JSON and retain one previous valid generation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = None
    try:
        candidate = path.read_bytes()
        if _decode_json_bytes(candidate) is not None:
            previous = candidate
    except OSError:
        pass

    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if previous is not None:
            _write_backup(path, previous)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_bookmarks(path):
    data = read_json(path, [])
    if not isinstance(data, list):
        return []
    result, seen = [], set()
    for item in data:
        if not isinstance(item, dict) or not valid_url(item.get('url')):
            continue
        url = item['url']
        if url not in seen:
            result.append({'url': url, 'title': str(item.get('title') or url)})
            seen.add(url)
    return result


def session_snapshot(tabs, active_id):
    result, active = [], 0
    for tab in tabs:
        url = tab.get('url') or ''
        if url and not valid_url(url):
            continue
        if tab.get('id') == active_id:
            active = len(result)
        saved = {'url': url, 'title': str(tab.get('title') or 'New Tab')}
        if tab.get('pinned'):
            saved['pinned'] = True
        group = str(tab.get('group') or '').strip()
        if group:
            saved['group'] = group[:64]
        result.append(saved)
    return {'tabs': result, 'active': active}


def load_session(path):
    data = read_json(path, {})
    if not isinstance(data, dict) or not isinstance(data.get('tabs'), list):
        return {'tabs': [], 'active': 0}
    tabs = [dict(t, id=i) for i, t in enumerate(data['tabs']) if isinstance(t, dict)]
    active = data.get('active', 0)
    result = session_snapshot(tabs, active if type(active) is int else 0)
    if 'clean_exit' in data:
        result['clean_exit'] = bool(data['clean_exit'])
    return result
