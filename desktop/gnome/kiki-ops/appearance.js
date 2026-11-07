// Pure helpers: custom wallpaper choices and page arguments stay bounded.
import {PAPER_COLORS} from './palette.js';
const PAPER = 'file:///usr/share/kiki-paper-pixel/';

export function configureWallpaper(settings, dark) {
    for (const [key, file] of [['picture-uri', 'wallpaper-light.svg'], ['picture-uri-dark', 'wallpaper-dark.svg']]) {
        if (settings.get_user_value(key) === null)
            settings.set_string(key, PAPER + file);
    }
    const own = settings.get_string('picture-uri') === PAPER + 'wallpaper-light.svg' &&
        settings.get_string('picture-uri-dark') === PAPER + 'wallpaper-dark.svg';
    if (!own)
        return;
    // Fit the complete image on 4:3, widescreen and portrait displays. A matching
    // solid fill makes the remaining area seamless, without stretching pixels.
    if (settings.get_user_value('picture-options') === null)
        settings.set_string('picture-options', 'scaled');
    if (settings.get_string('picture-options') === 'scaled') {
        const color = PAPER_COLORS[dark ? 'dark' : 'light'];
        settings.set_string('primary-color', color);
        settings.set_string('secondary-color', color);
    }
}

export function adminCommand(page) {
    if (!['overview', 'diagnostics'].includes(page))
        throw new Error('Unsupported administrator page');
    return `/usr/bin/kiki-admin --page ${page}`;
}
