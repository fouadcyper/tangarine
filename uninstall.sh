#!/usr/bin/env bash
set -euo pipefail
INSTALL_HOME="${QUICKCONVERT_INSTALL_HOME:-${HOME}}"
if [[ -z "$INSTALL_HOME" || "$INSTALL_HOME" == "/" ]]; then
  printf 'Refusing unsafe removal directory.\n' >&2
  exit 1
fi
gnome-extensions disable quickconvert@fouad.local 2>/dev/null || true
gnome-extensions uninstall quickconvert@fouad.local 2>/dev/null || true
rm -rf "${INSTALL_HOME}/.local/share/quickconvert"
rm -f "${INSTALL_HOME}/.local/bin/quickconvert"
rm -f "${INSTALL_HOME}/.local/share/applications/io.github.quickconvert.app.desktop"
rm -f "${INSTALL_HOME}/.local/share/icons/hicolor/scalable/apps/io.github.quickconvert.app.svg"
rm -f "${INSTALL_HOME}/.local/share/nautilus-python/extensions/quickconvert.py"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "${INSTALL_HOME}/.local/share/applications" || true
printf 'QuickConvert was removed.\n'
