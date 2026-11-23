"""Only synthetic, no-LLM database fixture configuration is admitted."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'hindsight/extensions/specialist-memory/validation/fixture_env.py'


class FixtureEnvironmentTests(unittest.TestCase):
    def test_fixture_has_no_provider_or_credential_fallback(self):
        self.assertTrue(SOURCE.is_file(), 'isolated runtime environment builder is missing')
        spec = importlib.util.spec_from_file_location('specialist_fixture_env', SOURCE)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        keys = {key: 'fixture-'+key for key in module.KEY_FIELDS}
        env = module.environment('hs-memory-db-123456abcdef', keys)
        self.assertEqual(env['HINDSIGHT_API_LLM_PROVIDER'],'none')
        self.assertEqual(env['HINDSIGHT_API_EMBEDDINGS_PROVIDER'],'onnx')
        self.assertEqual(env['HINDSIGHT_API_RERANKER_PROVIDER'],'rrf')
        self.assertEqual(env['HINDSIGHT_API_EMBEDDINGS_ONNX_MODEL_PATH'],'/models/onnx/model.onnx')
        self.assertEqual(env['HINDSIGHT_API_EMBEDDINGS_ONNX_TOKENIZER_NAME_OR_PATH'],'/models')
        self.assertEqual(env['HF_HUB_OFFLINE'],'1')
        docker_name = 'specialist-validation-'+'a'*32
        self.assertIn('@'+docker_name+':5432/',module.environment(docker_name,keys)['HINDSIGHT_API_DATABASE_URL'])
        self.assertFalse(any(key in env for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','HINDSIGHT_API_LLM_API_KEY')))
        for key in module.KEY_FIELDS:
            self.assertEqual(env['HINDSIGHT_API_TENANT_'+key.upper()], keys[key])
            self.assertEqual(env['HINDSIGHT_API_OPERATION_VALIDATOR_'+key.upper()], keys[key])
        for bad in ({**keys, 'api_key':'not-an-admitted-fixture'}, {**keys, 'api_key':'fixture-key\ninjected=value'}):
            with self.assertRaises(ValueError): module.environment('hs-memory-db-123456abcdef', bad)
        with self.assertRaises(ValueError): module.environment('production.example.com', keys)


if __name__ == '__main__':
    unittest.main()
