import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
import ki2planning as planning


class PlanningTests(unittest.TestCase):
    def test_dependency_closure_and_revision_are_pinned(self):
        def recipe(deps):
            return SimpleNamespace(version='1', summary='설명', license='MIT', tier='extra', source={'type':'local'}, dependencies={'runtime':deps}, build={'system':'copy'})
        store=SimpleNamespace(recipes=lambda:{'a':recipe([]),'b':recipe(['a']),'c':recipe(['b'])},current=lambda:{'revision':7,'metadata':{}})
        row=planning.context(store,'a','2')
        self.assertEqual(row['affected'],['b','c']);self.assertEqual(row['revision'],7)
        with self.assertRaises(ValueError):planning.context(store,'absent')

    def test_suggestion_schema_rejects_commands_and_bad_types(self):
        good=dict(summary='설명',license='MIT',tier='extra',evidence='기존 명세')
        self.assertEqual(planning.suggestions(json.dumps(good)),good)
        for bad in [dict(good,command='rm'),dict(good,license=[]),dict(good,tier='a\nb')]:
            with self.assertRaises(ValueError):planning.suggestions(json.dumps(bad))

    def test_review_escapes_model_output_and_preserves_revision(self):
        data=dict(package='a',revision=7,metadata={},summary='old',license='MIT',tier='extra')
        report=dict(task='metadata',planning=data,answer=json.dumps(dict(summary='<script>x</script>',license='MIT',tier='extra',evidence='출처')))
        body=planning.result_html(report)
        self.assertNotIn('<script>',body);self.assertIn('name="revision" value="7"',body)
        self.assertIn('/packages/metadata',body)

    def test_kernel_static_probe_never_claims_runtime_support(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config';path.write_text('CONFIG_MODULES=y\nCONFIG_DEBUG_INFO_NONE=y\n')
            row=planning.kernel_probe(path)
            self.assertFalse(row['configuration_ready']);self.assertFalse(row['runtime_verified'])
            self.assertFalse(row['module_loaded']);self.assertIn('CONFIG_LIVEPATCH',row['missing'])


if __name__=='__main__':unittest.main()
