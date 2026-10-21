from __future__ import annotations

import signal
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from .settings import load_settings, save_settings
from .smart import actions_json, perform


APP_ID = "io.github.quickconvert.app"
BUS_NAME = "org.gnome.Shell.Extensions.QuickConvert"
OBJECT_PATH = "/org/gnome/Shell/Extensions/QuickConvert"
INTERFACE = "org.gnome.Shell.Extensions.QuickConvert"


def source_path(value: str) -> Path:
    if value.startswith("file://"):
        return Path(unquote(urlparse(value).path)).resolve()
    return Path(value).expanduser().resolve()


def source_paths(values: list[str]) -> list[Path]:
    paths = [source_path(value) for value in values]
    return [path for path in paths if path.is_file()]


def show_radial(values: list[str]) -> bool:
    paths = source_paths(values)
    if not paths:
        raise ValueError("Unsupported or missing files")
    uris = [path.as_uri() for path in paths]
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    connection.call_sync(
        BUS_NAME,
        OBJECT_PATH,
        INTERFACE,
        "ShowFiles",
        GLib.Variant("(as)", (uris,)),
        None,
        Gio.DBusCallFlags.NONE,
        3000,
        None,
    )
    return True


def convert_now(action: str, values: list[str]) -> int:
    paths = source_paths(values)
    if not paths:
        print("Source files do not exist", file=sys.stderr)
        return 2
    try:
        if action in {"image_resize", "image_crop"}:
            from .image_edit import run_image_dialog

            outputs = [run_image_dialog(paths[0], "crop" if action == "image_crop" else "resize")]
        elif action in {"aab_sign_apk", "aab_sign_bundle"}:
            from .signing import run_signing_dialog

            outputs = [run_signing_dialog(paths[0], mode="aab" if action == "aab_sign_bundle" else "apk")]
        else:
            outputs = perform(action, paths)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(outputs[0] if len(outputs) == 1 else f"{len(outputs)} files completed")
    return 0


class SettingsWindow(Adw.PreferencesWindow):
    IMAGE_FORMATS = ["webp", "jpg", "png", "avif"]
    VIDEO_FORMATS = ["mp4", "webm", "mov"]
    AUDIO_FORMATS = ["mp3", "ogg", "flac", "m4a"]
    BITRATES = ["128k", "160k", "192k", "256k", "320k"]

    def __init__(self, application):
        super().__init__(application=application, title="QuickConvert Settings")
        self.set_default_size(620, 690)
        self._settings = load_settings()
        self._build()

    def _combo(self, title: str, values: list[str], current: str, key: str) -> Adw.ComboRow:
        model = Gtk.StringList.new([value.upper() for value in values])
        row = Adw.ComboRow(title=title, model=model)
        row.set_selected(values.index(current) if current in values else 0)
        row.connect("notify::selected", lambda widget, _prop: self._set(key, values[widget.get_selected()]))
        return row

    def _switch(self, title: str, subtitle: str, key: str) -> Adw.SwitchRow:
        row = Adw.SwitchRow(title=title, subtitle=subtitle, active=bool(self._settings[key]))
        row.connect("notify::active", lambda widget, _prop: self._set(key, widget.get_active()))
        return row

    def _scale(self, title: str, key: str) -> Adw.SpinRow:
        row = Adw.SpinRow.new_with_range(20, 100, 1)
        row.set_title(title)
        row.set_value(float(self._settings[key]))
        row.connect("notify::value", lambda widget, _prop: self._set(key, int(widget.get_value())))
        return row

    def _set(self, key, value):
        self._settings[key] = value
        save_settings(self._settings)

    def _build(self):
        page = Adw.PreferencesPage(title="Conversion", icon_name="emblem-system-symbolic")

        output = Adw.PreferencesGroup(title="Output", description="Where converted files are saved")
        mode = self._combo("Output location", ["beside", "custom"], self._settings["output_mode"], "output_mode")
        output.add(mode)
        directory = Adw.EntryRow(title="Custom output folder")
        directory.set_text(self._settings["output_directory"])
        directory.connect("changed", lambda widget: self._set("output_directory", widget.get_text()))
        output.add(directory)
        output.add(self._switch("Overwrite matching outputs", "Otherwise QuickConvert creates a numbered filename", "overwrite"))
        page.add(output)

        quality = Adw.PreferencesGroup(title="Quality")
        quality.add(self._scale("Image quality", "image_quality"))
        quality.add(self._scale("Video quality", "video_quality"))
        quality.add(self._combo("Audio bitrate", self.BITRATES, self._settings["audio_bitrate"], "audio_bitrate"))
        quality.add(self._switch("Remove metadata by default", "Strips private camera and media metadata when possible", "remove_metadata"))
        page.add(quality)

        defaults = Adw.PreferencesGroup(title="Default batch formats")
        defaults.add(self._combo("Images", self.IMAGE_FORMATS, self._settings["default_image_format"], "default_image_format"))
        defaults.add(self._combo("Video", self.VIDEO_FORMATS, self._settings["default_video_format"], "default_video_format"))
        defaults.add(self._combo("Audio", self.AUDIO_FORMATS, self._settings["default_audio_format"], "default_audio_format"))
        page.add(defaults)

        about = Adw.PreferencesGroup(title="Wayland integration")
        status = Adw.ActionRow(
            title="GNOME Shell radial overlay",
            subtitle="Runs only inside GNOME Shell; the conversion backend starts on demand",
            icon_name="object-select-symbolic",
        )
        about.add(status)
        page.add(about)
        self.add(page)


class QuickConvertApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        window = self.props.active_window or SettingsWindow(self)
        window.present()


def main() -> int:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--actions":
        paths = source_paths(args[1:])
        try:
            print(actions_json(paths))
            return 0
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if len(args) >= 3 and args[0] == "--convert":
        return convert_now(args[1], args[2:])
    if len(args) >= 2 and args[0] == "--show":
        try:
            show_radial(args[1:])
            return 0
        except Exception as exc:
            print(f"QuickConvert overlay unavailable: {exc}", file=sys.stderr)
            return 1
    return QuickConvertApplication().run([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
