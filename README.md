# QuickConvert 3

[![Tests](https://github.com/fouadcyper/tangarine/actions/workflows/tests.yml/badge.svg)](https://github.com/fouadcyper/tangarine/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/fouadcyper/tangarine)](https://github.com/fouadcyper/tangarine/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A Tangerine-inspired radial quick converter built for **Kali Linux x86_64,
GNOME 50, and native Wayland**. It uses a GNOME Shell overlay instead of an
X11 window, so the desktop remains visible while you drag and convert files.

## One-command install

```bash
curl -fL -o /tmp/QuickConvert.run https://github.com/fouadcyper/tangarine/releases/latest/download/QuickConvert-3.1.0-Kali-GNOME-Wayland.run && bash /tmp/QuickConvert.run
```

The installer may ask for your password once to install the required
Kali/Debian packages. Sign out and back in once if GNOME has not loaded the
Shell extension before.

## Install

For a source checkout, run `bash install.sh`. The installer adds the GNOME
Shell overlay, backend, Applications entry, icon, and GNOME Files integration.

## Use

Drag one or more local files from GNOME Files. QuickConvert reads their real
content type and opens a small glass radial menu near the pointer. Hover an
action and release to run it. The result is saved next to the source by default.

The **More** item opens secondary actions without turning the overlay into a
dashboard. Right-clicking selected files in GNOME Files and choosing **Quick
Convert…** opens the same overlay. Launching QuickConvert from Applications
opens only its compact settings window.

## Smart actions

- Images: JPG, PNG, WebP, AVIF, HEIC, compress, resize, square crop, rotate,
  metadata removal, clipboard, PDF, and multi-image batch conversion.
  Resize and Crop open a compact editor with custom pixel dimensions, fit/fill/
  stretch modes, circular transparent crops, 1:1, 4:5, 16:9, 9:16, 3:2, and
  ready-made Instagram, Story/Reel, YouTube, Facebook, LinkedIn, and Full HD presets.
- Video: MP4, WebM, MOV, compress, 720p, GIF, MP3 extraction, trim preview,
  remove audio, 30 FPS, and metadata removal.
- Audio: MP3, WAV, FLAC, OGG, M4A, compress, trim preview, bitrate, metadata
  report, and metadata removal.
- PDF: compress, render pages to images, split pages, rotate, merge, and batch.
- Archives: extract and create or repackage ZIP, 7Z, and TAR.GZ.
- Text: clipboard plus Pandoc formats when Pandoc is already available.
- Mixed selections: package together as ZIP, 7Z, or TAR.GZ.
- Android App Bundles: create a universal test APK, inspect bundle details,
  create a universal APK signed with a chosen JKS/keystore and alias, or sign a
  new AAB copy without converting it. The original AAB is never modified.
  Passwords are never stored; bundletool receives them through temporary
  permission-locked files, while jarsigner receives them through its private
  input stream rather than command-line arguments.

Actions whose required system capability is unavailable are hidden. Output
location, overwrite policy, quality, default batch formats, bitrate, and
metadata policy are configurable from the Applications entry.

QuickConvert includes Google's official bundletool 1.18.3 JAR and verifies its
SHA-256 checksum during installation. The installer also provides Java and
Android's `apksigner` from Kali packages.

## Requirements

- Kali Linux or a compatible Debian-based distribution on x86_64
- GNOME Shell 50 on a Wayland session
- Internet access during installation for system packages

QuickConvert does not silently fall back to X11 or Xwayland. Automatic drag
activation is implemented in GNOME Shell; a **Quick Convert…** item in GNOME
Files is included as a native fallback.

## Architecture

- GNOME Shell extension: receives GNOME's Wayland drag selection and renders
  the overlay inside Shell using St/Clutter.
- Existing Python backend: MIME inspection, contextual actions, safe output
  names, settings, and conversion commands.
- Nautilus extension: multi-selection fallback entry point.
- GTK4/libadwaita: compact native settings window.

## Security and privacy

- Conversions run locally; files are not uploaded.
- Output files never replace the originals unless you explicitly change the
  overwrite setting.
- Keystore passwords are kept only for the active operation and are never
  saved. They are not placed in process command lines.
- The included bundletool JAR is checksum-verified by the installer.

## Development

Run the test suite from the repository root:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Uninstall

Run `bash uninstall.sh` from the extracted package.

## License

QuickConvert is released under the [MIT License](LICENSE). The bundled Google
bundletool component remains under its own Apache-2.0 license; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
