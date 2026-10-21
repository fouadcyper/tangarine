from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from .smart import crop_image, image_dimensions, resize_image


RESIZE_PRESETS = [
    ("Custom", 0, 0),
    ("Square 1:1", 1080, 1080),
    ("Instagram portrait 4:5", 1080, 1350),
    ("Story / Reel 9:16", 1080, 1920),
    ("YouTube thumbnail 16:9", 1280, 720),
    ("Facebook post", 1200, 630),
    ("LinkedIn post 1.91:1", 1200, 627),
    ("Full HD 16:9", 1920, 1080),
]

CROP_PRESETS = [
    ("Square 1:1", 1080, 1080, False),
    ("Portrait 4:5", 1080, 1350, False),
    ("Landscape 16:9", 1280, 720, False),
    ("Vertical 9:16", 1080, 1920, False),
    ("Photo 3:2", 1500, 1000, False),
    ("Circle (transparent PNG)", 1080, 1080, True),
    ("Custom", 0, 0, False),
]


class ImageEditApplication(Adw.Application):
    def __init__(self, source: Path, operation: str):
        super().__init__(
            application_id="io.github.quickconvert.app.ImageEdit",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.source = source
        self.operation = operation
        self.result: Path | None = None
        self._working = False

    def do_activate(self):
        original_width, original_height = image_dimensions(self.source)
        title = "Crop image" if self.operation == "crop" else "Resize image"
        self._window = Adw.PreferencesWindow(application=self, title=title)
        self._window.set_default_size(540, 520)
        page = Adw.PreferencesPage(title=title, icon_name="edit-cut-symbolic" if self.operation == "crop" else "zoom-out-symbolic")

        details = Adw.PreferencesGroup(
            title=self.source.name,
            description=f"Original size: {original_width} × {original_height} px",
        )
        presets = CROP_PRESETS if self.operation == "crop" else RESIZE_PRESETS
        self._presets = presets
        self._preset = Adw.ComboRow(
            title="Preset",
            model=Gtk.StringList.new([item[0] for item in presets]),
        )
        self._preset.connect("notify::selected", self._preset_changed)
        details.add(self._preset)

        self._width = Adw.SpinRow.new_with_range(1, 10000, 1)
        self._width.set_title("Width (pixels)")
        self._width.set_value(original_width)
        details.add(self._width)
        self._height = Adw.SpinRow.new_with_range(1, 10000, 1)
        self._height.set_title("Height (pixels)")
        self._height.set_value(original_height)
        details.add(self._height)
        if self.operation == "crop":
            self._width.set_value(presets[0][1])
            self._height.set_value(presets[0][2])

        if self.operation == "resize":
            self._method = Adw.ComboRow(
                title="Resize method",
                subtitle="Fill & crop creates the exact selected dimensions",
                model=Gtk.StringList.new(["Fit inside", "Fill & crop", "Stretch"]),
            )
            self._method.set_selected(1)
            details.add(self._method)
        page.add(details)

        action = Adw.PreferencesGroup(
            description="The new image is saved next to the original; the original is never changed.",
        )
        self._error = Gtk.Label(wrap=True, visible=False, css_classes=["error"])
        action.add(self._error)
        self._button = Gtk.Button(label=title, margin_top=12, margin_bottom=12)
        self._button.add_css_class("suggested-action")
        self._button.add_css_class("pill")
        self._button.connect("clicked", self._start)
        action.add(self._button)
        page.add(action)
        self._window.add(page)
        self._window.connect("close-request", self._closed)
        self._window.present()

    def _preset_changed(self, row, _property):
        preset = self._presets[row.get_selected()]
        if preset[1] and preset[2]:
            self._width.set_value(preset[1])
            self._height.set_value(preset[2])

    def _start(self, _button):
        width = int(self._width.get_value())
        height = int(self._height.get_value())
        circular = self.operation == "crop" and bool(self._presets[self._preset.get_selected()][3])
        mode = "fill"
        if self.operation == "resize":
            mode = ["inside", "fill", "stretch"][self._method.get_selected()]
        self._working = True
        self._button.set_sensitive(False)
        self._button.set_label("Processing…")
        self._error.set_visible(False)
        threading.Thread(
            target=self._worker,
            args=(width, height, mode, circular),
            daemon=True,
        ).start()

    def _worker(self, width: int, height: int, mode: str, circular: bool):
        try:
            if self.operation == "crop":
                result = crop_image(self.source, width, height, circular)
            else:
                result = resize_image(self.source, width, height, mode)
        except Exception as error:
            GLib.idle_add(self._failed, str(error))
            return
        GLib.idle_add(self._finished, result)

    def _failed(self, message: str):
        self._working = False
        self._button.set_sensitive(True)
        self._button.set_label("Crop image" if self.operation == "crop" else "Resize image")
        self._error.set_label(message)
        self._error.set_visible(True)
        return GLib.SOURCE_REMOVE

    def _finished(self, result: Path):
        self.result = result
        self._working = False
        self.quit()
        return GLib.SOURCE_REMOVE

    def _closed(self, _window):
        if self._working:
            return True
        self.quit()
        return False


def run_image_dialog(source: Path, operation: str) -> Path:
    application = ImageEditApplication(source, operation)
    application.run(["quickconvert-image-edit"])
    if application.result is None:
        raise RuntimeError("Image editing cancelled")
    return application.result
