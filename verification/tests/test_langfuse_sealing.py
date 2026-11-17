"""Exercise the real helper with exclusively fake credentials and kubeseal."""
import contextlib
import base64
import importlib.util
import io
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
NAMES = ('langfuse-app-credentials', 'langfuse-bootstrap', 'langfuse-postgresql-auth',
         'langfuse-redis-auth', 'langfuse-clickhouse-auth', 'langfuse-s3-auth')
PASSWORD = 'fake-test-password-at-least-20-characters'


class SealingTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('seal_bootstrap', ROOT / 'langfuse/seal-bootstrap.py')
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'verification')
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.captured = []
        self.output = io.StringIO()

    def invoke(self, email='fake@example.invalid', password=PASSWORD, repeat=PASSWORD,
               fail_at=None, malformed=None, tty=True, race=False):
        module = self.module
        counter = itertools.count(1)

        def run(command, **kwargs):
            manifest = json.loads(kwargs['input'])
            self.captured.append(manifest)
            self.assertEqual(command, ['kubeseal', '--controller-name', 'sealed-secrets-controller',
                                      '--controller-namespace', 'kube-system', '--scope', 'strict',
                                      '--format', 'json'])
            self.assertNotIn(PASSWORD, ' '.join(command))
            self.assertNotIn('shell', kwargs)
            self.assertEqual(kwargs['timeout'], 60)
            if fail_at == len(self.captured):
                return subprocess.CompletedProcess(command, 1, b'partial fixture', PASSWORD.encode())
            if race and len(self.captured) == 6:
                (self.directory / (NAMES[1] + '-sealed-secret.yaml')).write_text('racing fixture')
            sealed = {'apiVersion': 'bitnami.com/v1alpha1', 'kind': 'SealedSecret',
                      'metadata': manifest['metadata'], 'spec': {
                          'encryptedData': {k: base64.b64encode(b'FAKE-CIPHERTEXT-ONLY-' * 4).decode()
                                            for k in manifest['stringData']},
                          'template': {'metadata': manifest['metadata'], 'type': 'Opaque'}}}
            if malformed:
                malformed(sealed)
            return subprocess.CompletedProcess(command, 0, json.dumps(sealed).encode(), b'')

        with patch.object(module, '__file__', str(self.directory / 'seal-bootstrap.py')), \
             patch('builtins.input', return_value=email), \
             patch.object(module.getpass, 'getpass', side_effect=[password, repeat]), \
             patch.object(module.sys.stdin, 'isatty', return_value=tty), \
             patch.object(module.sys.stderr, 'isatty', return_value=tty), \
             patch.object(module.secrets, 'token_hex', side_effect=lambda n: f'{next(counter):0{2*n}x}'), \
             patch.object(module.subprocess, 'run', side_effect=run), \
             contextlib.redirect_stdout(self.output):
            module.main([])

    def test_six_identities_relationships_and_private_files(self):
        before = os.umask(0o022)
        try:
            self.invoke()
            observed = os.umask(0o022)
            self.assertEqual(observed, 0o022)
        finally:
            os.umask(before)
        self.assertEqual({m['metadata']['name'] for m in self.captured}, set(NAMES))
        self.assertEqual(len(list(self.directory.iterdir())), 6)
        by_name = {m['metadata']['name']: m['stringData'] for m in self.captured}
        for manifest in self.captured:
            self.assertEqual(manifest['metadata']['namespace'], 'langfuse')
            for value in manifest['stringData'].values():
                self.assertNotIn(value, self.output.getvalue())
        self.assertRegex(by_name[NAMES[0]]['encryption-key'], r'^[0-9a-f]{64}$')
        pg = by_name[NAMES[2]]
        self.assertNotEqual(pg['POSTGRES_PASSWORD'], pg['USERDB_PASSWORD'])
        s3 = by_name[NAMES[5]]
        iam = json.loads(s3['seaweedfs_s3_config'])['identities'][0]
        self.assertEqual(iam['credentials'], [{'accessKey': s3['accessKey'], 'secretKey': s3['secretKey']}])
        for path in self.directory.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())['kind'], 'SealedSecret')

    def test_invalid_inputs_do_not_seal_or_write(self):
        for kwargs in ({'password': 'short'}, {'repeat': 'mismatch'},
                       {'email': 'invalid'}, {'email': 'a@b\n.invalid'},
                       {'password': ' ' * 24, 'repeat': ' ' * 24}, {'tty': False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(SystemExit):
                self.invoke(**kwargs)
            self.assertEqual(self.captured, [])
            self.assertEqual(list(self.directory.iterdir()), [])

    def test_owner_validation_reports_safe_actionable_reasons(self):
        cases = [
            ({'email': 'invalid-fixture'}, 'owner email is not a valid address'),
            ({'password': 'FAKE_SHORT_INPUT', 'repeat': 'FAKE_SHORT_INPUT'},
             'owner password must contain at least 20 characters'),
            ({'repeat': 'FAKE_DIFFERENT_PASSWORD_LONGER_THAN_TWENTY'},
             'owner passwords do not match'),
            ({'password': ' ' * 24, 'repeat': ' ' * 24},
             'owner password must be nonblank and contain no control characters'),
        ]
        for kwargs, reason in cases:
            with self.subTest(reason=reason), self.assertRaises(SystemExit) as caught:
                self.invoke(email=kwargs.get('email', 'fake@example.invalid'),
                            password=kwargs.get('password', PASSWORD),
                            repeat=kwargs.get('repeat', PASSWORD))
            message = str(caught.exception) + self.output.getvalue()
            self.assertIn(reason, message)
            for value in [PASSWORD, *kwargs.values()]:
                self.assertNotIn(value, message)
            self.assertEqual(self.captured, [])
            self.assertEqual(list(self.directory.iterdir()), [])

    def test_sealing_failure_identifies_stage_without_echoing_stderr(self):
        with self.assertRaises(SystemExit) as caught:
            self.invoke(fail_at=1)
        self.assertIn('kubeseal exited unsuccessfully', str(caught.exception))
        self.assertNotIn(PASSWORD, str(caught.exception))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_late_kubeseal_failure_leaves_nothing(self):
        with self.assertRaises(SystemExit) as caught:
            self.invoke(fail_at=6)
        self.assertEqual(len(self.captured), 6)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertNotIn(PASSWORD, str(caught.exception) + self.output.getvalue())

    def test_existing_file_and_dangling_symlink_are_never_replaced(self):
        path = self.directory / (NAMES[1] + '-sealed-secret.yaml')
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    path.symlink_to(self.directory / 'absent')
                else:
                    path.write_text('existing fixture')
                with self.assertRaises(SystemExit):
                    self.invoke()
                self.assertEqual(self.captured, [])
                self.assertEqual(len(list(self.directory.iterdir())), 1)
                self.assertTrue(path.is_symlink() if symlink else path.read_text() == 'existing fixture')
                path.unlink()

    def test_racing_destination_is_preserved_without_partial_set(self):
        with self.assertRaises(SystemExit):
            self.invoke(race=True)
        paths = list(self.directory.iterdir())
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].read_text(), 'racing fixture')

    def test_invalid_sealed_output_is_rejected(self):
        mutations = [lambda s: s.update(kind='Secret'),
                     lambda s: s['metadata'].update(namespace='wrong'),
                     lambda s: s['spec']['encryptedData'].clear(),
                     lambda s: s['spec']['template'].update(data={'plaintext': PASSWORD}),
                     lambda s: s.update(stringData={'password': PASSWORD}),
                     lambda s: s['spec']['encryptedData'].update(salt=PASSWORD),
                     lambda s: s['metadata']['annotations'].update(
                         {'sealedsecrets.bitnami.com/cluster-wide': 'true'})]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(SystemExit):
                self.invoke(malformed=mutation)
            self.assertEqual(list(self.directory.iterdir()), [])

    def test_symlink_output_directory_is_rejected(self):
        real = self.directory
        alias = real / 'alias'
        alias.symlink_to(real, target_is_directory=True)
        self.directory = alias
        with self.assertRaises(SystemExit):
            self.invoke()
        self.assertEqual(self.captured, [])

    def test_partial_publication_error_rolls_back_only_new_files(self):
        real_link = os.link
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('fake publication error')
            return real_link(*args, **kwargs)

        with patch.object(self.module.os, 'link', side_effect=fail_second):
            with self.assertRaises(SystemExit):
                self.invoke()
        self.assertEqual(calls, 2)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_missing_kubeseal_and_timeout_are_sanitized(self):
        for error in (FileNotFoundError(PASSWORD),
                      subprocess.TimeoutExpired('kubeseal', 60, output=PASSWORD.encode())):
            with self.subTest(error=type(error).__name__):
                with patch.object(self.module, 'seal', side_effect=error):
                    with self.assertRaises(SystemExit) as caught:
                        self.invoke()
                self.assertNotIn(PASSWORD, str(caught.exception))
                self.assertEqual(list(self.directory.iterdir()), [])

    def test_help_is_noninteractive(self):
        result = subprocess.run([str(ROOT / 'verification/venv/bin/python'), '-B',
                                 str(ROOT / 'langfuse/seal-bootstrap.py'), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('interactive', result.stdout)
