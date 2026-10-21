import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as DND from 'resource:///org/gnome/shell/ui/dnd.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

Gio._promisify(Gio.Subprocess.prototype, 'communicate_utf8_async', 'communicate_utf8_finish');

const BUS_NAME = 'org.gnome.Shell.Extensions.QuickConvert';
const OBJECT_PATH = '/org/gnome/Shell/Extensions/QuickConvert';
const INTERFACE_XML = `
<node>
  <interface name="org.gnome.Shell.Extensions.QuickConvert">
    <method name="ShowFile"><arg type="s" name="uri" direction="in"/></method>
    <method name="ShowFiles"><arg type="as" name="uris" direction="in"/></method>
    <method name="Hide"/>
  </interface>
</node>`;

function localUrisFromPayload(payload) {
    const uris = [];
    for (const rawLine of payload.split(/\r?\n/)) {
        const line = rawLine.trim();
        if (!line || line.startsWith('#') || line === 'copy' || line === 'cut')
            continue;
        if (line.startsWith('file://') && !uris.includes(line))
            uris.push(line);
    }
    return uris.slice(0, 64);
}

export default class QuickConvertExtension extends Extension {
    enable() {
        this._overlay = null;
        this._uris = [];
        this._actions = [];
        this._moreActions = [];
        this._buttons = [];
        this._highlighted = -1;
        this._dragActive = false;
        this._busy = false;
        this._anchor = null;
        this._pendingUris = [];
        this._process = null;
        this._readInProgress = false;
        this._readRetryId = 0;
        this._pollDetectedDrag = false;

        this._dragMonitor = {dragMotion: event => this._onDragMotion(event)};
        DND.addDragMonitor(this._dragMonitor);
        this._dragBeginId = Main.xdndHandler.connect('drag-begin', () => this._onDragBegin());
        this._dragEndId = Main.xdndHandler.connect('drag-end', () => this._onDragEnd());
        this._dragPollId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 80, () => this._pollDragState());

        this._dbus = Gio.DBusExportedObject.wrapJSObject(INTERFACE_XML, this);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
        this._ownerId = Gio.bus_own_name_on_connection(
            Gio.DBus.session, BUS_NAME, Gio.BusNameOwnerFlags.NONE, null, null
        );
    }

    disable() {
        if (this._dragMonitor)
            DND.removeDragMonitor(this._dragMonitor);
        if (this._dragBeginId)
            Main.xdndHandler.disconnect(this._dragBeginId);
        if (this._dragEndId)
            Main.xdndHandler.disconnect(this._dragEndId);
        this._dragMonitor = null;
        this._dragBeginId = 0;
        this._dragEndId = 0;
        if (this._dragPollId)
            GLib.source_remove(this._dragPollId);
        this._dragPollId = 0;
        if (this._readRetryId)
            GLib.source_remove(this._readRetryId);
        this._readRetryId = 0;
        this._destroyOverlay();
        this._dbus?.unexport();
        this._dbus = null;
        if (this._ownerId)
            Gio.bus_unown_name(this._ownerId);
        this._ownerId = 0;
    }

    ShowFile(uri) {
        this.ShowFiles([uri]);
    }

    ShowFiles(uris) {
        this._dragActive = false;
        this._pendingUris = uris;
        const [x, y] = global.get_pointer();
        this._requestActions(uris, x, y, false);
    }

    Hide() {
        this._hide();
    }

    _backendPath() {
        const override = GLib.getenv('QUICKCONVERT_BACKEND');
        if (override && GLib.file_test(override, GLib.FileTest.IS_EXECUTABLE))
            return override;
        const local = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'quickconvert']);
        return GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE) ? local : '/usr/bin/quickconvert';
    }

    _onDragBegin() {
        if (this._busy)
            return;
        this._beginDrag(null, false);
    }

    _beginDrag(anchor, detectedByPoll) {
        if (this._dragActive || this._busy)
            return;
        this._dragActive = true;
        this._pollDetectedDrag = detectedByPoll;
        this._anchor = anchor;
        this._pendingUris = [];
        this._readInProgress = false;
        this._readDraggedUris();
        this._readRetryId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 90, () => {
            if (!this._dragActive || this._pendingUris.length) {
                this._readRetryId = 0;
                return GLib.SOURCE_REMOVE;
            }
            this._readDraggedUris();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _pollDragState() {
        if (this._busy)
            return GLib.SOURCE_CONTINUE;
        const [x, y, modifiers] = global.get_pointer();
        const primaryPressed = !!(modifiers & Clutter.ModifierType.BUTTON1_MASK);
        if (!this._dragActive && primaryPressed) {
            try {
                const selection = global.display.get_selection();
                const mimetypes = selection.get_mimetypes(Meta.SelectionType.SELECTION_DND) ?? [];
                const hasFileData = mimetypes.some(type =>
                    type === 'text/uri-list' || type === 'x-special/gnome-copied-files'
                );
                if (hasFileData)
                    this._beginDrag([x, y], true);
            } catch (_error) {
                // The DND selection is transient; the next poll retries it.
            }
        } else if (this._dragActive && this._pollDetectedDrag && !primaryPressed) {
            this._onDragEnd();
        }
        if (this._dragActive && this._overlay?.visible)
            this._updateHighlight(x, y);
        return GLib.SOURCE_CONTINUE;
    }

    _readDraggedUris() {
        if (this._readInProgress || !this._dragActive)
            return;
        const selection = global.display.get_selection();
        const selectionType = Meta.SelectionType.SELECTION_DND;
        const mimetypes = selection.get_mimetypes(selectionType) ?? [];
        const mime = mimetypes.includes('text/uri-list')
            ? 'text/uri-list'
            : mimetypes.find(type => type === 'x-special/gnome-copied-files');
        if (!mime)
            return;
        this._readInProgress = true;
        const stream = Gio.MemoryOutputStream.new_resizable();
        selection.transfer_async(selectionType, mime, -1, stream, null, (object, result) => {
            try {
                object.transfer_finish(result);
                stream.close(null);
                const payload = new TextDecoder().decode(stream.steal_as_bytes().get_data());
                const uris = localUrisFromPayload(payload);
                this._readInProgress = false;
                if (!uris.length || !this._dragActive)
                    return;
                this._pendingUris = uris;
                if (this._readRetryId) {
                    GLib.source_remove(this._readRetryId);
                    this._readRetryId = 0;
                }
                if (this._anchor)
                    this._requestActions(uris, this._anchor[0], this._anchor[1], true);
            } catch (error) {
                this._readInProgress = false;
                console.debug(`QuickConvert: drag data unavailable: ${error.message}`);
            }
        });
    }

    _onDragMotion(event) {
        if (!this._dragActive || this._busy)
            return DND.DragMotionResult.CONTINUE;
        if (!this._anchor) {
            this._anchor = [event.x, event.y];
            if (this._pendingUris.length)
                this._requestActions(this._pendingUris, event.x, event.y, true);
        }
        if (this._overlay?.visible) {
            this._updateHighlight(event.x, event.y);
            return this._highlighted >= 0
                ? DND.DragMotionResult.COPY_DROP
                : DND.DragMotionResult.NO_DROP;
        }
        return DND.DragMotionResult.CONTINUE;
    }

    _onDragEnd() {
        if (!this._dragActive)
            return;
        this._dragActive = false;
        this._pollDetectedDrag = false;
        if (this._readRetryId) {
            GLib.source_remove(this._readRetryId);
            this._readRetryId = 0;
        }
        if (this._highlighted >= 0 && this._actions[this._highlighted])
            this._activateAction(this._actions[this._highlighted]);
        else if (!this._busy)
            this._hide();
    }

    async _requestActions(uris, pointerX, pointerY, fromDrag) {
        if (this._busy || !uris.length)
            return;
        try {
            const process = Gio.Subprocess.new(
                [this._backendPath(), '--actions', ...uris],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            );
            const [stdout, stderr] = await process.communicate_utf8_async(null, null);
            if (!process.get_successful())
                throw new Error(stderr.trim() || 'This file type is not supported');
            if (fromDrag && !this._dragActive)
                return;
            this._showForFiles(uris, JSON.parse(stdout), pointerX, pointerY, fromDrag);
        } catch (error) {
            if (!fromDrag)
                Main.notifyError('QuickConvert', error.message);
        }
    }

    _showForFiles(uris, data, pointerX, pointerY, fromDrag) {
        const file = Gio.File.new_for_uri(uris[0]);
        if (!file.is_native())
            return;
        let info;
        try {
            info = file.query_info('standard::icon', Gio.FileQueryInfoFlags.NONE, null);
        } catch (error) {
            Main.notifyError('QuickConvert', error.message);
            return;
        }
        this._uris = uris;
        this._moreActions = data.more ?? [];
        this._actions = [...(data.primary ?? [])];
        if (this._moreActions.length)
            this._actions.push({id: '__more__', label: 'MORE', icon: 'view-more-symbolic'});
        this._highlighted = -1;
        this._buildOverlay(info, data, fromDrag);
        this._placeOverlay(pointerX, pointerY);
        this._overlay.show();
        this._overlay.opacity = 0;
        this._overlay.scale_x = 0.82;
        this._overlay.scale_y = 0.82;
        this._overlay.ease({
            opacity: 255, scale_x: 1, scale_y: 1, duration: 190,
            mode: Clutter.AnimationMode.EASE_OUT_BACK,
        });
    }

    _buildOverlay(info, data, fromDrag) {
        this._destroyOverlay();
        this._overlay = new St.Widget({
            style_class: 'quickconvert-overlay', reactive: true,
            width: 400, height: 400, layout_manager: new Clutter.FixedLayout(),
        });
        const glass = new St.Widget({
            style_class: 'quickconvert-glass', x: 35, y: 35, width: 330, height: 330,
        });
        try {
            glass.add_effect(new Shell.BlurEffect({
                mode: Shell.BlurMode.BACKGROUND, radius: 28, brightness: 0.62,
            }));
        } catch (_error) {
            // Translucent shell CSS remains the visual fallback.
        }
        this._overlay.add_child(glass);

        this._buttons = [];
        const count = this._actions.length;
        const radius = count <= 3 ? 128 : 136;
        this._actions.forEach((action, index) => {
            const angle = -Math.PI / 2 + index * (Math.PI * 2 / count);
            const content = new St.BoxLayout({
                orientation: Clutter.Orientation.VERTICAL,
                x_align: Clutter.ActorAlign.CENTER, y_align: Clutter.ActorAlign.CENTER,
            });
            content.add_child(new St.Icon({icon_name: action.icon, icon_size: 20}));
            content.add_child(new St.Label({text: action.label, style_class: 'quickconvert-action-label'}));
            const button = new St.Button({
                style_class: action.id === '__more__' ? 'quickconvert-action quickconvert-more' : 'quickconvert-action',
                child: content, reactive: true, can_focus: !fromDrag,
                x: 200 + Math.cos(angle) * radius - 38,
                y: 200 + Math.sin(angle) * radius - 38,
                width: 76, height: 76,
            });
            button.connect('clicked', () => this._activateAction(action));
            button.connect('enter-event', () => {
                if (!this._dragActive)
                    this._setHighlighted(index);
                return Clutter.EVENT_PROPAGATE;
            });
            button.connect('leave-event', () => {
                if (!this._dragActive)
                    this._setHighlighted(-1);
                return Clutter.EVENT_PROPAGATE;
            });
            this._overlay.add_child(button);
            this._buttons.push(button);
        });

        this._progressRing = new St.Widget({
            style_class: 'quickconvert-progress-ring', x: 132, y: 132,
            width: 136, height: 136, opacity: 0,
        });
        this._overlay.add_child(this._progressRing);
        this._center = new St.BoxLayout({
            style_class: 'quickconvert-center', orientation: Clutter.Orientation.VERTICAL,
            x_align: Clutter.ActorAlign.CENTER, y_align: Clutter.ActorAlign.CENTER,
            x: 142, y: 142, width: 116, height: 116,
        });
        this._center.add_child(new St.Icon({gicon: info.get_icon(), icon_size: 36}));
        let name = data.name ?? 'File';
        if (name.length > 18)
            name = `${name.slice(0, 15)}…`;
        this._center.add_child(new St.Label({text: name, style_class: 'quickconvert-file-label'}));
        this._center.add_child(new St.Label({text: data.size ?? '', style_class: 'quickconvert-size-label'}));
        this._overlay.add_child(this._center);

        this._cancelButton = new St.Button({
            style_class: 'quickconvert-cancel', icon_name: 'process-stop-symbolic',
            x: 181, y: 276, width: 38, height: 38, visible: false,
        });
        this._cancelButton.connect('clicked', () => this._cancelConversion());
        this._overlay.add_child(this._cancelButton);
        Main.uiGroup.add_child(this._overlay);
        Main.uiGroup.set_child_above_sibling(this._overlay, null);
    }

    _placeOverlay(pointerX, pointerY) {
        const monitor = Main.layoutManager.monitors.find(candidate =>
            pointerX >= candidate.x && pointerX < candidate.x + candidate.width &&
            pointerY >= candidate.y && pointerY < candidate.y + candidate.height
        ) ?? Main.layoutManager.primaryMonitor ?? {x: 0, y: 0, width: 1280, height: 720};
        const x = Math.max(monitor.x + 12, Math.min(pointerX - 200, monitor.x + monitor.width - 412));
        const y = Math.max(monitor.y + 12, Math.min(pointerY - 200, monitor.y + monitor.height - 412));
        this._overlay.set_position(Math.round(x), Math.round(y));
    }

    _updateHighlight(stageX, stageY) {
        const [overlayX, overlayY] = this._overlay.get_transformed_position();
        let closest = -1;
        let closestDistance = 58;
        this._buttons.forEach((button, index) => {
            const distance = Math.hypot(
                stageX - (overlayX + button.x + button.width / 2),
                stageY - (overlayY + button.y + button.height / 2)
            );
            if (distance < closestDistance) {
                closestDistance = distance;
                closest = index;
            }
        });
        this._setHighlighted(closest);
    }

    _setHighlighted(index) {
        if (index === this._highlighted)
            return;
        this._buttons.forEach((button, buttonIndex) => {
            if (buttonIndex === index)
                button.add_style_pseudo_class('selected');
            else
                button.remove_style_pseudo_class('selected');
        });
        this._highlighted = index;
    }

    _activateAction(action) {
        if (action.id === '__more__') {
            this._showMore();
            return;
        }
        this._startConversion(action);
    }

    _showMore() {
        if (!this._moreActions.length)
            return;
        const [x, y] = this._overlay.get_transformed_position();
        const info = Gio.File.new_for_uri(this._uris[0]).query_info(
            'standard::icon', Gio.FileQueryInfoFlags.NONE, null
        );
        const name = this._uris.length === 1
            ? Gio.File.new_for_uri(this._uris[0]).get_basename()
            : `${this._uris.length} files`;
        if (this._moreActions.length > 6) {
            this._actions = this._moreActions.slice(0, 5);
            this._moreActions = this._moreActions.slice(5);
            this._actions.push({id: '__more__', label: 'NEXT', icon: 'go-next-symbolic'});
        } else {
            this._actions = this._moreActions;
            this._moreActions = [];
        }
        this._dragActive = false;
        this._buildOverlay(info, {name, size: 'More actions'}, false);
        this._overlay.set_position(x, y);
        this._overlay.show();
        this._overlay.opacity = 0;
        this._overlay.ease({opacity: 255, duration: 150, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
    }

    async _startConversion(action) {
        if (this._busy || !this._uris.length)
            return;
        this._busy = true;
        this._dragActive = false;
        this._buttons.forEach(button => button.ease({
            opacity: 0, scale_x: 0.72, scale_y: 0.72, duration: 130,
            mode: Clutter.AnimationMode.EASE_IN_QUAD,
        }));
        this._center.add_style_pseudo_class('busy');
        this._cancelButton.show();
        this._progressRing.ease({opacity: 255, duration: 150});
        this._spinProgress();
        try {
            this._process = Gio.Subprocess.new(
                [this._backendPath(), '--convert', action.id, ...this._uris],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            );
            const process = this._process;
            const [stdout, stderr] = await process.communicate_utf8_async(null, null);
            if (this._process !== process)
                return;
            this._process = null;
            if (!process.get_successful())
                throw new Error(stderr.trim() || 'Conversion failed');
            this._busy = false;
            this._cancelButton.hide();
            this._progressRing.remove_all_transitions();
            this._progressRing.opacity = 0;
            this._center.remove_style_pseudo_class('busy');
            this._center.add_style_pseudo_class('success');
            this._center.ease({
                scale_x: 1.10, scale_y: 1.10, duration: 150,
                mode: Clutter.AnimationMode.EASE_OUT_BACK,
                onComplete: () => this._hide(),
            });
            const result = stdout.trim();
            let message = 'Action completed';
            if (result && !result.endsWith('files completed'))
                message = `${Gio.File.new_for_path(result).get_basename()} is ready`;
            else if (result)
                message = result;
            Main.notify('QuickConvert', message);
        } catch (error) {
            this._process = null;
            this._busy = false;
            this._hide();
            Main.notifyError('QuickConvert could not finish', error.message);
        }
    }

    _spinProgress() {
        if (!this._busy || !this._progressRing)
            return;
        this._progressRing.rotation_angle_z = 0;
        this._progressRing.ease({
            rotation_angle_z: 360, duration: 760,
            mode: Clutter.AnimationMode.LINEAR,
            onComplete: () => this._spinProgress(),
        });
    }

    _cancelConversion() {
        if (!this._process)
            return;
        const process = this._process;
        this._process = null;
        process.force_exit();
        this._busy = false;
        this._hide();
        Main.notify('QuickConvert', 'Conversion cancelled');
    }

    _hide() {
        if (!this._overlay)
            return;
        const overlay = this._overlay;
        overlay.ease({
            opacity: 0, scale_x: 0.88, scale_y: 0.88, duration: 145,
            mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => {
                if (this._overlay === overlay)
                    this._destroyOverlay();
                else
                    overlay.destroy();
            },
        });
    }

    _destroyOverlay() {
        this._overlay?.remove_all_transitions();
        this._overlay?.destroy();
        this._overlay = null;
        this._buttons = [];
        this._progressRing = null;
        this._cancelButton = null;
        this._center = null;
        this._highlighted = -1;
    }
}
