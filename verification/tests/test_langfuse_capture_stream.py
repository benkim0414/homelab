"""Generated-only native age integration. No production keys/data/network/NAS.

Run: python3 -B -m unittest discover -s verification/tests
     -p test_langfuse_capture_stream.py -v
All run directories/receipts are preserved in the ignored encryption cache.
Native cases explicitly skip without Linux AMD64, bubblewrap and memfd support;
they never fall back to running generated identities outside their sandbox.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import threading
import time
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


capture = load('langfuse_capture_stream', ROOT / 'langfuse/recovery/capture_stream.py')
fixture = load('langfuse_encryption_fixture', ROOT / 'langfuse/recovery/fixture-encryption.py')


@unittest.skipUnless(sys.platform == 'linux' and os.uname().machine == 'x86_64'
                     and Path('/usr/bin/bwrap').is_file() and hasattr(os, 'memfd_create'),
                     'native age integration requires Linux AMD64, /usr/bin/bwrap and memfd')
class NativeCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binaries = fixture.tools()  # Verifies exact official archive and executable bytes.
        cls.state = fixture.CACHE / ('capture-tests-' + uuid.uuid4().hex)
        cls.state.mkdir(mode=0o700)
        for key in ['generated', 'wrong']:
            fixture.require_success(fixture.native(cls.binaries, cls.state,
                'age-keygen', ['-o', key + '.identity']))
        cls.recipient = fixture.native(cls.binaries, cls.state, 'age-keygen',
                                      ['-y', 'generated.identity']).stdout.decode().strip()
        cls.payload = {'schema.txt': b'GENERATED CAPTURE ONLY\n',
                       'data.bin': bytes(range(256)) * 4097}
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:') as archive:
            for name, data in cls.payload.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        cls.plain = stream.getvalue()
        cls.results = []

    @classmethod
    def tearDownClass(cls):
        fixture.new_file(cls.state / 'suite-receipt.json', json.dumps({
            'scope': 'generated-only local native age streaming tests',
            'production_recipient_selected': False, 'NAS_verified': False,
            'age_archive_sha256': fixture.SHA256,
            'module_sha256': hashlib.sha256((ROOT / 'langfuse/recovery/capture_stream.py').read_bytes()).hexdigest(),
            'cases': cls.results}, indent=2).encode())
        print('\nGenerated capture receipts: ' + str(cls.state / 'suite-receipt.json'))

    def setUp(self):
        self.directory = self.state / self._testMethodName
        self.directory.mkdir(mode=0o700)
        self.fd = os.open(self.directory, os.O_DIRECTORY | os.O_NOFOLLOW)
        self.source = os.memfd_create('generated-archive', os.MFD_CLOEXEC)
        os.write(self.source, self.plain)
        os.lseek(self.source, 0, os.SEEK_SET)

    def tearDown(self):
        os.close(self.source)
        os.close(self.fd)

    def age(self, *args):
        return ['/'+ 'usr/bin/bwrap', '--unshare-all', '--die-with-parent',
                '--new-session', '--cap-drop', 'ALL', '--ro-bind',
                str(self.binaries['age']), '/age', '--ro-bind', str(self.state),
                '/fixture', '--tmpfs', '/tmp', '--proc', '/proc', '--dev', '/dev',
                '--clearenv', '--setenv', 'HOME', '/tmp', '/age', *args]

    def run_capture(self, allow_occupied=False, **overrides):
        kwargs = dict(directory_fd=self.fd, name='archive.age',
                      producer_argv=['/usr/bin/cat'], producer_stdin_fd=self.source,
                      age_argv=self.age('-r', self.recipient),
                      decrypt_argv=self.age('-d', '-i', '/fixture/generated.identity'),
                      expected_bytes=len(self.plain),
                      expected_sha256=hashlib.sha256(self.plain).hexdigest(),
                      max_ciphertext_bytes=len(self.plain) + 65536,
                      timeout_seconds=10)
        kwargs.update(overrides)
        result = capture.capture(**kwargs)
        self.results.append({'case': self._testMethodName, 'complete': result.complete,
                             'reason': result.reason, 'receipt': str(self.directory / result.receipt)})
        record = json.loads((self.directory / result.receipt).read_text())
        self.assertEqual(record['status'], 'COMPLETE' if result.complete else 'INCOMPLETE')
        self.assertTrue((self.directory / result.partial).exists())
        if not result.complete:
            self.assertFalse((self.directory / 'archive.age.complete.json').exists())
            if not allow_occupied:
                self.assertFalse((self.directory / 'archive.age').exists())
        return result

    def test_identity_descriptors_are_only_inherited_by_decrypt(self):
        identity = os.memfd_create('generated-identity-scope', os.MFD_CLOEXEC)
        try:
            os.write(identity, b'GENERATED IDENTITY SCOPE ONLY')
            producer = [sys.executable, '-c',
                        'import os,sys\n'
                        f'try: os.fstat({identity})\n'
                        'except OSError: pass\n'
                        'else: raise RuntimeError("unexpected identity descriptor")\n'
                        'sys.stdout.buffer.write(sys.stdin.buffer.read())']
            actual_popen = subprocess.Popen
            with mock.patch.object(capture.subprocess, 'Popen', wraps=actual_popen) as spawn:
                result = self.run_capture(producer_argv=producer,
                                          decrypt_pass_fds=(identity,), sink_argv=['/usr/bin/cat'])
            self.assertTrue(result.complete, result.reason)
            self.assertEqual([call.kwargs['pass_fds'] for call in spawn.call_args_list],
                             [(), (), (identity,), ()])
        finally:
            os.close(identity)

    def test_zero_progress_receipt_write_is_rejected(self):
        with mock.patch.object(capture.os, 'write', return_value=0):
            with self.assertRaises(OSError):
                capture._record(self.fd, 'zero-progress.json', {'status': 'INCOMPLETE'})
        self.assertFalse((self.directory / 'archive.age.complete.json').exists())

    def test_zero_progress_ciphertext_write_is_incomplete(self):
        original_new, original_write = capture._new, os.write
        partial_fd = []
        def reserve(fd, name):
            result = original_new(fd, name)
            if name.endswith('.partial'):
                partial_fd.append(result)
            return result
        def write(fd, data):
            if partial_fd and fd == partial_fd[0]:
                return 0
            return original_write(fd, data)
        with mock.patch.object(capture, '_new', side_effect=reserve), \
                mock.patch.object(capture.os, 'write', side_effect=write):
            result = self.run_capture()
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, 'ciphertext-write-no-progress')

    def test_directory_permission_drift_prevents_acceptance(self):
        def drift():
            self.directory.chmod(0o750)
            return False
        try:
            result = self.run_capture(cancelled=drift)
            self.assertFalse(result.complete)
        finally:
            self.directory.chmod(0o700)

    def test_roundtrip_full_parse_equality(self):
        r = self.run_capture(sink_argv=['/usr/bin/cat'])
        self.assertTrue(r.complete, r.reason)
        fd = os.open(self.directory / 'archive.age', os.O_RDONLY | os.O_NOFOLLOW)
        try:
            decrypted = subprocess.run(self.age('-d', '-i', '/fixture/generated.identity'),
                stdin=fd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True).stdout
        finally:
            os.close(fd)
        self.assertEqual(decrypted, self.plain)
        self.assertEqual(decrypted[-1024:], bytes(1024))
        with tarfile.open(fileobj=io.BytesIO(decrypted), mode='r:') as archive:
            members = list(archive)
            self.assertEqual([x.name for x in members], list(self.payload))
            contents = {}
            for member in members:
                source = archive.extractfile(member)
                assert source is not None
                contents[member.name] = source.read()
            self.assertEqual(contents, self.payload)
            self.assertFalse(any(decrypted[archive.offset:]))
        record = json.loads((self.directory / r.receipt).read_text())
        encrypted = (self.directory / 'archive.age').read_bytes()
        self.assertEqual(record['ciphertext_bytes'], len(encrypted))
        self.assertEqual(record['ciphertext_sha256'], hashlib.sha256(encrypted).hexdigest())
        self.assertEqual(record['exits'], {'producer': 0, 'age': 0, 'decrypt': 0, 'sink': 0})
        for path in self.directory.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_producer_failure_after_partial(self):
        r = self.run_capture(producer_argv=[sys.executable, '-c',
            'import os; os.write(1, os.read(0, 4096)); raise SystemExit(7)'])
        self.assertFalse(r.complete)
        self.assertEqual(r.reason, 'producer-exit')

    def test_rc0_truncated_producer(self):
        r = self.run_capture(producer_argv=[sys.executable, '-c',
            'import os; os.write(1, os.read(0, 4096))'])
        self.assertEqual(r.reason, 'source-mismatch')

    def test_full_producer_bytes_nonzero_exit(self):
        script = ('import os\nwhile True:\n data=os.read(0,65536)\n'
                  ' if not data: break\n'
                  ' while data: data=data[os.write(1,data):]\n'
                  'raise SystemExit(7)')
        self.assertEqual(self.run_capture(producer_argv=[sys.executable, '-c', script]).reason,
                         'producer-exit')

    def test_full_age_ciphertext_nonzero_exit(self):
        wrapper = [sys.executable, '-c',
                   'import subprocess,sys; subprocess.run(sys.argv[1:],check=True); raise SystemExit(7)']
        self.assertEqual(self.run_capture(age_argv=wrapper + self.age('-r', self.recipient)).reason,
                         'age-exit')

    def test_wrong_recipient_custody(self):
        r = self.run_capture(decrypt_argv=self.age('-d', '-i', '/fixture/wrong.identity'))
        self.assertEqual(r.reason, 'decrypt-exit')

    def test_encryption_consumer_failure(self):
        self.assertFalse(self.run_capture(age_argv=['/usr/bin/false']).complete)

    def test_rc0_truncated_ciphertext(self):
        self.assertFalse(self.run_capture(age_argv=[sys.executable, '-c',
            'import os; data=b""\nwhile os.read(0,65536): pass\nos.write(1,b"not age")']).complete)

    def test_decrypt_consumer_failure(self):
        self.assertEqual(self.run_capture(decrypt_argv=['/usr/bin/false']).reason, 'decrypt-exit')

    def test_transport_failure(self):
        self.assertEqual(self.run_capture(sink_argv=['/usr/bin/false']).reason, 'sink-exit')

    def test_transport_rc0_short_read(self):
        self.assertEqual(self.run_capture(sink_argv=['/usr/bin/true']).reason, 'sink-short-read')

    def test_transport_cannot_write_ciphertext(self):
        self.assertEqual(self.run_capture(sink_argv=[sys.executable, '-c',
            'import os; os.write(0,b"corrupt")']).reason, 'sink-exit')

    def test_transport_deadline(self):
        self.assertEqual(self.run_capture(sink_argv=['/usr/bin/sleep', '30'],
                                         timeout_seconds=0.8).reason, 'deadline')

    def test_plaintext_byte_bound(self):
        r = self.run_capture(expected_bytes=1)
        self.assertEqual(r.reason, 'plaintext-limit')

    def test_ciphertext_byte_bound(self):
        self.assertEqual(self.run_capture(max_ciphertext_bytes=1).reason, 'ciphertext-limit')

    def test_deadline_producer(self):
        start = time.monotonic()
        self.assertEqual(self.run_capture(producer_argv=['/usr/bin/sleep', '30'],
                                         timeout_seconds=0.1).reason, 'deadline')
        self.assertLess(time.monotonic() - start, 3)

    def test_cancellation(self):
        start = time.monotonic()
        r = self.run_capture(producer_argv=['/usr/bin/sleep', '30'],
                             cancelled=lambda: time.monotonic() - start > 0.1)
        self.assertEqual(r.reason, 'cancelled')

    def test_keyboard_interrupt(self):
        def interrupt():
            raise KeyboardInterrupt()
        self.assertFalse(self.run_capture(cancelled=interrupt).complete)

    def test_overwrite_regular_symlink_hardlink(self):
        victim = self.directory / 'existing'
        victim.write_bytes(b'untouched')
        for kind in ['regular', 'symlink', 'hardlink']:
            sub = self.directory / kind
            sub.mkdir(mode=0o700)
            target = sub / 'archive.age'
            if kind == 'regular':
                target.write_bytes(b'existing')
            elif kind == 'symlink':
                target.symlink_to(victim)
            else:
                os.link(victim, target)
            fd = os.open(sub, os.O_DIRECTORY)
            try:
                with self.assertRaises(FileExistsError):
                    self.run_capture(directory_fd=fd)
            finally:
                os.close(fd)
            self.assertFalse((sub / 'archive.age.complete.json').exists())
        self.assertEqual(victim.read_bytes(), b'untouched')

    def test_fd_pinned_source_and_no_overwrite(self):
        source = capture._new(self.fd, 'source')
        try:
            os.write(source, b'cipher-fixture')
            os.rename(self.directory / 'source', self.directory / 'renamed')
            (self.directory / 'source').symlink_to('/not-an-artifact')
            capture._publish(source, self.fd, 'published')
            self.assertEqual((self.directory / 'published').read_bytes(), b'cipher-fixture')
            with self.assertRaises(capture.Rejected):
                capture._publish(source, self.fd, 'again')  # nlink no longer 1
        finally:
            os.close(source)

    def test_publication_race(self):
        script = ('import os\nwhile os.read(0,65536): pass\n'
                  'os.open(%r,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)') % str(self.directory / 'archive.age')
        # Existing artifact must be preserved; this failure intentionally has a final
        # ciphertext name but NEVER a complete marker.
        result = self.run_capture(allow_occupied=True, sink_argv=[sys.executable, '-c', script])
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, 'io-or-process-failure')
        self.assertEqual((self.directory / 'archive.age').read_bytes(), b'')
        self.assertFalse((self.directory / 'archive.age.complete.json').exists())

    def test_insecure_directory_rejected(self):
        self.directory.chmod(0o755)
        with self.assertRaises(ValueError):
            self.run_capture()

    def test_directory_fd_pinned_across_rename(self):
        original = self.directory
        self.directory = self.directory.with_name(self.directory.name + '-moved')
        original.rename(self.directory)
        original.symlink_to('/not-a-destination')
        self.assertTrue(self.run_capture().complete)

    def test_wrong_expected_hash(self):
        self.assertEqual(self.run_capture(expected_sha256='0' * 64).reason, 'source-mismatch')

    def test_grandchild_keeps_pipe_open_deadline(self):
        script = 'import os,time\npid=os.fork()\nif pid==0: time.sleep(30)\nelse: os._exit(0)'
        self.assertEqual(self.run_capture(producer_argv=[sys.executable, '-c', script],
                                         timeout_seconds=0.1).reason, 'deadline')
