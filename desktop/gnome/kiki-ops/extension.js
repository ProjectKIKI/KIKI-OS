import Gio from 'gi://Gio';
import GioUnix from 'gi://GioUnix';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import St from 'gi://St';
import {adminCommand, configureWallpaper} from './appearance.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

export default class KikiOps extends Extension {
    enable() {
        // The extension is deliberately inert in ordinary GNOME and GDM.
        if (Main.sessionMode.currentMode !== 'kiki-ops')
            return;
        this._alive = true;
        this._generation = (this._generation ?? 0) + 1;
        this._button = new PanelMenu.Button(0, 'KIKI 로컬 운영');
        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        box.add_child(new St.Icon({gicon: Gio.icon_new_for_string('/usr/share/kiki-paper-pixel/icons/server.svg'), style_class: 'system-status-icon'}));
        this._label = new St.Label({text: 'KIKI · 확인 중', y_align: 2});
        box.add_child(this._label);
        this._button.add_child(box);
        this._summary = new PopupMenu.PopupMenuItem('로컬 상태 확인 중', {reactive: false});
        this._button.menu.addMenuItem(this._summary);
        this._action('관리자 열기', () => this._launchAdmin('overview'));
        this._action('실패 서비스·로그', () => this._launchAdmin('diagnostics'));
        this._action('터미널 열기', () => this._launchDesktop('org.gnome.Console.desktop'));
        this._action('파일 열기', () => this._launchDesktop('org.gnome.Nautilus.desktop'));
        this._action('앱 목록', () => Main.overview.showApps());
        this._action('incident-ai 연결', () => {
            const process = Gio.Subprocess.new(['/usr/libexec/kiki-ops-link'], Gio.SubprocessFlags.STDERR_PIPE);
            process.communicate_utf8_async(null, null, (p, r) => {
                try {
                    const [, , error] = p.communicate_utf8_finish(r);
                    if (!p.get_successful() && this._alive)
                        Main.notifyError('incident-ai 연결', error.trim() || '연결 주소를 확인하세요.');
                } catch (e) {
                    if (this._alive) Main.notifyError('incident-ai 연결', e.message);
                }
            });
        });
        this._action('지금 다시 확인', () => this._refresh());
        this._settings = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
        this._signal = this._settings.connect('changed::color-scheme', () => this._theme());
        this._accessibility = new Gio.Settings({schema_id: 'org.gnome.desktop.a11y.interface'});
        this._contrastSignal = this._accessibility.connect('changed::high-contrast', () => this._theme());
        // One removable scope covers newly created popovers, notifications,
        // overview and dialogs. GTK client surfaces are not Shell CSS actors.
        this._decorated = [Main.layoutManager.uiGroup];
        this._decorated.forEach(a => a.add_style_class_name('kiki-paper-pixel'));
        Main.panel.addToStatusArea(this.uuid, this._button, 0, 'left');
        const shell = new Gio.Settings({schema_id: 'org.gnome.shell'});
        if (shell.get_user_value('favorite-apps') === null)
            shell.set_strv('favorite-apps', ['org.kiki.Admin.desktop', 'org.gnome.Console.desktop', 'org.gnome.Nautilus.desktop', 'org.gnome.Settings.desktop']);
        this._background = new Gio.Settings({schema_id: 'org.gnome.desktop.background'});
        this._theme();
        this._refresh();
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 30, () => {
            this._refresh(); return GLib.SOURCE_CONTINUE;
        });
    }

    _action(title, callback) {
        const item = new PopupMenu.PopupMenuItem(title);
        item.connect('activate', () => {
            try { callback(); } catch (e) { Main.notifyError('KIKI 운영 데스크톱', e.message); }
        });
        this._button.menu.addMenuItem(item);
    }

    _launchDesktop(id) {
        const app = GioUnix.DesktopAppInfo.new(id);
        if (!app) throw new Error(`설치되지 않은 앱: ${id}`);
        app.launch([], global.create_app_launch_context(0, -1));
    }

    _launchAdmin(page) {
        const command = adminCommand(page);
        const timestamp = global.get_current_time();
        const app = Shell.AppSystem.get_default().lookup_app('org.kiki.Admin.desktop');
        // The compositor restores an existing minimized window using the real
        // user event. This avoids weakening Wayland focus-stealing protection.
        if (app?.get_n_windows() > 0)
            app.activate_full(-1, timestamp);
        const info = Gio.AppInfo.create_from_commandline(command, 'KIKI 관리자',
            Gio.AppInfoCreateFlags.SUPPORTS_STARTUP_NOTIFICATION);
        info.launch([], global.create_app_launch_context(timestamp, -1));
        Main.overview.hide();
    }

    _theme() {
        const dark = this._settings.get_string('color-scheme') === 'prefer-dark';
        const highContrast = this._accessibility.get_boolean('high-contrast');
        this._decorated.forEach(a => {
            a.remove_style_class_name('kiki-pixel-light');
            a.remove_style_class_name('kiki-pixel-dark');
            if (!highContrast)
                a.add_style_class_name(dark ? 'kiki-pixel-dark' : 'kiki-pixel-light');
        });
        configureWallpaper(this._background, dark);
    }

    _refresh() {
        if (!this._alive || this._process) return;
        const generation = this._generation;
        const p = Gio.Subprocess.new(['/usr/bin/kiki-adminctl', 'snapshot'],
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
        this._process = p;
        this._deadline = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 8, () => {
            this._deadline = 0; p.force_exit(); return GLib.SOURCE_REMOVE;
        });
        p.communicate_utf8_async(null, null, (process, result) => {
            try {
                const [, output] = process.communicate_utf8_finish(result);
                if (!this._alive || this._generation !== generation) return;
                if (this._deadline) { GLib.Source.remove(this._deadline); this._deadline = 0; }
                if (!process.get_successful()) throw new Error('상태 조회 실패');
                if (output.length > 1024 * 1024) throw new Error('상태 응답이 너무 큽니다.');
                const data = JSON.parse(output);
                if (!data.ok || data.schema !== 'kiki-admin-v1' || !Array.isArray(data.failed))
                    throw new Error('상태 응답 형식 오류');
                const warning = data.warnings?.length > 0;
                const host = String(data.hostname).slice(0, 48);
                this._label.text = `${host} · ${warning ? '조회 주의' : data.failed.length ? `실패 ${data.failed.length}` : '정상'}`;
                this._summary.label.text = warning ? '일부 정보를 확인하지 못했습니다.' : `실패 서비스 ${data.failed.length}개 · 로컬 장비`;
                this._button.accessible_name = this._label.text;
            } catch (e) {
                if (this._alive && this._generation === generation) {
                    this._label.text = 'KIKI · 조회 실패';
                    this._summary.label.text = '상태를 확인하지 못했습니다. 관리자에서 확인하세요.';
                }
            } finally {
                if (this._process === process) {
                    this._process = null;
                    if (this._deadline) { GLib.Source.remove(this._deadline); this._deadline = 0; }
                }
            }
        });
    }

    disable() {
        this._alive = false;
        if (this._timer) GLib.Source.remove(this._timer);
        if (this._deadline) GLib.Source.remove(this._deadline);
        this._timer = this._deadline = 0;
        this._process?.force_exit(); this._process = null;
        if (this._signal) this._settings.disconnect(this._signal);
        this._signal = 0; this._settings = null;
        if (this._contrastSignal) this._accessibility.disconnect(this._contrastSignal);
        this._contrastSignal = 0; this._accessibility = null;
        this._background = null;
        this._decorated?.forEach(a => {
            for (const style of ['kiki-paper-pixel', 'kiki-pixel-light', 'kiki-pixel-dark'])
                a.remove_style_class_name(style);
        });
        this._decorated = null;
        this._button?.destroy(); this._button = null;
    }
}
