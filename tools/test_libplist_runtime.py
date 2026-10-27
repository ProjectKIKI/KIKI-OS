"""Opt-in upstream libplist scripts with KIKI packaged libraries and temp outputs.

Host /bin/sh and timezone database are used; no desktop/session/device operations.
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('KIKI_LIBPLIST_TEST_SOURCE'),
                     'set KIKI_LIBPLIST_TEST_SOURCE to the completed build source on Linux')
class LibplistRuntimeTests(unittest.TestCase):
    def test_upstream_scripts_with_packaged_libraries(self):
        source = Path(os.environ['KIKI_LIBPLIST_TEST_SOURCE']).resolve(strict=True)
        makefile = (source / 'test/Makefile.am').read_text()
        block = re.search(r'^TESTS = (.*?)(?:\n\n)', makefile, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(block)
        tests = re.findall(r'[A-Za-z0-9_+.-]+\.test', block.group(1))
        self.assertEqual(len(tests), 41)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / 'distro/recipes')
        ordered = ki2build.dependency_closure(recipes, ['libplist'], 'x86_64', include_build_deps=False)
        with tempfile.TemporaryDirectory(prefix='kiki-libplist-tests-') as tmp:
            work = Path(tmp)
            root = work / 'root'
            for name in ordered:
                package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipes[name], 'x86_64')
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            library_path = ':'.join(str(root / p) for p in ('usr/lib', 'usr/lib64', 'lib', 'lib64'))
            env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C',
                   'top_srcdir': str(source), 'top_builddir': str(work)}
            binaries = {name: source / 'test/.libs' / name for name in (
                'plist_cmp', 'plist_test', 'plist_test++', 'integer_set_test',
                'plist_btest', 'plist_jtest', 'plist_otest')}
            binaries['plistutil'] = root / 'usr/bin/plistutil'
            (work / 'test/data').mkdir(parents=True)
            (work / 'tools').mkdir()
            for name, binary in binaries.items():
                self.assertTrue(binary.is_file(), str(binary))
                command = [str(loaders[0]), '--inhibit-cache', '--library-path', library_path, str(binary)]
                listing = subprocess.run(command[:-1] + ['--list', str(binary)],
                                         env=env, text=True, capture_output=True, timeout=15)
                self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
                resolved = re.findall(r'=> (\S+) \(', listing.stdout)
                self.assertTrue(resolved, listing.stdout)
                for path in resolved:
                    self.assertTrue(Path(path).resolve().is_relative_to(root), listing.stdout)
                wrapper = work / ('tools' if name == 'plistutil' else 'test') / name
                wrapper.write_text('#!/bin/sh\nexec ' + shlex.join(command) + ' "$@"\n')
                wrapper.chmod(0o755)
            passed = 0
            for name in tests:
                with self.subTest(script=name):
                    result = subprocess.run(['/bin/sh', str(source / 'test' / name)],
                                            cwd=work, env=env, capture_output=True, text=True, timeout=60)
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode, 0, output)
                    # Old scripts can exit zero even when an invalid test operator ran.
                    self.assertNotRegex(result.stderr,
                                        r'unexpected operator|(?:unary|binary) operator expected')
                    passed += 1
            print(f'libplist upstream scripts passed: {passed}/{len(tests)}')


if __name__ == '__main__':
    unittest.main()
