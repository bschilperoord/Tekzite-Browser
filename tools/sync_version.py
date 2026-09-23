"""Synchronize Tekzite Browser release-version metadata.

Usage:
    python tools/sync_version.py 10.5.63

This intentionally updates release metadata and the active regression-suite
version pins, but does not rewrite historical changelog entries.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = r"\d+\.\d+\.\d+"


def _replace(path: Path, pattern: str, replacement: str, *, count: int = 0) -> int:
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, replacement, text, count=count)
    if n:
        path.write_text(new, encoding="utf-8")
    return n


def sync(version: str) -> list[str]:
    if not re.fullmatch(VERSION_RE, version):
        raise ValueError(f"Invalid version: {version!r}")
    major, minor, patch = (int(x) for x in version.split("."))
    changed: list[str] = []

    def mark(path: Path, n: int) -> None:
        if n and str(path.relative_to(ROOT)) not in changed:
            changed.append(str(path.relative_to(ROOT)))

    path = ROOT / "main.py"
    mark(path, _replace(path, rf'BROWSER_VERSION = "{VERSION_RE}"', f'BROWSER_VERSION = "{version}"', count=1))

    path = ROOT / "tekzite_browser.manifest"
    mark(path, _replace(path, rf'<assemblyIdentity version="{VERSION_RE}\.0"', f'<assemblyIdentity version="{version}.0"', count=1))

    path = ROOT / "tekzite_version_info.txt"
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"filevers=\(\d+,\s*\d+,\s*\d+,\s*0\)", f"filevers=({major}, {minor}, {patch}, 0)", text, count=1)
    new = re.sub(r"prodvers=\(\d+,\s*\d+,\s*\d+,\s*0\)", f"prodvers=({major}, {minor}, {patch}, 0)", new, count=1)
    new = re.sub(r"StringStruct\(u'FileVersion', u'[^']+'\)", f"StringStruct(u'FileVersion', u'{version}')", new, count=1)
    new = re.sub(r"StringStruct\(u'ProductVersion', u'[^']+'\)", f"StringStruct(u'ProductVersion', u'{version}')", new, count=1)
    if new != text:
        path.write_text(new, encoding="utf-8")
        changed.append(str(path.relative_to(ROOT)))

    path = ROOT / "installer" / "TekziteBrowser.iss"
    mark(path, _replace(path, rf'#define MyAppVersion "{VERSION_RE}"', f'#define MyAppVersion "{version}"', count=1))

    path = ROOT / "installer" / "README.txt"
    mark(path, _replace(path, rf"Tekzite-Browser-Setup-{VERSION_RE}\.exe", f"Tekzite-Browser-Setup-{version}.exe"))

    path = ROOT / "chromium_zoom_extension" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        manifest["version"] = version
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        changed.append(str(path.relative_to(ROOT)))

    path = ROOT / "README.md"
    mark(path, _replace(path, rf"\*\*Current release:\*\* v{VERSION_RE}", f"**Current release:** v{version}", count=1))

    # Historical feature tests live in tests/current, but their release pins
    # should always follow the active package version. This keeps the behavior
    # assertions while avoiding dozens of hand-edits on every release.
    tests_dir = ROOT / "tests" / "current"
    for path in sorted(tests_dir.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        new = re.sub(r'BROWSER_VERSION == (["\'])' + VERSION_RE + r'\1', lambda m: f'BROWSER_VERSION == {m.group(1)}{version}{m.group(1)}', text)
        new = re.sub(r'BROWSER_VERSION = \\"' + VERSION_RE + r'\\"', f'BROWSER_VERSION = \\"{version}\\"', new)
        new = re.sub(r'BROWSER_VERSION = "' + VERSION_RE + r'"', f'BROWSER_VERSION = "{version}"', new)
        new = re.sub(r'version="' + VERSION_RE + r'\.0"', f'version="{version}.0"', new)
        new = re.sub(r"extension\['version'\] == ([\"'])" + VERSION_RE + r"\1", lambda m: f"extension['version'] == {m.group(1)}{version}{m.group(1)}", new)
        new = re.sub(r"filevers=\\?\(\d+,\\?\s*\d+,\\?\s*\d+,\\?\s*0\\?\)", f"filevers=({major}, {minor}, {patch}, 0)", new)
        new = re.sub(r"u'ProductVersion', u'" + VERSION_RE + r"'", f"u'ProductVersion', u'{version}'", new)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(str(path.relative_to(ROOT)))

    return changed



def check(version: str) -> list[str]:
    if not re.fullmatch(VERSION_RE, version):
        raise ValueError(f"Invalid version: {version!r}")
    major, minor, patch = (int(x) for x in version.split("."))
    issues: list[str] = []

    checks = [
        (ROOT / "main.py", f'BROWSER_VERSION = "{version}"'),
        (ROOT / "tekzite_browser.manifest", f'<assemblyIdentity version="{version}.0"'),
        (ROOT / "tekzite_version_info.txt", f'filevers=({major}, {minor}, {patch}, 0)'),
        (ROOT / "tekzite_version_info.txt", f'prodvers=({major}, {minor}, {patch}, 0)'),
        (ROOT / "tekzite_version_info.txt", f"StringStruct(u'FileVersion', u'{version}')"),
        (ROOT / "tekzite_version_info.txt", f"StringStruct(u'ProductVersion', u'{version}')"),
        (ROOT / "installer" / "TekziteBrowser.iss", f'#define MyAppVersion "{version}"'),
        (ROOT / "installer" / "README.txt", f'Tekzite-Browser-Setup-{version}.exe'),
        (ROOT / "README.md", f'**Current release:** v{version}'),
    ]
    for path, needle in checks:
        if needle not in path.read_text(encoding="utf-8"):
            issues.append(f"{path.relative_to(ROOT)} missing {needle!r}")

    manifest_path = ROOT / "chromium_zoom_extension" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(f"{manifest_path.relative_to(ROOT)} invalid JSON: {exc}")
    else:
        if manifest.get("version") != version:
            issues.append(
                f"{manifest_path.relative_to(ROOT)} version is {manifest.get('version')!r}, expected {version!r}"
            )

    # Current-suite release pins should agree with the package. Historical
    # URLs/examples are ignored unless they are actual BROWSER_VERSION checks.
    for path in sorted((ROOT / "tests" / "current").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for found in re.findall(r'BROWSER_VERSION == ["\'](' + VERSION_RE + r')["\']', text):
            if found != version:
                issues.append(f"{path.relative_to(ROOT)} pins BROWSER_VERSION {found}")
        for found in re.findall(r'BROWSER_VERSION = ["\'](' + VERSION_RE + r')["\']', text):
            if found != version:
                issues.append(f"{path.relative_to(ROOT)} pins source BROWSER_VERSION {found}")
    return issues

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Semantic release version, e.g. 10.5.63")
    parser.add_argument("--check", action="store_true", help="Validate metadata without modifying files")
    args = parser.parse_args()
    if args.check:
        issues = check(args.version)
        if issues:
            print(f"Tekzite release metadata does not match v{args.version}:")
            for item in issues:
                print(f"  - {item}")
            return 1
        print(f"Tekzite release metadata is synchronized to v{args.version}")
        return 0
    changed = sync(args.version)
    print(f"Tekzite release metadata synchronized to v{args.version}")
    for item in changed:
        print(f"  updated {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
