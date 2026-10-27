import unittest
import ki2media


def index(*entries):
    return {'packages': [{'name': name, 'dependencies': {'runtime': deps}} for name, deps in entries]}


class RuntimeDependencyTests(unittest.TestCase):
    def test_transitive_dependencies_ordered_and_deduplicated(self):
        data = index(('firewalld', ['glib', 'python']), ('glib', ['libffi']), ('python', ['libffi']), ('libffi', []))
        self.assertEqual(ki2media.runtime_closure(data, ['firewalld', 'glib']), ['libffi', 'glib', 'python', 'firewalld'])

    def test_missing_dependency_and_cycles_rejected(self):
        for data in [index(('app', ['missing'])), index(('app', ['app'])), index(('app', ['b']), ('b', ['app']))]:
            with self.assertRaises(ki2media.MediaError):
                ki2media.runtime_closure(data, ['app'])

    def test_duplicate_names_empty_and_capacity_rejected(self):
        for data, selected in [(index(('app', []), ('app', [])), ['app']), (index(('app', [])), []),
                               (index(*[(f'p{i}', []) for i in range(513)]), [f'p{i}' for i in range(513)])]:
            with self.assertRaises(ki2media.MediaError):
                ki2media.runtime_closure(data, selected)

    def test_desktop_sized_runtime_closure(self):
        data = index(*[(f'p{i}', []) for i in range(182)])
        self.assertEqual(len(ki2media.runtime_closure(data, [f'p{i}' for i in range(182)])), 182)


if __name__ == '__main__':
    unittest.main()
