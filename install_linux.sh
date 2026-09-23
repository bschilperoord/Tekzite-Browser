#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

binary="dist-linux/TekziteBrowser"
if [[ ! -x "$binary" ]]; then
  echo "Linux executable not found. Run ./build_linux.sh first." >&2
  exit 1
fi

bin_dir="${HOME}/.local/bin"
app_dir="${HOME}/.local/share/applications"
icon_dir="${HOME}/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$bin_dir" "$app_dir" "$icon_dir"
install -m 0755 "$binary" "$bin_dir/TekziteBrowser"
install -m 0644 assets/tekzite.png "$icon_dir/tekzite.png"

sed "s|^Exec=.*|Exec=${bin_dir}/TekziteBrowser %U|" \
  packaging/linux/tekzite-browser.desktop > "$app_dir/tekzite-browser.desktop"
chmod 0644 "$app_dir/tekzite-browser.desktop"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$app_dir" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "Installed Tekzite Browser Linux Preview for this user."
echo "Desktop entry: $app_dir/tekzite-browser.desktop"
echo "Executable:    $bin_dir/TekziteBrowser"
echo
echo "Tekzite was not made the default browser automatically."
echo "If you want that later: xdg-settings set default-web-browser tekzite-browser.desktop"
