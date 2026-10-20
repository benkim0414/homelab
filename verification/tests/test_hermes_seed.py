"""Check that Hermes bootstrap preserves operator files and symlinks."""
import os
from pathlib import Path
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = yaml.safe_load((ROOT / 'hermes/configmap.yaml').read_text())['data']
DEPLOYMENT = next(doc for doc in yaml.safe_load_all(
    (ROOT / 'hermes/deployment.yaml').read_text()) if doc['kind'] == 'Deployment')


class HermesSeedTests(unittest.TestCase):
    def test_seed_preserves_existing_config_instructions_and_symlinks(self):
        source = DEPLOYMENT['spec']['template']['spec']['initContainers'][0]['args'][0]
        with tempfile.TemporaryDirectory(dir=ROOT / 'verification/cache') as directory:
            root = Path(directory)
            bootstrap, state = root / 'bootstrap', root / 'data'
            bootstrap.mkdir()
            for name in ('config.yaml', 'AGENTS.md'):
                (bootstrap / name).write_text(DATA[name])
            script = source.replace('/bootstrap/', str(bootstrap) + '/').replace(
                '/opt/data', str(state))

            def seed():
                previous_umask = os.umask(0o077)
                try:
                    exec(compile(script, 'seed-config', 'exec'), {})
                finally:
                    os.umask(previous_umask)

            seed()
            config, instructions = state / 'config.yaml', state / 'workspace/AGENTS.md'
            self.assertEqual(instructions.read_text(), DATA['AGENTS.md'])
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            config.write_text('operator-selected model')
            instructions.write_text('operator instructions')
            seed()
            self.assertEqual(config.read_text(), 'operator-selected model')
            self.assertEqual(instructions.read_text(), 'operator instructions')
            instructions.unlink()
            target = root / 'untouched'
            instructions.symlink_to(target)
            seed()
            self.assertTrue(instructions.is_symlink())
            self.assertFalse(target.exists())
