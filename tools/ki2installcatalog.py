"""Shared installer catalogue: expand groups, check media, generate native tables."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'distro/sources/ki2ctl/usr/share/ki2/package-groups.json'


def catalog_path():
    return Path(os.environ.get('KI2_PACKAGE_GROUPS_FILE') or CATALOG)


def load(path=None):
    data = json.loads(Path(path if path is not None else catalog_path()).read_text(encoding='utf-8'))
    if data.get('schema') != 'ki2-package-groups-v1':
        raise ValueError('Unsupported installer catalogue')
    for section in ('groups', 'profiles'):
        ids = [x['id'] for x in data[section]]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate catalogue identifiers')
    return data


def expand(data, selected):
    groups = {g['id']: g for g in data['groups']}
    result = dict(groups=[], packages=[], enable=[], disable=[], default_target='multi-user.target')
    active = set()

    def visit(name):
        if name in active:
            raise ValueError('Package group cycle: ' + name)
        if name in result['groups']:
            return
        active.add(name)
        group = groups[name]
        for dep in group['requires']:
            visit(dep)
        active.remove(name)
        result['groups'].append(name)
        for kind in ('mandatory', 'default'):
            result['packages'].extend(group['packages'][kind])
        for kind in ('enable', 'disable'):
            result[kind].extend(group['services'].get(kind, []))
        result['default_target'] = group['services'].get('default_target', result['default_target'])
    for name in selected:
        visit(name)
    for key in ('packages', 'enable', 'disable'):
        result[key] = list(dict.fromkeys(result[key]))
    result['enable'] = [x for x in result['enable'] if x not in result['disable']]
    return result


def media_catalog(index, data=None):
    import ki2media
    explicit = data is not None
    data = data if explicit else load()
    entries = {p['name']: p for p in index['packages']}
    content = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode('utf-8') if explicit else catalog_path().read_bytes()
    result = dict(schema='kiki-installer-media-v1', catalog_sha256=hashlib.sha256(content).hexdigest())
    for section in ('profiles', 'groups'):
        result[section] = []
        for item in data[section]:
            selected = item['groups'] if section == 'profiles' else [item['id']]
            ai_default = item.get('ai_default', 'off')
            if section == 'profiles' and ai_default == 'local':
                try:
                    ki2media.runtime_closure(index, expand(data, ['ai-console'])['packages'])
                    selected = [*selected, 'ai-console']
                except ki2media.MediaError:
                    # AI is optional: a desktop medium can still install a server.
                    ai_default = 'off'
            expanded = expand(data, selected)
            record = dict(id=item['id'], available=False, packages=0, download_bytes=0, missing=[],
                          default_target=expanded['default_target'])
            if section == 'profiles': record['ai_default'] = ai_default
            try:
                closure = ki2media.runtime_closure(index, expanded['packages'])
                record.update(available=True, packages=len(closure),
                              download_bytes=sum(entries[n]['size'] for n in closure))
            except ki2media.MediaError as error:
                record['missing'] = [str(error)]
            result[section].append(record)
    return result


def media_ini(catalog):
    lines = ['[media]', 'schema=kiki-installer-media-v1', 'default_profile=' + catalog.get('default_profile', 'server-core')]
    for section in ('profiles', 'groups'):
        for item in catalog[section]:
            lines += ['', '[' + section[:-1] + ' ' + item['id'] + ']',
                      'available=' + str(item['available']).lower(),
                      'packages=' + str(item['packages']), 'download_bytes=' + str(item['download_bytes']),
                      'reason=' + '; '.join(item['missing']).replace('\n', ' ')]
            if section == 'profiles': lines.append('ai_default=' + item['ai_default'])
    return '\n'.join(lines) + '\n'


def c_array(values):
    return '{' + ', '.join([*(json.dumps(v, ensure_ascii=False) for v in values), 'NULL']) + '}'


def backend_c(data=None):
    data = data or load()
    lines = ['/* Generated from package-groups.json by ki2installcatalog. */']
    for group in data['groups']:
        ident = group['id'].replace('-', '_')
        lines.append('static const char *const catalog_' + ident + '[] = ' +
                     c_array(group['packages']['mandatory'] + group['packages']['default']) + ';')
        for policy in ('enable', 'disable'):
            lines.append('static const char *const catalog_' + ident + '_' + policy + '[] = ' + c_array(group['services'].get(policy, [])) + ';')
    lines += ['typedef struct { const char *id; const char *const *packages; const char *const *enable; const char *const *disable; } CatalogGroup;',
              'static const CatalogGroup catalog_group_policies[] = {']
    for g in data['groups']:
        ident = 'catalog_' + g['id'].replace('-', '_')
        lines.append('{' + json.dumps(g['id']) + ', ' + ', '.join([ident, ident+'_enable', ident+'_disable']) + '},')
    lines += ['{NULL, NULL, NULL, NULL}', '};']
    return '\n'.join(lines)


def generated(data=None):
    data = data or load()
    go_list = lambda xs: '[]string{' + ', '.join(json.dumps(s, ensure_ascii=False) for s in xs) + '}'
    go = ['// Code generated by tools/ki2installcatalog.py; DO NOT EDIT.', 'package main',
          'type catalogGroup struct { Packages, Enable, Disable, Requires []string; DefaultTarget string }',
          'var catalogGroups = map[string]catalogGroup{']
    for g in data['groups']:
        s = g['services']
        go.append(json.dumps(g['id']) + ': {' + ', '.join([
            'Packages: ' + go_list(g['packages']['mandatory'] + g['packages']['default']),
            'Enable: ' + go_list(s.get('enable', [])), 'Disable: ' + go_list(s.get('disable', [])),
            'Requires: ' + go_list(g['requires']), 'DefaultTarget: ' + json.dumps(s.get('default_target', ''))]) + '},')
    go += ['}', 'type catalogProfile struct { Groups []string; AIDefault string }',
           'var catalogProfiles = map[string]catalogProfile{']
    for p in data['profiles']:
        go.append(json.dumps(p['id']) + ': {Groups: ' + go_list(p['groups']) + ', AIDefault: ' + json.dumps(p['ai_default']) + '},')
    go += ['}', 'var selectablePackageGroups = ' + go_list([g['id'] for g in data['groups'] if g.get('selectable', True)])]
    aliases = {'minimalSystemdPackages': ('minimal', 'Packages'), 'minimalSystemdServices': ('minimal', 'Enable'),
               'serverCorePackages': ('server', 'Packages'), 'serverCoreServices': ('server', 'Enable'),
               'kubernetesCommonPackages': ('kubernetes-node', 'Packages'),
               'crioRuntimePackages': ('container-crio', 'Packages'),
               'containerdStandalonePackages': ('container-containerd', 'Packages'),
               'containerdServices': ('container-containerd', 'Enable')}
    for var, (group, field) in aliases.items():
        go.append('var ' + var + ' = catalogGroups[' + json.dumps(group) + '].' + field)
    h = ['/* Generated by tools/ki2installcatalog.py; DO NOT EDIT. */', '#pragma once']
    profiles = data['profiles']
    for name, key in [('profiles', 'id'), ('profile_labels_ko', 'name_ko'), ('profile_labels_en', 'name_en'), ('profile_ai_defaults', 'ai_default')]:
        h.append('static const char *' + name + '[] = ' + c_array([p[key] for p in profiles]) + ';')
    groups = [g for g in data['groups'] if g.get('selectable', True) and g['id'] not in ('minimal', 'ai-console', 'ai-console-remote', 'kubernetes-node')]
    for name, key in [('extra_group_ids', 'id'), ('extra_group_labels_ko', 'name_ko'), ('extra_group_labels_en', 'name_en')]:
        h.append('static const char *' + name + '[] = ' + c_array([g.get(key, g['id']) for g in groups]) + ';')
    return {ROOT / 'cmd/kiki-installer-tui/catalog_generated.go': '\n'.join(go) + '\n',
            ROOT / 'cmd/kiki-installer-gtk/catalog.generated.h': '\n'.join(h) + '\n'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check', action='store_true')
    args = p.parse_args()
    for path, content in generated().items():
        if args.check:
            if not path.is_file() or path.read_text(encoding='utf-8') != content:
                raise SystemExit('Stale installer catalogue: ' + str(path))
        else:
            path.write_text(content, encoding='utf-8')


if __name__ == '__main__':
    main()
