import base64
import hashlib
import io
import json
from pathlib import Path
import struct
import zipfile
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

import extension_updates as updates
import main
from browser_features import BrowserFeatures


def data(version='1.0', **extra):
    return dict(name='Example', manifest_version=3, version=version, permissions=['storage'], **extra)


def package(manifest, files=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('extension/manifest.json', json.dumps(manifest))
        archive.writestr('extension/code.js', 'new code')
        for name, value in (files or {}).items():
            info = zipfile.ZipInfo('placeholder')
            info.filename = name  # Preserve hostile separators on Windows too.
            archive.writestr(info, value)
    return stream.getvalue()


def field(number, value):
    def varint(number):
        output = bytearray()
        while number > 127:
            output.append((number & 127) | 128); number >>= 7
        output.append(number)
        return bytes(output)
    return varint((number << 3) | 2) + varint(len(value)) + value


def signed_crx(payload, algorithm):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048) if algorithm == 'rsa' else ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    signed = field(1, hashlib.sha256(public).digest()[:16])
    message = b'CRX3 SignedData\x00' + struct.pack('<I', len(signed)) + signed + payload
    signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256()) if algorithm == 'rsa' else key.sign(message, ec.ECDSA(hashes.SHA256()))
    proof = field(1, public) + field(2, signature)
    header = field(2 if algorithm == 'rsa' else 3, proof) + field(10000, signed)
    return b'Cr24' + struct.pack('<II', 3, len(header)) + header + payload, base64.b64encode(public).decode()


@pytest.mark.parametrize('algorithm', ['rsa', 'ecdsa'])
def test_crx_signature_and_signer_are_verified(algorithm):
    payload = package(data('2.0'))
    crx, key = signed_crx(payload, algorithm)
    assert updates.verified_crx(crx, key) == payload
    with pytest.raises(Exception):
        updates.verified_crx(crx[:-1] + bytes([crx[-1] ^ 1]), key)
    _, wrong = signed_crx(payload, algorithm)
    with pytest.raises(ValueError, match='identity'):
        updates.verified_crx(crx, wrong)


def test_automatic_source_discovery():
    assert updates.discover_source(data(name_override='unused')) is None
    assert updates.discover_source({'name': 'uBlock Origin', 'author': 'Raymond Hill & contributors'}) == {'kind': 'github', 'repository': 'gorhill/uBlock', 'asset': '*.chromium.zip'}
    assert updates.discover_source(data(homepage_url='https://github.com/owner/project#docs')) == {'kind': 'github', 'repository': 'owner/project'}
    _, key = signed_crx(b'archive', 'rsa')
    source = updates.discover_source(data(key=key, update_url='https://clients2.google.com/service/update2/crx'))
    assert source['kind'] == 'crx' and len(source['id']) == 32
    assert updates.discover_source(data(homepage_url='https://github.com.attacker.test/owner/repo')) is None


@pytest.mark.parametrize('url', ['http://example.com/update', 'https://user:secret@example.com/update', 'file:///etc/passwd'])
def test_update_transport_requires_https_without_credentials(url):
    with pytest.raises(ValueError):
        updates.https_url(url)


@pytest.mark.parametrize('filename', ['../outside', '/outside', 'x\\outside', 'x:stream', 'CON.txt', 'x./code.js'])
def test_zip_paths_are_validated_before_extraction(tmp_path, filename):
    with pytest.raises(ValueError, match='Unsafe'):
        updates.unpack(package(data('2.0'), {filename: 'unsafe'}), tmp_path / 'unpack')
    assert not (tmp_path / 'outside').exists()


def test_zip_symlinks_are_rejected(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        link = zipfile.ZipInfo('link'); link.external_attr = 0o120777 << 16
        archive.writestr(link, '../outside')
    with pytest.raises(ValueError):
        updates.unpack(stream.getvalue(), tmp_path)


@pytest.fixture
def installed(tmp_path, monkeypatch):
    path = tmp_path / 'installed'; path.mkdir()
    old = data(homepage_url='https://github.com/owner/project')
    (path / 'manifest.json').write_text(json.dumps(old))
    (path / 'code.js').write_text('old code')
    profile = tmp_path / 'profile'; profile.mkdir()
    (profile / 'extension-settings.json').write_text('user settings')
    entries = [{'path': str(path), 'enabled': True, 'pinned': False}]
    payload = package(data('2.0', homepage_url='https://github.com/owner/project'))
    calls = []
    def fetch(url, limit=updates.MAX_PACKAGE):
        calls.append(url)
        if url.endswith('/releases/latest'):
            return json.dumps({'assets': [{'name': 'extension.chromium.zip', 'browser_download_url': 'https://github.com/owner/project/releases/download/v2/extension.chromium.zip', 'digest': 'sha256:' + hashlib.sha256(payload).hexdigest()}]}).encode()
        return payload
    monkeypatch.setattr(updates, 'fetch', fetch)
    return path, profile, entries, calls


def test_update_stages_then_applies_on_restart_preserving_identity_and_settings(installed):
    path, profile, entries, calls = installed
    result = updates.check_updates(entries, profile, '150.0')
    assert result[updates.token(path)]['state'] == 'staged'
    assert updates.manifest(path)['version'] == '1.0'
    assert (path / 'code.js').read_text() == 'old code'
    assert updates.apply_pending(entries, profile)[0]['state'] == 'updated'
    assert updates.manifest(path)['version'] == '2.0'
    assert (path / 'code.js').read_text() == 'new code'
    assert (profile / 'extension-settings.json').read_text() == 'user settings'
    assert entries[0]['path'] == str(path) and entries[0]['pinned'] is False
    assert not list(path.parent.glob('.tekzite-extension-*'))


def test_interval_and_forced_check(installed):
    path, profile, entries, calls = installed
    updates.check_updates(entries, profile, '150.0')
    count = len(calls)
    updates.check_updates(entries, profile, '150.0')
    assert len(calls) == count
    result = updates.check_updates(entries, profile, '150.0', force=True)
    assert len(calls) > count
    assert result[updates.token(path)]['state'] == 'staged'


def test_failed_update_never_changes_installed_extension(installed, monkeypatch):
    path, profile, entries, _ = installed
    monkeypatch.setattr(updates, 'fetch', Mock(side_effect=OSError('offline')))
    result = updates.check_updates(entries, profile, '150.0')
    assert result[updates.token(path)]['state'] == 'error'
    assert updates.apply_pending(entries, profile) == []
    assert updates.manifest(path)['version'] == '1.0'


def test_disabled_extension_has_no_update_requests(installed):
    path, profile, entries, calls = installed
    entries[0]['enabled'] = False
    assert updates.check_updates(entries, profile, '150.0') == {}
    assert calls == []


def test_swap_failure_rolls_back(installed, monkeypatch):
    path, profile, entries, _ = installed
    updates.check_updates(entries, profile, '150.0')
    rename = Path.rename
    def fail_replacement(self, target):
        if self.name.startswith('.tekzite-extension-update-'):
            raise OSError('file locked')
        return rename(self, target)
    monkeypatch.setattr(Path, 'rename', fail_replacement)
    assert updates.apply_pending(entries, profile)[0]['state'] == 'error'
    assert updates.manifest(path)['version'] == '1.0'
    assert (path / 'code.js').read_text() == 'old code'


def test_incomplete_stage_is_not_applied(installed):
    path, profile, entries, _ = installed
    stage = updates.cache_dir(profile) / updates.token(path)
    stage.mkdir(parents=True)
    (stage / 'manifest.json').write_text(json.dumps(data('2.0')))
    assert updates.apply_pending(entries, profile) == []
    assert updates.manifest(path)['version'] == '1.0'


@pytest.mark.parametrize('change', [{'name': 'Another'}, {'manifest_version': 2}, {'permissions': ['storage', 'debugger']}, {'minimum_chrome_version': '999.0'}])
def test_incompatible_updates_are_rejected(change):
    new = data('2.0'); new.update(change)
    with pytest.raises(ValueError):
        updates.compatible(data(), new, '150.0')


def test_keyless_unpacked_id_remains_path_based():
    new = data('2.0', key='downloaded key')
    assert updates.compatible(data(), new, '150.0')
    assert 'key' not in new


def test_preference_migration_enables_automatic_checks():
    assert main.DEFAULT_PREFERENCES['extensions_auto_update']
    assert main._normalized_extension_entries([{'path': 'extension'}])[0]['auto_update']


def test_private_mode_never_checks_extensions():
    app = Mock()
    app._closing = False; app._private_mode = True
    assert not BrowserFeatures._start_extension_updates(app, force=True)
    app._executor.submit.assert_not_called()


def test_automatic_checks_respect_global_opt_out():
    app = Mock()
    app._closing = False; app._private_mode = False
    app.preferences = {'extensions_auto_update': False}
    assert not BrowserFeatures._start_extension_updates(app)
    app._executor.submit.assert_not_called()


def test_crx_update_manifest_selects_matching_identity(monkeypatch):
    payload = package(data('2.0'))
    crx, key = signed_crx(payload, 'rsa')
    old = data(key=key, update_url='https://example.com/updates.xml')
    source = updates.discover_source(old)
    xml = f'<gupdate xmlns="http://www.google.com/update2/response"><app appid="{source["id"]}" status="ok"><updatecheck codebase="https://example.com/new.crx" version="2.0"/></app></gupdate>'.encode()
    calls = []
    def fetch(url, limit=updates.MAX_PACKAGE):
        calls.append(url)
        return crx if url.endswith('.crx') else xml
    monkeypatch.setattr(updates, 'fetch', fetch)
    assert updates.release_package(source, old, '150.0') == (payload, '2.0')
    assert 'prodversion=150.0' in calls[0] and 'acceptformat=crx3' in calls[0]
    assert source['id'] in calls[0]


def test_changed_signing_key_is_rejected():
    with pytest.raises(ValueError, match='signing key'):
        updates.compatible(data(key='original'), data('2.0', key='different'), '150.0')


def test_bad_github_checksum_never_stages(installed, monkeypatch):
    path, profile, entries, _ = installed
    payload = package(data('2.0'))
    def fetch(url, limit=updates.MAX_PACKAGE):
        if url.endswith('/releases/latest'):
            return json.dumps({'assets': [{'name': 'chrome.zip', 'browser_download_url': 'https://github.com/owner/project/releases/download/v2/chrome.zip', 'digest': 'sha256:' + '0' * 64}]}).encode()
        return payload
    monkeypatch.setattr(updates, 'fetch', fetch)
    result = updates.check_updates(entries, profile, '150.0')
    assert 'checksum' in result[updates.token(path)]['error']
    assert updates.apply_pending(entries, profile) == []


def test_unknown_source_is_reported_without_network(installed, monkeypatch):
    path, profile, entries, calls = installed
    (path / 'manifest.json').write_text(json.dumps(data()))
    result = updates.check_updates(entries, profile, '150.0')
    assert result[updates.token(path)]['state'] == 'no-source'
    assert calls == []


def test_manual_change_after_staging_is_not_overwritten(installed):
    path, profile, entries, _ = installed
    updates.check_updates(entries, profile, '150.0')
    (path / 'manifest.json').write_text(json.dumps(data('1.5')))
    assert updates.apply_pending(entries, profile)[0]['state'] == 'error'
    assert updates.manifest(path)['version'] == '1.5'


def test_pre_swap_crash_recovers_original_folder(installed):
    path, profile, entries, _ = installed
    updates.check_updates(entries, profile, '150.0')
    backup = path.parent / ('.tekzite-extension-backup-' + updates.token(path))
    path.rename(backup)
    assert updates.apply_pending(entries, profile)[0]['state'] == 'updated'
    assert updates.manifest(path)['version'] == '2.0'


def test_store_source_can_be_derived_from_signing_key():
    _, key = signed_crx(b'archive', 'rsa')
    source = updates.discover_source(data(key=key))
    assert source['url'] == 'https://clients2.google.com/service/update2/crx'


def test_live_update_is_confirmed_before_backup_is_removed(installed):
    path, profile, entries, _ = installed
    updates.check_updates(entries, profile, '150.0')
    def reload(path_value, expected):
        assert path_value == str(path)
        assert expected == '2.0'
        assert updates.manifest(path)['version'] == expected
        assert list(path.parent.glob('.tekzite-extension-backup-*'))
        return True
    assert updates.apply_pending(entries, profile, reload_extension=reload)[0]['state'] == 'updated'
    assert not list(path.parent.glob('.tekzite-extension-backup-*'))


def test_failed_live_reload_restores_files_and_old_runtime(installed):
    path, profile, entries, _ = installed
    updates.check_updates(entries, profile, '150.0')
    calls = []
    def reload(path_value, expected):
        calls.append(expected)
        assert updates.manifest(path)['version'] == expected
        if expected == '2.0':
            raise RuntimeError('Runtime rejected update')
        return True
    result = updates.apply_pending(entries, profile, reload_extension=reload)
    assert result[0]['state'] == 'error'
    assert calls == ['2.0', '1.0']
    assert updates.manifest(path)['version'] == '1.0'
    assert (profile / 'extension-settings.json').read_text() == 'user settings'
