"""Discover, verify and stage unpacked-extension updates for the next startup."""
import base64
import fnmatch
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from browser_state import read_json, write_json

INTERVAL = 24 * 60 * 60
MAX_PACKAGE = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
_LOCK = threading.Lock()


def version(value):
    if not re.fullmatch(r"\d+(?:\.\d+){0,3}", str(value)):
        raise ValueError("Invalid extension version")
    parts = tuple(int(p) for p in str(value).split('.'))
    if any(p > 65535 for p in parts):
        raise ValueError("Invalid extension version")
    return parts + (0,) * (4 - len(parts))


def manifest(path):
    data = json.loads((Path(path) / 'manifest.json').read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('manifest_version') not in (2, 3):
        raise ValueError("Unsupported extension manifest")
    version(data.get('version'))
    if not data.get('name'):
        raise ValueError("Missing extension name")
    return data


def extension_id(key):
    public = base64.b64decode(key, validate=True)
    return ''.join(chr(ord('a') + int(c, 16)) for c in hashlib.sha256(public).hexdigest()[:32])


def https_url(url):
    parts = urllib.parse.urlsplit(str(url))
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError("Extension updates require HTTPS")
    return str(url)


def discover_source(data):
    # uBO's Chromium ZIP is distributed by its author, including builds no
    # longer distributed through the Web Store. Preserve the classic MV2 build.
    if data.get('name') == 'uBlock Origin' and 'Raymond Hill' in str(data.get('author') or ''):
        return {'kind': 'github', 'repository': 'gorhill/uBlock', 'asset': '*.chromium.zip'}
    if data.get('key'):
        identity = extension_id(data['key'])
        url = data.get('update_url')
        if url:
            return {'kind': 'crx', 'id': identity, 'url': https_url(url)}
    for field in ('homepage_url', 'website', 'url'):
        url = data.get(field)
        if not isinstance(url, str):
            continue
        parts = urllib.parse.urlsplit(url)
        if parts.scheme == 'https' and parts.hostname == 'github.com' and not parts.username:
            segments = parts.path.strip('/').split('/')
            if len(segments) >= 2 and all(re.fullmatch(r'[\w.-]+', s) for s in segments[:2]):
                return {'kind': 'github', 'repository': '/'.join(segments[:2]).removesuffix('.git')}
    if data.get('key'):
        return {'kind': 'crx', 'id': extension_id(data['key']), 'url': 'https://clients2.google.com/service/update2/crx'}
    return None


class _HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit=MAX_PACKAGE):
    request = urllib.request.Request(https_url(url), headers={'User-Agent': 'Tekzite-Extension-Updater', 'Accept': '*/*'})
    # No browser cookies or credentials are shared with update servers.
    with urllib.request.build_opener(_HTTPSRedirect()).open(request, timeout=20) as response:
        https_url(response.geturl())
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Extension update exceeds size limit")
    return data


def _protobuf(data):
    """Read only bounded protobuf wire fields needed by Chromium's CRX3 header."""
    index = 0
    def number():
        nonlocal index
        value = 0
        for shift in range(0, 70, 7):
            if index >= len(data):
                raise ValueError("Truncated CRX header")
            byte = data[index]; index += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                return value
        raise ValueError("Invalid CRX integer")
    fields = {}
    while index < len(data):
        tag = number(); field, wire = tag >> 3, tag & 7
        if not field:
            raise ValueError("Invalid CRX field")
        if wire == 2:
            length = number()
            if length > len(data) - index:
                raise ValueError("Truncated CRX field")
            fields.setdefault(field, []).append(data[index:index + length]); index += length
        elif wire == 0:
            number()
        elif wire in (1, 5):
            index += 8 if wire == 1 else 4
            if index > len(data):
                raise ValueError("Truncated CRX field")
        else:
            raise ValueError("Unsupported CRX field")
    return fields


def verified_crx(data, expected_key):
    # Format and signature domain follow Chromium components/crx_file/crx3.proto.
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    if len(data) < 12 or data[:4] != b'Cr24' or struct.unpack_from('<I', data, 4)[0] != 3:
        raise ValueError("Only signed CRX3 updates are supported")
    length = struct.unpack_from('<I', data, 8)[0]
    if length > 1024 * 1024 or length > len(data) - 12:
        raise ValueError("Invalid CRX header size")
    header = _protobuf(data[12:12 + length]); archive = data[12 + length:]
    signed_values = header.get(10000, [])
    if len(signed_values) != 1:
        raise ValueError("Missing CRX signed header")
    signed = signed_values[0]
    public = base64.b64decode(expected_key, validate=True)
    if _protobuf(signed).get(1) != [hashlib.sha256(public).digest()[:16]]:
        raise ValueError("CRX extension identity changed")
    message = b'CRX3 SignedData\x00' + struct.pack('<I', len(signed)) + signed + archive
    for kind in (2, 3):
        for proof in header.get(kind, []):
            values = _protobuf(proof)
            if values.get(1) != [public] or len(values.get(2, [])) != 1:
                continue
            key = serialization.load_der_public_key(public)
            signature = values[2][0]
            if kind == 2 and isinstance(key, rsa.RSAPublicKey):
                key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
            elif kind == 3 and isinstance(key, ec.EllipticCurvePublicKey):
                key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
            else:
                continue
            return archive
    raise ValueError("Missing valid extension signer proof")


def release_package(source, old, chrome_version):
    if source['kind'] == 'github':
        repo = source['repository']
        release = json.loads(fetch(f'https://api.github.com/repos/{repo}/releases/latest', 2 * 1024 * 1024))
        if release.get('draft') or release.get('prerelease'):
            return None
        assets = [a for a in release.get('assets', []) if isinstance(a, dict)
                  and str(a.get('name', '')).endswith('.zip')
                  and not re.search(r'firefox|thunderbird|safari', str(a.get('name')), re.I)]
        pattern = source.get('asset')
        if pattern:
            assets = [a for a in assets if fnmatch.fnmatchcase(a['name'], pattern)]
        elif len(assets) > 1:
            assets = [a for a in assets if re.search(r'chromium|chrome', a['name'], re.I)]
        if len(assets) != 1:
            raise ValueError("No unambiguous Chromium release ZIP")
        asset = assets[0]
        url = asset['browser_download_url']
        parts = urllib.parse.urlsplit(url)
        if parts.hostname != 'github.com' or not parts.path.startswith('/' + repo + '/releases/download/'):
            raise ValueError("Release asset is outside its source repository")
        payload = fetch(url)
        digest = str(asset.get('digest') or '')
        if digest.startswith('sha256:') and hashlib.sha256(payload).hexdigest() != digest[7:]:
            raise ValueError("Extension package checksum mismatch")
        return payload, None
    query = urllib.parse.urlencode({'x': urllib.parse.urlencode({'id': source['id'], 'v': old['version'], 'uc': ''}),
                                    'prodversion': chrome_version, 'acceptformat': 'crx3', 'response': 'updatecheck'})
    url = source['url'] + ('&' if '?' in source['url'] else '?') + query
    xml = fetch(url, 2 * 1024 * 1024)
    if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
        raise ValueError("Unsupported update XML")
    root = ET.fromstring(xml)
    for app in root.iter():
        if app.tag.split('}')[-1] != 'app' or app.get('appid') != source['id']:
            continue
        if app.get('status', 'ok') != 'ok':
            raise ValueError("Update service does not recognize this extension")
        for check in app:
            if check.tag.split('}')[-1] != 'updatecheck' or not check.get('codebase'):
                continue
            if version(check.get('version')) <= version(old['version']):
                return None
            minimum = check.get('prodversionmin')
            if minimum and version(minimum) > version(chrome_version):
                raise ValueError("Update requires a newer Chromium version")
            return verified_crx(fetch(check.get('codebase')), old['key']), check.get('version')
        return None
    raise ValueError("Update manifest does not identify this extension")


def unpack(payload, target):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) > 10000 or sum(m.file_size for m in members) > MAX_EXPANDED:
            raise ValueError("Extension ZIP exceeds extraction limits")
        seen = set()
        for item in members:
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (path.is_absolute() or '..' in path.parts or '\\' in item.orig_filename or '\x00' in item.orig_filename or ':' in item.filename
                    or stat.S_ISLNK(mode) or str(path).casefold() in seen
                    or any(p.rstrip(' .') != p or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p) for p in path.parts)):
                raise ValueError("Unsafe extension ZIP path")
            seen.add(str(path).casefold())
        archive.extractall(target)
    roots = list(Path(target).rglob('manifest.json'))
    if (Path(target) / 'manifest.json').is_file():
        return Path(target)
    if len(roots) != 1:
        raise ValueError("Extension ZIP has no unique manifest")
    return roots[0].parent


def compatible(old, new, chrome_version):
    if version(new['version']) <= version(old['version']):
        return False
    if old['name'] != new['name'] or old['manifest_version'] != new['manifest_version']:
        raise ValueError("Extension identity or manifest generation changed")
    if old.get('key') and new.get('key') and old['key'] != new['key']:
        raise ValueError("Extension signing key changed")
    if new.get('minimum_chrome_version') and version(new['minimum_chrome_version']) > version(chrome_version):
        raise ValueError("Update requires a newer Chromium version")
    for field in ('permissions', 'host_permissions', 'optional_permissions', 'optional_host_permissions'):
        if set(new.get(field) or []) - set(old.get(field) or []):
            raise ValueError("New permissions require a manual extension update")
    old_matches = {p for script in old.get('content_scripts', []) for p in script.get('matches', [])}
    new_matches = {p for script in new.get('content_scripts', []) for p in script.get('matches', [])}
    if new_matches - old_matches:
        raise ValueError("New site access requires a manual extension update")
    # Retain path-derived IDs for old keyless unpacked installations too.
    if old.get('key'):
        new['key'] = old['key']
    else:
        new.pop('key', None)
    return True


def token(path):
    return hashlib.sha256(os.path.normcase(str(Path(path).resolve())).encode()).hexdigest()[:24]


def cache_dir(state_directory):
    return Path(state_directory) / 'extension-updates'


def check_updates(entries, state_directory, chrome_version, *, force=False):
    with _LOCK:
        cache = cache_dir(state_directory); cache.mkdir(parents=True, exist_ok=True)
        records = read_json(cache / 'status.json', {})
        if not isinstance(records, dict):
            records = {}
        for row in entries:
            if not row.get('enabled', True) or not row.get('auto_update', True):
                continue
            path = row['path']; ident = token(path)
            previous = records.get(ident) or {}
            if not force and time.time() - float(previous.get('checked_at') or 0) < (3600 if previous.get('state') == 'error' else INTERVAL):
                continue
            record = {'checked_at': time.time(), 'state': 'up-to-date'}
            try:
                old = manifest(path); source = discover_source(old)
                record.update(name=old['name'], installed_version=old['version'], source=source, phase='source-discovery')
                if not source:
                    record['state'] = 'no-source'
                else:
                    record['phase'] = 'download-and-validation'
                    package = release_package(source, old, chrome_version)
                    if package:
                        payload, expected_version = package
                        stage = cache / ident
                        ready = cache / (ident + '.ready.json')
                        ready.unlink(missing_ok=True)
                        if stage.exists():
                            shutil.rmtree(stage)
                        with tempfile.TemporaryDirectory(dir=cache) as tmp:
                            root = unpack(payload, tmp); new = manifest(root)
                            if expected_version and new['version'] != expected_version:
                                raise ValueError("Package version differs from update manifest")
                            if compatible(old, new, chrome_version):
                                (root / 'manifest.json').write_text(json.dumps(new, indent=2), encoding='utf-8')
                                shutil.copytree(root, stage)
                                write_json(ready, {'base': old['version'], 'version': new['version']})
                                record.update(state='staged', version=new['version'], base=old['version'], phase='activation-pending')
                # A forced check for the same release must retain an existing stage.
                if record['state'] == 'up-to-date' and (cache / (ident + '.ready.json')).is_file() and (cache / ident / 'manifest.json').is_file():
                    record.update(state='staged', version=manifest(cache / ident)['version'], base=old['version'])
            except Exception as exc:
                record.update(state='error', error=str(exc))
            if record['state'] in ('up-to-date', 'no-source'):
                record['phase'] = 'complete'
            records[ident] = record
        write_json(cache / 'status.json', records)
        return {token(row['path']): records[token(row['path'])] for row in entries
                if row.get('enabled', True) and row.get('auto_update', True) and token(row['path']) in records}


def apply_pending(entries, state_directory, reload_extension=None):
    """Swap files and optionally confirm live reload before discarding backup."""
    results = []
    cache = cache_dir(state_directory)
    for row in entries:
        if not row.get('enabled', True) or not row.get('auto_update', True):
            continue
        path = Path(row['path']); ident = token(path)
        stage = cache / ident
        ready_path = cache / (ident + '.ready.json')
        backup = path.parent / ('.tekzite-extension-backup-' + ident)
        replacement = path.parent / ('.tekzite-extension-update-' + ident)
        try:
            if backup.exists() and not path.exists():
                backup.rename(path)
            if not ready_path.is_file() or not (stage / 'manifest.json').is_file():
                continue
            old = manifest(path); new = manifest(stage)
            ready = read_json(ready_path, {})
            if backup.exists() and old['version'] == ready.get('version'):
                shutil.rmtree(backup)
                shutil.rmtree(stage)
                ready_path.unlink(missing_ok=True)
                results.append({'path': str(path), 'state': 'updated', 'version': old['version']})
                continue
            if ready.get('base') != old['version'] or ready.get('version') != new['version']:
                raise ValueError("Extension changed after staging; check updates again")
            if version(new['version']) <= version(old['version']):
                shutil.rmtree(stage)
                ready_path.unlink(missing_ok=True)
                continue
            if not compatible(old, new, '65535.65535.65535.65535'):
                continue
            if replacement.exists():
                shutil.rmtree(replacement)
            shutil.copytree(stage, replacement)
            if backup.exists():
                shutil.rmtree(backup)
            path.rename(backup)
            try:
                replacement.rename(path)
            except Exception:
                backup.rename(path)
                raise
            if reload_extension is not None:
                try:
                    if reload_extension(str(path), new['version']) is not True:
                        raise RuntimeError("Extension reload was not confirmed")
                except Exception as exc:
                    shutil.rmtree(path)
                    backup.rename(path)
                    try:
                        reload_extension(str(path), old['version'])
                    except Exception as recovery_error:
                        raise RuntimeError(f"{exc}; old files restored but runtime recovery failed: {recovery_error}") from exc
                    raise
            shutil.rmtree(backup)
            shutil.rmtree(stage)
            ready_path.unlink(missing_ok=True)
            results.append({'path': str(path), 'state': 'updated', 'version': new['version']})
        except Exception as exc:
            results.append({'path': str(path), 'state': 'error', 'error': str(exc)})
    if results:
        records = read_json(cache / 'status.json', {})
        if not isinstance(records, dict):
            records = {}
        for result in results:
            ident = token(result['path'])
            record = records.setdefault(ident, {})
            record.update({key: value for key, value in result.items() if key != 'path'})
            record['phase'] = 'active' if result['state'] == 'updated' else 'activation'
        write_json(cache / 'status.json', records)
    return results


def update_summary(entries, results):
    results = results if isinstance(results, dict) else {}
    eligible = [row for row in entries if row.get('enabled', True) and row.get('auto_update', True)]
    rows = [results.get(token(row['path']), {}) for row in eligible]
    counts = {state: sum(row.get('state') == state for row in rows)
              for state in ('updated', 'staged', 'up-to-date', 'no-source', 'error')}
    if results.get('check', {}).get('state') == 'error':
        counts['error'] += 1
    if counts['error']:
        return f"{counts['error']} update check(s) failed. Use Copy Update Debug."
    if not eligible:
        return 'No eligible user extensions to check. Built-in services update with Tekzite.'
    if counts['updated'] or counts['staged']:
        return f"{counts['updated']} updated and active; {counts['staged']} awaiting activation; {counts['up-to-date']} up to date; {counts['no-source']} without a source."
    unchecked = sum(not row.get('state') for row in rows)
    if unchecked:
        return f"{unchecked} extension(s) not checked yet. Use Check updates."
    return f"{counts['up-to-date']} up to date; {counts['no-source']} without an update source."


def _debug_url(value):
    parts = urllib.parse.urlsplit(str(value or ''))
    return urllib.parse.urlunsplit((parts.scheme, parts.hostname or '', parts.path, '', ''))


def _debug_error(value, entries):
    text = str(value or '')
    for row in entries:
        path = str(row.get('path') or '')
        if path:
            text = text.replace(path, '<extension>')
            parent = str(Path(path).parent)
            if len(parent) > 1:
                text = text.replace(parent, '<extension-parent>')
    text = re.sub(r'https?://[^\s\'"<>]+', lambda match: _debug_url(match.group()), text)
    return text[:600]


def build_debug_report(entries, state_directory, *, results=None, runtime=None, context=None):
    """Allowlisted diagnostics without cookies, signing keys or profile folders."""
    records = read_json(cache_dir(state_directory) / 'status.json', {})
    if not isinstance(records, dict):
        records = {}
    if isinstance(results, dict):
        records.update(results)
    report = {'schema': 1, 'summary': update_summary(entries, records), 'extensions': []}
    report['context'] = {key: value for key, value in (context or {}).items()
                         if key in ('browser_version', 'chromium_version', 'chromium_running',
                                    'check_running', 'automatic_updates', 'private_mode', 'authentication_active')}
    if records.get('check', {}).get('error'):
        report['check_error'] = _debug_error(records['check']['error'], entries)
    for row in entries:
        path = row.get('path') or ''; record = records.get(token(path), {})
        item = {'enabled': bool(row.get('enabled', True)),
                'automatic_updates': bool(row.get('auto_update', True)),
                'folder_exists': Path(path).is_dir(),
                'state': record.get('state', 'not-checked'), 'phase': record.get('phase'),
                'checked_at': record.get('checked_at'), 'target_version': record.get('version')}
        if not item['enabled'] or not item['automatic_updates']:
            item['state'] = 'disabled' if not item['enabled'] else 'updates-disabled'
        try:
            data = manifest(path)
            item.update(name=data['name'], installed_version=data['version'],
                        manifest_version=data['manifest_version'], signing_key_present=bool(data.get('key')),
                        update_url_present=bool(data.get('update_url')))
            source = discover_source(data)
            item['source'] = ({'kind': source['kind'], 'repository': source.get('repository'),
                               'extension_id': source.get('id'),
                               'url': _debug_url(source.get('url'))} if source else None)
        except Exception as exc:
            item['manifest_error'] = _debug_error(exc, entries)
        if record.get('error'):
            item['error'] = _debug_error(record['error'], entries)
        report['extensions'].append(item)
    report['runtime_extensions'] = [{key: row.get(key) for key in ('id', 'name', 'version', 'enabled', 'installType')}
                                    for row in (runtime or []) if isinstance(row, dict)]
    return report
