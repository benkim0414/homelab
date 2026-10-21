"""Exercise source staging without changing the destination volume's mode."""
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class HermesSourceTests(unittest.TestCase):
    def test_source_copy_preserves_volume_root_and_includes_hidden_files(self):
        documents = yaml.safe_load_all((ROOT / 'hermes/deployment.yaml').read_text())
        deployment = next(doc for doc in documents if doc['kind'] == 'Deployment')
        container = next(item for item in deployment['spec']['template']['spec']['initContainers']
                         if item['name'] == 'webui-agent-source')
        with tempfile.TemporaryDirectory(dir=ROOT / 'verification/cache') as directory:
            source = Path(directory) / 'source'
            target = Path(directory) / 'target'
            source.mkdir(mode=0o755)
            target.mkdir()
            target.chmod(0o2775)
            included = ['pyproject.toml', 'run_agent.py', '.hidden', 'tools/keep.py']
            excluded = ['.venv/package', '.git/config', '.playwright/browser',
                        'tools/__pycache__/compiled.pyc', 'tools/.install.lock']
            for name in included + excluded:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            (source / 'tools/.install.lock').chmod(0)
            command = container['args'][0].replace('/opt/hermes', str(source)).replace(
                '/agent-source', str(target))
            result = subprocess.run(container['command'] + [command],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o2775)
            self.assertEqual(sorted(str(path.relative_to(target))
                                    for path in target.rglob('*') if path.is_file()),
                             sorted(included))
            for name in included:
                self.assertEqual((target / name).read_text(), name)
