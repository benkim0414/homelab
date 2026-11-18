"""Fake-key coverage for the operator-private desktop enrollment helper."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('desktop_setup', ROOT / 'langfuse/setup-desktop.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
PUBLIC = 'pk-lf-fixtureonly123'
SECRET = 'sk-lf-fixtureonly123'


class DesktopSetupTests(unittest.TestCase):
    def backend(self):
        return Mock()

    def test_valid_prompts_verify_before_save(self):
        backend = self.backend()
        order = []
        backend.save.side_effect = lambda *a: order.append('save')
        verify = lambda *a: order.append('verify')
        m.provision(backend, Mock(side_effect=[PUBLIC, SECRET, SECRET]), verify)
        self.assertEqual(order, ['verify', 'save'])
        backend.save.assert_called_once_with(PUBLIC, SECRET)

    def test_bad_format_never_verifies_or_saves(self):
        for public, secret in [('pk-lf-bad key', SECRET), (PUBLIC, SECRET+'\n')]:
            backend, verify = self.backend(), Mock()
            with self.assertRaises(m.SetupError):
                m.provision(backend, Mock(side_effect=[public, secret, secret]), verify)
            verify.assert_not_called()
            backend.save.assert_not_called()

    def test_confirmation_failure_preserves_credentials(self):
        backend, verify = self.backend(), Mock()
        with self.assertRaises(m.SetupError):
            m.provision(backend, Mock(side_effect=[PUBLIC, SECRET, SECRET+'x']), verify)
        verify.assert_not_called()
        backend.save.assert_not_called()

    def test_project_failure_preserves_credentials(self):
        backend = self.backend()
        with self.assertRaises(m.SetupError):
            m.provision(backend, Mock(side_effect=[PUBLIC, SECRET, SECRET]),
                        Mock(side_effect=m.SetupError('Wrong project')))
        backend.save.assert_not_called()

    def test_preflight_failure_precedes_prompts(self):
        backend, prompt = self.backend(), Mock()
        backend.preflight.side_effect = m.SetupError('Disabled required')
        with self.assertRaises(m.SetupError):
            m.provision(backend, prompt, Mock())
        prompt.assert_not_called()

    def test_project_get_uses_fixed_https_and_no_redirect(self):
        response = Mock()
        response.read.return_value = json.dumps({'data':[{'name':'hermes-desktop'}]}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(m.urllib.request, 'build_opener', return_value=opener) as build:
            m.verify_project(PUBLIC, SECRET)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, m.PROJECT_URL)
        self.assertEqual(request.method, 'GET')
        self.assertIsInstance(build.call_args.args[0], m.NoRedirect)
        self.assertIsNone(m.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid'))

    def test_wrong_project_rejected(self):
        for name in ['hermes-cluster', 'unexpected']:
            response = Mock()
            response.read.return_value = json.dumps({'data':[{'name':name}]}).encode()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            opener = Mock(); opener.open.return_value = response
            with patch.object(m.urllib.request, 'build_opener', return_value=opener):
                with self.assertRaises(m.SetupError):m.verify_project(PUBLIC, SECRET)

    def test_argument_values_not_echoed(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(m.main(['--key', SECRET]), 2)
        self.assertNotIn(SECRET, output.getvalue())

    def test_noninteractive_does_not_load_backend(self):
        with patch.object(m.sys.stdin, 'isatty', return_value=False), patch.object(m, 'NativeBackend') as backend, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m.main(['default']), 2)
        backend.assert_not_called()

    def test_native_writer_in_isolated_temporary_profile(self):
        python = Path.home() / '.hermes/hermes-agent/venv/bin/python'
        if not python.is_file():self.skipTest('Installed desktop Hermes interpreter unavailable')
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, HERMES_HOME=temporary)
            code = '''import importlib.util,os
from pathlib import Path
s=importlib.util.spec_from_file_location('setup',os.environ['FIXTURE_HELPER']);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
b=m.NativeBackend('default');p=b.config.get_env_path();assert p==Path(os.environ['HERMES_HOME'])/'.env'
p.write_text('UNRELATED=fixture-preserved\\n');p.chmod(0o600)
b.save('pk-lf-fixtureonly123','sk-lf-fixtureonly123')
assert b.config.load_env()['UNRELATED']=='fixture-preserved'
assert p.stat().st_mode & 0o777==0o600
try:b.preflight()
except m.SetupError:pass
else:raise AssertionError('Existing keys must not be replaced')
assert not ({'langfuse','observability/langfuse'} & b.enabled())
'''
            env['FIXTURE_HELPER'] = str(ROOT / 'langfuse/setup-desktop.py')
            result = subprocess.run([str(python), '-B', '-c', code], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, 'Isolated native-writer fixture failed; output withheld')


if __name__ == '__main__':
    unittest.main()
