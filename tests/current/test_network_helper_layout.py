from pathlib import Path
import engine.net as net


def test_directory_helper_wins_over_legacy_onefile(tmp_path):
    old = tmp_path / 'tekzite-network.exe'
    old.write_bytes(b'old')
    new = tmp_path / 'network-helper' / 'tekzite-network.exe'
    new.parent.mkdir(); new.write_bytes(b'new')
    assert net._network_helper_executable(tmp_path, old.name) == new


def test_existing_onefile_and_source_layout_remain_compatible(tmp_path):
    path = tmp_path / 'tekzite-network.exe'
    assert net._network_helper_executable(tmp_path, path.name) == path
    path.write_bytes(b'old')
    assert net._network_helper_executable(tmp_path, path.name) == path
