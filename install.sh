#!/usr/bin/env bash
set -euo pipefail

INSTALL_HOME="${QUICKCONVERT_INSTALL_HOME:-${HOME}}"
if [[ -z "$INSTALL_HOME" || "$INSTALL_HOME" == "/" ]]; then
  printf 'Refusing unsafe installation directory.\n' >&2
  exit 1
fi
APP_DIR="${INSTALL_HOME}/.local/share/quickconvert"
BIN_DIR="${INSTALL_HOME}/.local/bin"
DESKTOP_DIR="${INSTALL_HOME}/.local/share/applications"
ICON_DIR="${INSTALL_HOME}/.local/share/icons/hicolor/scalable/apps"
NAUTILUS_DIR="${INSTALL_HOME}/.local/share/nautilus-python/extensions"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

packages=(python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-nautilus gnome-shell ffmpeg imagemagick poppler-utils ghostscript img2pdf file qpdf 7zip zip unzip wl-clipboard openjdk-21-jdk-headless apksigner)
missing=()
for package in "${packages[@]}"; do
  dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "ok installed" || missing+=("$package")
done

if ((${#missing[@]})); then
  printf 'Installing required system packages: %s\n' "${missing[*]}"
  sudo apt-get update
  sudo apt-get install -y "${missing[@]}"
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR" "$NAUTILUS_DIR"
rm -rf "$APP_DIR/quickconvert"
cp -R "$SOURCE_DIR/quickconvert" "$APP_DIR/quickconvert"
expected_bundletool="a099cfa1543f55593bc2ed16a70a7c67fe54b1747bb7301f37fdfd6d91028e29"
actual_bundletool="$(sha256sum "$SOURCE_DIR/vendor/bundletool-all-1.18.3.jar" | cut -d' ' -f1)"
if [[ "$actual_bundletool" != "$expected_bundletool" ]]; then
  printf 'Bundled bundletool integrity check failed.\n' >&2
  exit 1
fi
rm -rf "$APP_DIR/vendor"
cp -R "$SOURCE_DIR/vendor" "$APP_DIR/vendor"
cp "$SOURCE_DIR/io.github.quickconvert.app.svg" "$ICON_DIR/io.github.quickconvert.app.svg"
cp "$SOURCE_DIR/nautilus-extension/quickconvert.py" "$NAUTILUS_DIR/quickconvert.py"

sed "s|^Exec=.*|Exec=${BIN_DIR}/quickconvert --settings|" "$SOURCE_DIR/io.github.quickconvert.app.desktop" > "$DESKTOP_DIR/io.github.quickconvert.app.desktop"

cat > "$BIN_DIR/quickconvert" <<EOF
#!/usr/bin/env bash
exec python3 -m quickconvert "\$@"
EOF
sed -i "2i export PYTHONPATH=\"${APP_DIR}:\${PYTHONPATH:-}\"" "$BIN_DIR/quickconvert"
chmod +x "$BIN_DIR/quickconvert"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "${INSTALL_HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true

gnome-extensions disable quickconvert@fouad.local 2>/dev/null || true
gnome-extensions install --force "$SOURCE_DIR/quickconvert@fouad.local.shell-extension.zip"
needs_relogin=0
if ! gnome-extensions enable quickconvert@fouad.local 2>/dev/null; then
  current_extensions="$(gsettings get org.gnome.shell enabled-extensions)"
  updated_extensions="$(python3 - "$current_extensions" <<'PY'
import ast
import sys

extensions = ast.literal_eval(sys.argv[1])
uuid = "quickconvert@fouad.local"
if uuid not in extensions:
    extensions.append(uuid)
print(repr(extensions))
PY
)"
  gsettings set org.gnome.shell enabled-extensions "$updated_extensions"
  needs_relogin=1
fi

if pgrep -x nautilus >/dev/null 2>&1; then
  nautilus -q || true
fi

printf '\nQuickConvert is installed.\n'
if ((needs_relogin)); then
  printf 'Sign out and back in once so GNOME Wayland can load the new Shell extension.\n'
else
  printf 'Its Wayland radial overlay is enabled and waiting for file drags.\n'
fi
printf 'You can also right-click a file in GNOME Files and choose Quick Convert.\n'
printf 'Open QuickConvert from Applications whenever you want to change its settings.\n'
