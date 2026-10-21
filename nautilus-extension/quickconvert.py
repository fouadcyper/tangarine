from __future__ import annotations

from gi.repository import Gio, GLib, GObject, Nautilus


class QuickConvertMenuProvider(GObject.GObject, Nautilus.MenuProvider):
    def _activate(self, _item, file_infos):
        uris = [file_info.get_uri() for file_info in file_infos]
        local = GLib.build_filenamev([GLib.get_home_dir(), ".local", "bin", "quickconvert"])
        executable = local if GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE) else "/usr/bin/quickconvert"
        try:
            Gio.Subprocess.new([executable, "--show", *uris], Gio.SubprocessFlags.NONE)
        except GLib.Error as error:
            print(f"QuickConvert: {error.message}")

    def get_file_items(self, files):
        if not files or len(files) > 64:
            return []
        for file_info in files:
            location = file_info.get_location()
            if location is None or not location.is_native() or file_info.is_directory():
                return []
        label = "Quick Convert…" if len(files) == 1 else f"Quick Convert {len(files)} Files…"
        item = Nautilus.MenuItem(
            name="QuickConvert::RadialMenu",
            label=label,
            tip="Open the QuickConvert radial menu",
            icon="io.github.quickconvert.app",
        )
        item.connect("activate", self._activate, files)
        return [item]

    def get_background_items(self, _current_folder):
        return []
