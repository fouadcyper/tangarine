from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from .settings import load_settings, save_settings
from .smart import build_universal_apk, sign_aab


class SigningApplication(Adw.Application):
    def __init__(self, source: Path, mode: str):
        super().__init__(
            application_id="io.github.quickconvert.app.Signing",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.source = source
        self.mode = mode
        self.result: Path | None = None
        self._settings = load_settings()
        self._working = False

    def do_activate(self):
        output_name = "AAB" if self.mode == "aab" else "APK"
        self._window = Adw.PreferencesWindow(application=self, title=f"Sign {output_name}")
        self._window.set_default_size(540, 540)
        page_title = "Sign AAB" if self.mode == "aab" else "AAB to signed APK"
        page = Adw.PreferencesPage(title=page_title, icon_name="security-high-symbolic")

        source_group = Adw.PreferencesGroup(
            title="Android App Bundle",
            description=self.source.name,
        )
        source_group.add(Adw.ActionRow(
            title="Signed AAB copy" if self.mode == "aab" else "Universal APK",
            subtitle=(
                "Signs a new AAB copy and leaves the original untouched"
                if self.mode == "aab"
                else "Creates one installable APK for local distribution and testing"
            ),
            icon_name="channel-secure-symbolic" if self.mode == "aab" else "application-x-executable-symbolic",
        ))
        page.add(source_group)

        signing = Adw.PreferencesGroup(
            title="Signing key",
            description="Passwords stay only in memory and are never saved.",
        )
        key_row = Adw.ActionRow(title="Keystore file", subtitle=self._settings["aab_keystore"] or "Choose .jks or .keystore")
        choose = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
        choose.add_css_class("flat")
        choose.connect("clicked", self._choose_keystore)
        key_row.add_suffix(choose)
        key_row.set_activatable_widget(choose)
        signing.add(key_row)
        self._key_row = key_row

        self._alias = Adw.EntryRow(title="Key alias")
        self._alias.set_text(self._settings["aab_alias"])
        signing.add(self._alias)
        self._store_password = Adw.PasswordEntryRow(title="Keystore password")
        signing.add(self._store_password)
        self._key_password = Adw.PasswordEntryRow(title="Key password (leave empty if the same)")
        signing.add(self._key_password)
        page.add(signing)

        action_group = Adw.PreferencesGroup()
        self._error = Gtk.Label(wrap=True, visible=False, css_classes=["error"])
        action_group.add(self._error)
        self._button = Gtk.Button(label=f"Create signed {output_name}", margin_top=12, margin_bottom=12)
        self._button.add_css_class("suggested-action")
        self._button.add_css_class("pill")
        self._button.connect("clicked", self._start)
        action_group.add(self._button)
        page.add(action_group)
        self._window.add(page)
        self._window.connect("close-request", self._closed)
        self._window.present()

    def _choose_keystore(self, _button):
        chooser = Gtk.FileChooserNative(
            title="Choose signing keystore",
            transient_for=self._window,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Choose",
            cancel_label="Cancel",
        )
        file_filter = Gtk.FileFilter(name="Android keystores")
        file_filter.add_pattern("*.jks")
        file_filter.add_pattern("*.keystore")
        file_filter.add_pattern("*.p12")
        chooser.add_filter(file_filter)
        chooser.connect("response", self._keystore_chosen)
        chooser.show()

    def _keystore_chosen(self, chooser, response):
        if response == Gtk.ResponseType.ACCEPT:
            selected = chooser.get_file()
            if selected and selected.get_path():
                self._settings["aab_keystore"] = selected.get_path()
                self._key_row.set_subtitle(selected.get_basename())
        chooser.destroy()

    def _start(self, _button):
        keystore = Path(self._settings["aab_keystore"]).expanduser()
        alias = self._alias.get_text().strip()
        store_password = self._store_password.get_text()
        key_password = self._key_password.get_text()
        if not keystore.is_file() or not alias or not store_password:
            self._show_error("Choose a keystore and enter its key alias and password.")
            return
        self._working = True
        self._button.set_sensitive(False)
        self._button.set_label("Signing and verifying…")
        self._error.set_visible(False)
        thread = threading.Thread(
            target=self._worker,
            args=(keystore, alias, store_password, key_password),
            daemon=True,
        )
        thread.start()

    def _worker(self, keystore: Path, alias: str, store_password: str, key_password: str):
        try:
            if self.mode == "aab":
                result = sign_aab(
                    self.source, keystore, alias, store_password, key_password,
                )
            else:
                result = build_universal_apk(
                    self.source,
                    keystore=keystore,
                    alias=alias,
                    store_password=store_password,
                    key_password=key_password,
                )
        except Exception as error:
            GLib.idle_add(self._failed, str(error))
            return
        GLib.idle_add(self._finished, result, keystore, alias)

    def _failed(self, message: str):
        self._working = False
        self._button.set_sensitive(True)
        self._button.set_label(f"Create signed {'AAB' if self.mode == 'aab' else 'APK'}")
        self._show_error(message)
        return GLib.SOURCE_REMOVE

    def _finished(self, result: Path, keystore: Path, alias: str):
        self.result = result
        self._settings["aab_keystore"] = str(keystore)
        self._settings["aab_alias"] = alias
        save_settings(self._settings)
        self._store_password.set_text("")
        self._key_password.set_text("")
        self._working = False
        self.quit()
        return GLib.SOURCE_REMOVE

    def _show_error(self, message: str):
        self._error.set_label(message)
        self._error.set_visible(True)

    def _closed(self, _window):
        if self._working:
            return True
        self.quit()
        return False


def run_signing_dialog(source: Path, mode: str = "apk") -> Path:
    application = SigningApplication(source, mode)
    application.run(["quickconvert-signing"])
    if application.result is None:
        raise RuntimeError("Signing cancelled")
    return application.result
