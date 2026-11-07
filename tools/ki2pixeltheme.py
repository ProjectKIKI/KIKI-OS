"""Generate the isolated Shell and administrator palettes from shared tokens."""
import argparse
import json
from pathlib import Path
import re


def scoped(prefix, selectors):
    return ',\n'.join(f'{prefix} {s}' for s in selectors)


def outputs(repo):
    assets = repo/'assets/desktop/paper-pixel'
    shell = repo/'desktop/gnome/kiki-ops'
    tokens = json.loads((assets/'tokens.json').read_text())
    for palette in [tokens['light'], tokens['dark'], tokens['status']]:
        if not all(isinstance(v, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', v) for v in palette.values()):
            raise ValueError('Palette values must be six-digit hex colors')
    css = [(shell/'base.css').read_text()]
    result = {}
    cards = ['.popup-menu-content', '.quick-settings', '.quick-toggle-menu', '.datemenu-popover',
             '.calendar', '.events-button', '.world-clocks-button', '.weather-button', '.datemenu-today-button', '.search-entry', '#dash .dash-background',
             '.search-section-content', '.app-folder-dialog', '.notification-banner', '.message',
             '.modal-dialog', '.modal-dialog StEntry', '.osd-window', '.switcher-list', '.window-caption']
    controls = ['.quick-toggle', '.quick-toggle-menu-button', '.icon-button', '.modal-dialog-button',
                '.notification-button', '.message-list-clear-button', '.window-close', '.toggle-switch']
    hover = ['.quick-toggle:hover', '.icon-button:hover', '.popup-menu-item:hover', '.calendar-day:hover',
             '.overview-tile:hover', '#dash .dash-item-container .overview-tile:hover .overview-icon', '#dash .dash-item-container .show-apps:hover .overview-icon',
             '.modal-dialog-button:hover', '.notification-button:hover', '.message-list-clear-button:hover']
    selected = ['.quick-toggle:checked', '.quick-toggle-menu-button:checked', '.toggle-switch:checked',
                '.popup-menu-item:focus', '.popup-menu-item:active', '.calendar-day.calendar-today',
                '.overview-tile:focus', '.overview-tile:active', '#dash .dash-item-container .overview-tile:focus .overview-icon',
                '#dash .dash-item-container .overview-tile:checked .overview-icon', '#dash .dash-item-container .show-apps:checked .overview-icon',
                '.modal-dialog-button.default']
    for mode in ['light', 'dark']:
        p = tokens[mode]; prefix = '.kiki-paper-pixel.kiki-pixel-'+mode
        css.append(f'{prefix} {{ color: {p["text"]}; }}')
        css.append(f'{prefix} #overviewGroup {{ background-color: {p["background"]}; color: {p["text"]}; }}')
        css.append(scoped(prefix, ['#dash .dash-item-container .overview-tile .overview-icon',
                    '#dash .dash-item-container .show-apps .overview-icon'])+
                   f' {{ background-color: transparent; color: {p["text"]}; }}')
        css.append(scoped(prefix, ['.overview-tile', '.overview-tile .overview-icon', '.app-folder', '.search-provider-icon'])+
                   f' {{ color: {p["text"]}; }}')
        css.append(scoped(prefix, cards)+f' {{ background-color: {p["paper"]}; color: {p["text"]}; border-color: {p["border"]}; }}')
        css.append(scoped(prefix, controls)+f' {{ background-color: {p["surface"]}; color: {p["text"]}; }}')
        css.append(scoped(prefix, hover)+f' {{ background-color: {p["hover"]}; color: {p["text"]}; }}')
        css.append(scoped(prefix, selected)+f' {{ background-color: {tokens["status"]["selected"]}; color: #ffffff; }}')
        css.append(scoped(prefix, ['#panel', '#panel:overview'])+f' {{ background-color: {p["panel"]}; color: {p["text"]}; border-color: {p["border"]}; }}')
        css.append(scoped(prefix, ['#panel .panel-button', '#panel:overview .panel-button',
                    '#panel .panel-button.clock-display .clock', '#panel:overview .panel-button.clock-display .clock'])+
                   f' {{ color: {p["text"]}; }}')
        css.append(scoped(prefix, ['#panel .panel-button:hover', '#panel .panel-button:active',
                    '#panel:overview .panel-button:hover', '#panel:overview .panel-button:active'])+
                   f' {{ background-color: {p["hover"]}; }}')
        css.append(scoped(prefix, ['#panel .panel-button#panelActivities .workspace-dot',
                    '#panel:overview .panel-button#panelActivities .workspace-dot'])+
                   f' {{ background-color: {p["text"]}; }}')
        css.append(scoped(prefix, ['.search-statustext', '.message-list-placeholder', '.dash-label'])+
                   f' {{ color: {p["text"]}; }}')
        css.append(scoped(prefix, ['.events-title', '.event-placeholder', '.event-time', '.world-clocks-header',
                    '.world-clocks-timezone', '.weather-header', '.message .message-header'])+
                   f' {{ color: {p["muted"]}; }}')
        css.append(f'{prefix} .search-entry StLabel.hint-text {{ color: {p["muted"]}; }}')
        css.append(f'{prefix} .calendar .calendar-month-label {{ color: {p["text"]} !important; }}')
        css.append(f'{prefix} .app-grid-running-dot {{ background-color: {tokens["status"]["healthy"]}; }}')
        css.append(f'{prefix} .workspace-thumbnail-indicator {{ border-color: {tokens["status"]["selected"]}; }}')
        colors = dict(window_bg_color=p['background'], window_fg_color=p['text'], view_bg_color=p['paper'],
                      view_fg_color=p['text'], headerbar_bg_color=p['panel'], headerbar_fg_color=p['text'],
                      sidebar_bg_color=p['surface'], sidebar_fg_color=p['text'], card_bg_color=p['paper'],
                      card_fg_color=p['text'], borders=p['border'], accent_bg_color=tokens['status']['selected'], accent_fg_color='#ffffff')
        gtk = '\n'.join(f'@define-color {k} {v};' for k,v in colors.items())
        gtk += '\n:root { '+ ' '.join(f'--{k.replace("_", "-")}: {v};' for k,v in colors.items() if k!='borders')+' }\n'
        result[assets/f'admin-{mode}.css'] = gtk
    result[shell/'stylesheet.css'] = '\n\n'.join(css)+'\n'
    result[shell/'palette.js'] = '// Generated from shared tokens.\nexport const PAPER_COLORS = '+json.dumps(
        {mode:tokens[mode]['background'] for mode in ['light','dark']},sort_keys=True)+';\n'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for path, content in outputs(Path(__file__).resolve().parents[1]).items():
        if args.check:
            if not path.is_file() or path.read_text()!=content:
                raise SystemExit('Generated palette is stale: '+str(path))
        else:
            path.write_text(content,encoding='utf-8',newline='\n')


if __name__=='__main__':main()
