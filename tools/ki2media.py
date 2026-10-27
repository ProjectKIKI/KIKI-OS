"""Read-only local installer media verification; never formats or mounts disks."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import ki2repo


class MediaError(RuntimeError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MediaError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json_bytes(data):
    return json.loads(data, object_pairs_hook=unique_object)


def regular_file(path):
    if path.is_symlink() or not path.is_file():
        raise MediaError(f"missing or non-regular file: {path}")


def check_digest(data_hash, size, expected, label):
    digest = expected.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise MediaError(f"invalid SHA-256: {label}")
    if type(expected.get("size")) is not int or expected["size"] <= 0:
        raise MediaError(f"invalid size: {label}")
    if size != expected["size"] or data_hash != digest:
        raise MediaError(f"integrity mismatch: {label}")


def verify_media(media_root, public_key):
    root = Path(media_root).resolve(strict=True)
    key = Path(public_key).resolve(strict=True)
    if key == root or root in key.parents:
        raise MediaError("trust key must not come from the media being verified")
    for directory in (root / "kiki", root / "kiki/repo", root / "kiki/packages", root / "kiki/packages/x86_64"):
        if directory.is_symlink() or not directory.is_dir():
            raise MediaError(f"invalid media directory: {directory}")
    metadata_path = root / "kiki/repo/metadata.x86_64.json"
    index_path = root / "kiki/repo/index.x86_64.json"
    regular_file(metadata_path)
    regular_file(index_path)
    metadata = read_json_bytes(metadata_path.read_bytes())
    if not isinstance(metadata, dict) or metadata.get("arch") != "x86_64":
        raise MediaError("invalid metadata architecture")
    security = metadata.get("security")
    if not isinstance(security, dict) or security.get("signed") is not True:
        raise MediaError("repository signature required")
    if security.get("algorithm") != "ed25519" or not ki2repo.verify_metadata_ed25519(metadata, key):
        raise MediaError("repository Ed25519 verification failed")
    index_bytes = index_path.read_bytes()
    index_record = metadata.get("index")
    if not isinstance(index_record, dict):
        raise MediaError("signed index descriptor missing")
    check_digest(hashlib.sha256(index_bytes).hexdigest(), len(index_bytes), index_record, "repository index")
    index = read_json_bytes(index_bytes)
    if not isinstance(index, dict) or index.get("arch") != "x86_64":
        raise MediaError("invalid index architecture")
    entries = index.get("packages")
    if not isinstance(entries, list) or not entries:
        raise MediaError("package index is empty or invalid")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise MediaError("invalid package entry")
        name = entry.get("file")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*\.ki2", name) or name in seen:
            raise MediaError(f"invalid or duplicate package filename: {name!r}")
        seen.add(name)
        path = root / "kiki/packages/x86_64" / name
        regular_file(path)
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        check_digest(digest.hexdigest(), size, entry, name)
    return len(entries)


def runtime_closure(index, selected):
    """Resolve only runtime dependencies from an already verified index."""
    entries = {}
    for entry in index['packages']:
        name = entry.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,62}', name) or name in entries:
            raise MediaError('invalid or duplicate package name')
        entries[name] = entry
    result, active, done = [], set(), set()
    def visit(name):
        if not isinstance(name, str) or name not in entries:
            raise MediaError(f'missing runtime dependency: {name!r}')
        if name in done:
            return
        if name in active:
            raise MediaError(f'runtime dependency cycle: {name}')
        active.add(name)
        dependencies = entries[name].get('dependencies', {})
        if not isinstance(dependencies, dict):
            raise MediaError(f'invalid dependency descriptor: {name}')
        deps = dependencies.get('runtime', [])
        if not isinstance(deps, list):
            raise MediaError(f'invalid runtime dependencies: {name}')
        for dependency in deps:
            visit(dependency)
        active.remove(name)
        done.add(name)
        result.append(name)
        if len(result) > 512:
            raise MediaError('resolved package selection exceeds installer capacity')
    for name in selected:
        visit(name)
    if not result:
        raise MediaError('empty package selection')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument('--selection-file', type=Path)
    parser.add_argument('--resolved-file', type=Path)
    args = parser.parse_args()
    try:
        count = verify_media(args.media_root, args.public_key)
        if bool(args.selection_file) != bool(args.resolved_file):
            raise MediaError('selection and resolved files must be supplied together')
        if args.selection_file:
            index = read_json_bytes((args.media_root / 'kiki/repo/index.x86_64.json').read_bytes())
            resolved = runtime_closure(index, args.selection_file.read_text().splitlines())
            args.resolved_file.write_text('\n'.join(resolved) + '\n')
            print(f'Resolved {len(resolved)} packages including required runtime dependencies.')
    except (MediaError, OSError, ValueError, ki2repo.Ki2RepoError) as exc:
        parser.exit(1, f"Media verification failed: {exc}\n")
    print(f"Verified Ed25519 repository, index and {count} packages.")


if __name__ == "__main__":
    main()
