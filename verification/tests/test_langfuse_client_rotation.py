"""Offline rotation tests: fake tree, keys, HTTPS responses and kubeseal only."""
import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = 'pk-lf-' + 'FAKE_PUBLIC_123456'
SECRET = 'sk-lf-' + 'FAKE_SECRET_123456'


def ciphertext(marker):
    metadata = {'name': 'hermes-langfuse', 'namespace': 'hermes'}
    return json.dumps({'apiVersion': 'bitnami.com/v1alpha1', 'kind': 'SealedSecret',
                      'metadata': metadata, 'spec': {
                          'encryptedData': {key: base64.b64encode(marker * 64).decode()
                                            for key in ('public-key', 'secret-key')},
                          'template': {'metadata': dict(metadata), 'type': 'Opaque'}}}).encode()


class RotationTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('rotate_client', ROOT / 'langfuse/rotate-hermes-client.py')
        assert spec is not None and spec.loader is not None
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('langfuse', 'hermes', 'verification/cache'):
            (self.root / name).mkdir(parents=True)
        self.target = self.root / 'hermes/langfuse-sealed-secret.yaml'
        self.original = ciphertext(b'OLD-FAKE-CIPHERTEXT')
        self.target.write_bytes(self.original)
        self.output = io.StringIO()
        self.calls = []

    def invoke(self, keys=None, project='hermes-cluster', seal_error=False,
               mutation=None, race=None, tty=True, network_error=None):
        m = self.m
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({'data': [{'name': project}]}).encode()
        opener = MagicMock()
        opener.open.return_value = response
        if network_error:
            opener.open.side_effect = network_error

        def seal(command, **kwargs):
            self.calls.append(command)
            manifest = json.loads(kwargs['input'])
            self.assertEqual(manifest['stringData'], {'public-key': PUBLIC, 'secret-key': SECRET})
            self.assertEqual(manifest['metadata']['namespace'], 'hermes')
            self.assertEqual(manifest['metadata']['name'], 'hermes-langfuse')
            self.assertIn('strict', command)
            self.assertNotIn(SECRET, ' '.join(command))
            if race:
                race()
            if seal_error:
                return subprocess.CompletedProcess(command, 1, SECRET.encode(), SECRET.encode())
            document = json.loads(ciphertext(b'NEW-FAKE-CIPHERTEXT'))
            if mutation:
                mutation(document)
            return subprocess.CompletedProcess(command, 0, json.dumps(document).encode(), b'')

        with contextlib.redirect_stdout(self.output), contextlib.redirect_stderr(self.output), \
             patch.object(m, '__file__', str(self.root / 'langfuse/rotate-hermes-client.py')), \
             patch.object(m.client.getpass, 'getpass', side_effect=keys or [PUBLIC, SECRET, SECRET]), \
             patch.object(m.sys.stdin, 'isatty', return_value=tty), \
             patch.object(m.sys.stderr, 'isatty', return_value=tty), \
             patch.object(m.client.urllib.request, 'build_opener', return_value=opener) as build, \
             patch.object(m.bootstrap.subprocess, 'run', side_effect=seal):
            m.main([])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://langfuse.tailbd291c.ts.net/api/public/projects')
        self.assertEqual(request.get_method(), 'GET')
        self.assertTrue(any(isinstance(h, m.client.NoRedirect) for h in build.call_args.args))
        self.assertIsNone(m.client.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid'))

    def test_success_replaces_only_target_and_keeps_private_ciphertext_backup(self):
        self.invoke()
        self.assertNotEqual(self.target.read_bytes(), self.original)
        backups = list((self.root / 'verification/cache').glob('rotation-*/previous-ciphertext.yaml'))
        self.assertEqual(len(backups), 1)
        backup = backups[0]
        self.assertEqual(backup.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(backup.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])
        self.assertIn(str(backup), self.output.getvalue())
        self.assertIn('no plaintext files created or resources applied', self.output.getvalue())
        for path in self.root.rglob('*'):
            if path.is_file():
                self.assertNotIn(SECRET.encode(), path.read_bytes())
                self.assertNotIn(PUBLIC.encode(), path.read_bytes())
        self.assertNotIn(SECRET, self.output.getvalue())

    def test_invalid_keys_confirmation_project_network_and_seal_preserve_original(self):
        cases = [dict(keys=['bad', SECRET, SECRET]), dict(keys=[PUBLIC, SECRET, 'mismatch']),
                 dict(project='hermes-desktop'), dict(seal_error=True), dict(tty=False),
                 dict(network_error=RuntimeError(SECRET))]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(SystemExit) as caught:
                self.invoke(**kwargs)
            self.assertEqual(self.target.read_bytes(), self.original)
            self.assertNotIn(SECRET, str(caught.exception) + self.output.getvalue())

    def test_malformed_ciphertext_identity_keyset_scope_and_plaintext_rejected(self):
        mutations = [lambda d: d['metadata'].update(namespace='langfuse'),
                     lambda d: d['spec']['template']['metadata'].update(name='other'),
                     lambda d: d['spec']['encryptedData'].update(extra='bad'),
                     lambda d: d.update(stringData={'secret-key': SECRET}),
                     lambda d: d['metadata'].update(annotations={'sealedsecrets.bitnami.com/cluster-wide': 'true'})]
        for mutate in mutations:
            with self.subTest(mutate=mutate), self.assertRaises(SystemExit):
                self.invoke(mutation=mutate)
            self.assertEqual(self.target.read_bytes(), self.original)

    def test_concurrent_content_change_or_replacement_preserved(self):
        changed = ciphertext(b'CONCURRENT-FAKE-CIPHERTEXT')
        def replace():
            other = self.target.with_suffix('.other')
            other.write_bytes(changed)
            os.replace(other, self.target)
        for race in (lambda: self.target.write_bytes(changed), replace):
            self.target.write_bytes(self.original)
            with self.subTest(race=race), self.assertRaises(SystemExit):
                self.invoke(race=race)
            self.assertEqual(self.target.read_bytes(), changed)

    def test_symlink_and_nonregular_target_rejected_before_prompt(self):
        self.target.unlink()
        self.target.symlink_to(self.root / 'absent')
        with self.assertRaises(SystemExit):
            self.invoke()
        self.assertTrue(self.target.is_symlink())
        self.target.unlink()
        os.mkfifo(self.target)
        with self.assertRaises(SystemExit):
            self.invoke()
        self.assertTrue(stat.S_ISFIFO(self.target.lstat().st_mode))
        self.assertEqual(self.calls, [])

    def test_argv_sensitive_values_suppressed_even_with_help(self):
        for args in ([SECRET], ['--secret', SECRET], ['--help', SECRET]):
            with contextlib.redirect_stdout(self.output), contextlib.redirect_stderr(self.output), \
                 self.assertRaises(SystemExit) as caught:
                self.m.main(args)
            self.assertNotIn(SECRET, str(caught.exception) + self.output.getvalue())
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_change_during_backup_is_detected_by_final_guard(self):
        real_write = self.m.write_backup
        changed = ciphertext(b'CHANGED-DURING-BACKUP')
        def racing_write(directory, data):
            real_write(directory, data)
            self.target.write_bytes(changed)
        with patch.object(self.m, 'write_backup', side_effect=racing_write):
            with self.assertRaises(SystemExit):
                self.invoke()
        self.assertEqual(self.target.read_bytes(), changed)
        backups = list((self.root / 'verification/cache').glob('rotation-*/previous-ciphertext.yaml'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)

    def test_backup_failure_preserves_original(self):
        with patch.object(self.m, 'write_backup', side_effect=OSError(SECRET)):
            with self.assertRaises(SystemExit) as caught:
                self.invoke()
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertNotIn(SECRET, str(caught.exception))

    def test_cache_symlink_rejected_before_credentials(self):
        cache = self.root / 'verification/cache'
        cache.rmdir()
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        cache.symlink_to(elsewhere, target_is_directory=True)
        with patch.object(self.m.client.getpass, 'getpass') as prompt:
            with self.assertRaises(SystemExit):
                self.invoke()
        prompt.assert_not_called()
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_publication_validator_rejects_bad_staging_even_if_provision_is_mocked(self):
        bad = json.loads(ciphertext(b'BAD-STAGING'))
        bad['spec']['template']['metadata']['namespace'] = 'wrong'
        def unsafe_provision(directory):
            fd = os.open(self.target.name, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                         0o600, dir_fd=directory)
            with os.fdopen(fd, 'w') as stream:
                json.dump(bad, stream)
        with patch.object(self.m.client, 'provision', side_effect=unsafe_provision):
            with self.assertRaises(SystemExit):
                self.invoke()
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_replace_failure_preserves_original(self):
        with patch.object(self.m.os, 'replace', side_effect=OSError(SECRET)):
            with self.assertRaises(SystemExit) as caught:
                self.invoke()
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertNotIn(SECRET, str(caught.exception))


if __name__ == '__main__':
    unittest.main()
