import assert from 'node:assert/strict';
import {test} from 'node:test';
import {adminCommand, configureWallpaper} from '../desktop/gnome/kiki-ops/appearance.js';

const paper = 'file:///usr/share/kiki-paper-pixel/';
function settings(defaults={}, user={}) {
    return {user: {...user}, get_user_value(k) { return this.user[k] ?? null; },
        get_string(k) { return this.user[k] ?? defaults[k] ?? ''; },
        set_string(k,v) { this.user[k]=v; }};
}
test('default and r3 wallpapers fit the full image instead of cropping ornaments', () => {
    for (const user of [{}, {'picture-uri':paper+'wallpaper-light.svg','picture-uri-dark':paper+'wallpaper-dark.svg'}]) {
        const s=settings({'picture-options':'zoom'},user);
        configureWallpaper(s,false);
        assert.equal(s.user['picture-options'],'scaled');
        assert.equal(s.user['primary-color'],'#eeeade');
        configureWallpaper(s,true);
        assert.equal(s.user['primary-color'],'#151c25');
        assert.equal(s.user['secondary-color'],'#151c25');
    }
});
test('custom images, fill colors and sizing remain untouched', () => {
    const user={'picture-uri':'file:///home/kiki/custom.png','picture-uri-dark':'file:///home/kiki/dark.png',
        'picture-options':'zoom','primary-color':'#123456','secondary-color':'#abcdef'};
    const s=settings({},user);configureWallpaper(s,true);assert.deepEqual(s.user,user);
});
test('an explicit user sizing preference is preserved even with Paper images', () => {
    const user={'picture-uri':paper+'wallpaper-light.svg','picture-uri-dark':paper+'wallpaper-dark.svg',
        'picture-options':'zoom','primary-color':'#123456'};
    const s=settings({},user);configureWallpaper(s,false);assert.deepEqual(s.user,user);
});
test('only fixed administrator pages can enter the launch command', () => {
    assert.equal(adminCommand('overview'),'/usr/bin/kiki-admin --page overview');
    assert.equal(adminCommand('diagnostics'),'/usr/bin/kiki-admin --page diagnostics');
    for (const value of ['overview; reboot','--help','',null])assert.throws(()=>adminCommand(value));
});
