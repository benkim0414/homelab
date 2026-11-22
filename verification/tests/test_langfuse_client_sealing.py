"""Private client provisioning contracts, using only explicitly fake keys."""
import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = 'pk-lf-FAKE-CLIENT-PUBLIC-KEY'
SECRET = 'sk-lf-FAKE-CLIENT-SECRET-KEY'


class ClientSealingTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('seal_client', ROOT / 'langfuse/seal-hermes-client.py')
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'verification')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'langfuse').mkdir()
        (self.root / 'hermes/profiles/house-manager').mkdir(parents=True)
        self.target = self.root / 'hermes/profiles/house-manager/langfuse-sealed-secret.yaml'
        self.output = io.StringIO()
        self.captured = []

    def invoke(self, keys=None, tty=True, malformed=False, verify_error=None):
        m = self.module

        def seal(command, **kwargs):
            manifest = json.loads(kwargs['input'])
            self.captured.append(manifest)
            self.assertNotIn(PUBLIC, ' '.join(command))
            self.assertNotIn(SECRET, ' '.join(command))
            self.assertIn('strict', command)
            self.assertEqual(manifest['metadata']['namespace'], 'hermes')
            sealed = {'apiVersion': 'bitnami.com/v1alpha1', 'kind': 'SealedSecret',
                      'metadata': manifest['metadata'], 'spec': {
                          'encryptedData': {k: base64.b64encode(b'FAKE-CIPHERTEXT-ONLY-' * 4).decode()
                                            for k in manifest['stringData']},
                          'template': {'metadata': dict(manifest['metadata']), 'type': 'Opaque'}}}
            if malformed:
                sealed['spec']['template']['metadata']['namespace'] = 'langfuse'
            return subprocess.CompletedProcess(command, 0, json.dumps(sealed).encode(), b'')

        with patch.object(m, '__file__', str(self.root / 'langfuse/seal-hermes-client.py')), \
             patch.object(m.getpass, 'getpass', side_effect=keys or [PUBLIC, SECRET, SECRET]), \
             patch.object(m.sys.stdin, 'isatty', return_value=tty), \
             patch.object(m.sys.stderr, 'isatty', return_value=tty), \
             patch.object(m, 'verify_project', side_effect=verify_error) as verify, \
             patch.object(m.bootstrap.subprocess, 'run', side_effect=seal), \
             contextlib.redirect_stdout(self.output):
            m.main([])
            return verify

    def test_private_strict_client_file_and_no_plaintext(self):
        verify = self.invoke()
        verify.assert_called_once_with(PUBLIC, SECRET)
        self.assertEqual(self.captured[0]['metadata']['name'], 'hermes-langfuse')
        self.assertEqual(self.captured[0]['stringData'], {'public-key': PUBLIC, 'secret-key': SECRET})
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        document = json.loads(self.target.read_text())
        self.assertEqual(document['spec']['template']['metadata']['namespace'], 'hermes')
        self.assertEqual(set(document['spec']['encryptedData']), {'public-key', 'secret-key'})
        self.assertNotIn(PUBLIC, self.target.read_text() + self.output.getvalue())
        self.assertNotIn(SECRET, self.target.read_text() + self.output.getvalue())
        self.assertEqual([p.name for p in self.target.parent.iterdir()], [self.target.name])

    def test_noninteractive_refused_before_any_sealing(self):
        with self.assertRaises(SystemExit):
            self.invoke(tty=False)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.captured, [])

    def test_existing_file_not_overwritten(self):
        self.target.write_text('existing ciphertext fixture')
        with self.assertRaises(SystemExit):
            self.invoke()
        self.assertEqual(self.target.read_text(), 'existing ciphertext fixture')
        self.assertEqual(self.captured, [])

    def test_invalid_keys_and_confirmation_do_not_seal(self):
        for keys in [['invalid', SECRET, SECRET], [PUBLIC, 'wrong-prefix', 'wrong-prefix'],
                     [PUBLIC, SECRET, 'sk-lf-DIFFERENT-FAKE-SECRET'],
                     [PUBLIC + ' ', SECRET, SECRET], [PUBLIC, SECRET + '\n', SECRET + '\n']]:
            with self.subTest(keys=keys), self.assertRaises(SystemExit):
                self.invoke(keys=keys)
            self.assertEqual(self.captured, [])
            self.assertFalse(self.target.exists())

    def test_wrong_project_stops_before_sealing(self):
        with self.assertRaises(SystemExit):
            self.invoke(verify_error=self.module.ClientError('project'))
        self.assertFalse(self.target.exists())
        self.assertEqual(self.captured, [])

    def test_network_failure_never_echoes_exception_or_input(self):
        with self.assertRaises(SystemExit) as caught:
            self.invoke(verify_error=self.module.urllib.error.URLError(SECRET))
        self.assertNotIn(SECRET, str(caught.exception) + self.output.getvalue())
        self.assertFalse(self.target.exists())

    def test_wrong_sealed_namespace_not_published(self):
        with self.assertRaises(SystemExit):
            self.invoke(malformed=True)
        self.assertFalse(self.target.exists())

    def test_symlink_directory_refused(self):
        other = self.root / 'other'
        other.mkdir()
        self.target.parent.rmdir()
        self.target.parent.symlink_to(other, target_is_directory=True)
        with self.assertRaises(SystemExit):
            self.invoke()
        self.assertEqual(list(other.iterdir()), [])
        self.assertEqual(self.captured, [])

    def test_project_check_fixed_https_get_and_correct_scope(self):
        m = self.module
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({'data': [{'id': 'fake-project-id', 'name': 'hermes-cluster'}]}).encode()
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(m.urllib.request, 'build_opener', return_value=opener):
            m.verify_project(PUBLIC, SECRET)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://langfuse.tailbd291c.ts.net/api/public/projects')
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 15)
        self.assertEqual(request.get_header('Authorization'), 'Basic ' + base64.b64encode(f'{PUBLIC}:{SECRET}'.encode()).decode())
        response.read.return_value = json.dumps({'data': [{'name': 'hermes-desktop'}]}).encode()
        with patch.object(m.urllib.request, 'build_opener', return_value=opener), self.assertRaises(m.ClientError):
            m.verify_project(PUBLIC, SECRET)

    def test_redirect_handler_does_not_forward_credentials(self):
        self.assertIsNone(self.module.NoRedirect().redirect_request(None, None, 302, 'fixture', {}, 'https://example.invalid'))

    def test_credential_arguments_are_rejected_without_echo(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as caught:
            self.module.main([SECRET])
        self.assertNotIn(SECRET, output.getvalue() + str(caught.exception))


if __name__ == '__main__':
    unittest.main()
