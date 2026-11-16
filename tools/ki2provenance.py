"""Validate archive build inputs and bind installer origin to verified media."""
import hashlib
import json
import re
import tarfile
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate provenance key: ' + key)
        result[key] = value
    return result


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('provenance input must be a regular file')
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def digest(value, length=64):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{' + str(length) + '}', value):
        raise ValueError('invalid provenance digest')
    return value


def load_build_inputs(repo_root, receipt):
    root = Path(repo_root).resolve()
    receipt = Path(receipt).resolve()
    data = read(receipt)
    if data.get('schema') != 'kiki-build-inputs-v1' or data.get('source_state') not in {'clean', 'modified-candidate'}:
        raise ValueError('unsupported build input receipt')
    digest(data['source_commit'], 40)
    name = data['source_archive']
    if not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError('archive must be next to the input receipt')
    archive = receipt.parent / name
    if sha(archive) != digest(data['source_archive_sha256']):
        raise ValueError('source archive SHA mismatch')
    files = data['files']
    if not isinstance(files, dict) or not files:
        raise ValueError('source file inventory is required')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*')
              if p.is_file() and '.git' not in p.relative_to(root).parts and '__pycache__' not in p.relative_to(root).parts}
    if set(files) != actual:
        raise ValueError('source file inventory changed')
    for name, expected in files.items():
        p = root / name
        if Path(name).is_absolute() or '..' in Path(name).parts or p.is_symlink() or not p.resolve().is_relative_to(root):
            raise ValueError('unsafe source input path')
        if sha(p) != digest(expected):
            raise ValueError('source file SHA mismatch: ' + name)
    tree_sha = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if tree_sha != digest(data['source_tree_sha256']):
        raise ValueError('source tree SHA mismatch')
    archived = {}
    with tarfile.open(archive) as tf:
        for member in tf:
            if not member.isfile() or member.name in archived:
                raise ValueError('source archive must contain unique regular files')
            archived[member.name] = hashlib.sha256(tf.extractfile(member).read()).hexdigest()
    if archived != files:
        raise ValueError('archive and working source differ')
    return dict(commit=data['source_commit'], source_state=data['source_state'],
                dirty=data['source_state'] != 'clean', commit_role='base-with-input-lock' if data['source_state'] != 'clean' else 'source-commit',
                source_archive_sha256=data['source_archive_sha256'], source_tree_sha256=tree_sha,
                input_manifest_sha256=sha(receipt))


def media_origin(build_info, repo_dir, arch='x86_64'):
    repo = Path(repo_dir)
    metadata = read(repo / ('metadata.' + arch + '.json'))
    channel = metadata.get('channel')
    if not isinstance(channel, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,94}', channel):
        raise ValueError('invalid actual repository channel')
    index_sha = sha(repo / ('index.' + arch + '.json'))
    if metadata['index']['sha256'] != index_sha:
        raise ValueError('metadata/index origin mismatch')
    return dict(schema='kiki-installer-origin-v1', channel=channel,
                metadata_sha256=sha(repo / ('metadata.' + arch + '.json')), repository_index_sha256=index_sha,
                source_commit=build_info.get('commit', 'unknown'),
                source_state=build_info.get('source_state', 'unrecorded'),
                **{k: build_info.get(k) for k in ['source_archive_sha256', 'source_tree_sha256', 'input_manifest_sha256']})


def verified_origin_values(media_root, descriptor):
    """Caller must first run ki2media.verify_media with an external trust key."""
    root = Path(media_root)
    origin = read(descriptor)
    if origin.get('schema') != 'kiki-installer-origin-v1':
        raise ValueError('unsupported installer origin')
    actual = media_origin({}, root / 'kiki/repo')
    for field in ['channel', 'metadata_sha256', 'repository_index_sha256']:
        if origin.get(field) != actual[field]:
            raise ValueError('verified media origin mismatch: ' + field)
    if origin.get('input_manifest_sha256') is not None:
        receipt = root / 'kiki/build-inputs.json'
        if sha(receipt) != digest(origin['input_manifest_sha256']):
            raise ValueError('media build input receipt mismatch')
        inputs = read(receipt)
        for key in ['source_commit', 'source_archive_sha256', 'source_tree_sha256', 'source_state']:
            if inputs.get(key) != origin.get(key):
                raise ValueError('build input origin mismatch: ' + key)
        digest(origin['source_commit'], 40)
        for key in ['source_archive_sha256', 'source_tree_sha256']:
            digest(origin[key])
    keys = ['channel', 'source_commit', 'source_state', 'source_archive_sha256', 'source_tree_sha256', 'input_manifest_sha256', 'repository_index_sha256']
    return {k: origin.get(k) or 'unknown' for k in keys}


def origin_text(media_root, descriptor):
    values = verified_origin_values(media_root, descriptor)
    return ''.join(k + '=' + v + '\n' for k, v in values.items())
