"""Linux encrypted capture primitive; no production adapter or NAS receiver.

capture() accepts an already opened owner-only directory FD and reviewed fixed
argv (never shell commands/credential literals). Producer stdout is confidential;
only pipes/RAM carry plaintext. The caller supplies an independently trusted full
native-export byte count/hash, plus an age decrypt argv using privately supplied
identity FDs via decrypt_pass_fds (never identity literals in argv). Decryption must match
that entire stream before publication. Native full-parse/restore acceptance and
writer exclusion remain caller obligations, not something a hash establishes.

An optional binary sink consumes ciphertext only; rc0 is NOT remote durability
or remote no-overwrite proof. Local COMPLETE means encryption, byte equality,
all subprocess exits, optional sink exit, and durable local publication passed.
INCOMPLETE receipts and exclusive .partial ciphertext are retained on failure.
No cleanup unlinks any artifacts. A final .complete.json is the acceptance marker;
a ciphertext alone, including one left by a crash during publication, is incomplete.

Directory FDs pin destinations; linkat(AT_EMPTY_PATH) pins the source inode and
never replaces an existing destination (including symlinks/hardlinks). Only local
Linux regular-file filesystems supporting this and fsync are supported. Processes
are deadline/cancellation/byte bounded, including descendants in their groups.
Local kernel filesystem IO/fsync is synchronous and cannot be preempted by this
Python deadline; use a supervising process for a hard wall-clock IO ceiling.
"""
import ctypes
import errno
import hashlib
import json
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import time
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureResult:
    complete: bool
    receipt: str
    partial: str
    reason: str


class Rejected(Exception):
    pass


def _private(fd):
    s = os.fstat(fd)
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
        raise ValueError('directory must be owner-only')


def _new(fd, name):
    return os.open(name, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_RDWR,
                   0o600, dir_fd=fd)


def _record(fd, name, value):
    out = _new(fd, name)
    try:
        data = (json.dumps(value, sort_keys=True) + '\n').encode()
        while data:
            written = os.write(out, data)
            if written <= 0:
                raise OSError('receipt write made no progress')
            data = data[written:]
        os.fsync(out)
    finally:
        os.close(out)
    os.fsync(fd)


def _publish(source, directory, name):
    s = os.fstat(source)
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_uid != os.getuid():
        raise Rejected('unsafe-source')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.linkat(source, ctypes.c_char_p(b''), directory,
                   ctypes.c_char_p(name.encode()), 0x1000) != 0:
        raise OSError(ctypes.get_errno(), 'exclusive publication failed')
    os.fsync(directory)


def capture(*, directory_fd, name, producer_argv, age_argv, decrypt_argv,
            expected_bytes, expected_sha256, max_ciphertext_bytes,
            timeout_seconds=60, cancelled=lambda: False, producer_stdin_fd=None,
            producer_pass_fds=(), age_pass_fds=(), decrypt_pass_fds=(),
            sink_pass_fds=(), sink_argv=None):
    """Return CaptureResult; preflight errors raise, runtime failures return incomplete.

    argv lists are trusted executable policy, not untrusted strings: the primitive
    cannot sandbox a malicious producer or recognize credentials in arbitrary
    arguments. age_argv must encrypt to the approved recipient; decrypt_argv must
    use the independently approved matching custody identity. Both are mandatory.
    All children get an empty environment, / working dir, no stderr logs, closed
    unrelated descriptors. Descriptor allowlists are per process: private identity
    FDs belong only in decrypt_pass_fds, never a shared child allowlist. No shell is used.
    Cancellation is polled; KeyboardInterrupt also aborts without publication.
    """
    _private(directory_fd)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', name):
        raise ValueError('unsafe name')
    if (type(expected_bytes) is not int or expected_bytes <= 0
            or not re.fullmatch('[0-9a-f]{64}', expected_sha256)
            or type(max_ciphertext_bytes) is not int or max_ciphertext_bytes <= 0
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise ValueError('invalid bounds')
    for argv in (producer_argv, age_argv, decrypt_argv, sink_argv):
        if argv is not None and (not isinstance(argv, (list, tuple)) or not argv
                                or not all(isinstance(x, str) and x for x in argv)
                                or not os.path.isabs(argv[0])):
            raise ValueError('fixed absolute executable argv required')
    descriptor_policy = {'producer': tuple(producer_pass_fds), 'age': tuple(age_pass_fds),
                         'decrypt': tuple(decrypt_pass_fds), 'sink': tuple(sink_pass_fds)}
    for descriptors in descriptor_policy.values():
        if any(type(fd) is not int or fd < 3 for fd in descriptors) or len(set(descriptors)) != len(descriptors):
            raise ValueError('invalid per-process descriptor policy')
    # Refuse occupied paths before starting producers; linkat checks again later.
    for target in (name, name + '.complete.json'):
        try:
            os.stat(target, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(errno.EEXIST, 'publication target occupied')
    token = name + '.' + uuid.uuid4().hex
    partial = token + '.partial'
    incomplete = token + '.incomplete.json'
    _record(directory_fd, incomplete, {'status': 'INCOMPLETE', 'partial': partial,
                                      'publication': name})
    output = _new(directory_fd, partial)
    children = []
    readers = []
    exits = {}
    deadline = time.monotonic() + timeout_seconds
    reason = 'failed'
    cipher_hash = hashlib.sha256()
    cipher_count = 0

    def check():
        if cancelled():
            raise Rejected('cancelled')
        if time.monotonic() >= deadline:
            raise Rejected('deadline')

    def spawn(argv, label, **kwargs):
        check()
        p = subprocess.Popen(argv, stderr=subprocess.DEVNULL, env={}, cwd='/',
                             close_fds=True, pass_fds=descriptor_policy[label],
                             start_new_session=True, **kwargs)
        children.append(p)
        return p

    def reader():
        # Reopen the pinned inode read-only, never resolve the partial pathname.
        fd = os.open('/proc/self/fd/' + str(output), os.O_RDONLY | os.O_CLOEXEC)
        readers.append(fd)
        return fd

    def finish(p, label):
        while p.poll() is None:
            check()
            time.sleep(0.005)
        exits[label] = p.returncode
        if p.returncode:
            raise Rejected(label + '-exit')

    try:
        age = spawn(age_argv, 'age', stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        producer = spawn(producer_argv, 'producer', stdin=(producer_stdin_fd if producer_stdin_fd
                         is not None else subprocess.DEVNULL), stdout=subprocess.PIPE)
        assert producer.stdout is not None and age.stdin is not None and age.stdout is not None
        for stream in (producer.stdout, age.stdin, age.stdout):
            os.set_blocking(stream.fileno(), False)
        pending = bytearray()
        source_count = 0
        source_hash = hashlib.sha256()
        source_eof = encrypted_eof = False
        with selectors.DefaultSelector() as sel:
            while not (source_eof and encrypted_eof and not pending):
                check()
                if source_eof and not pending and not age.stdin.closed:
                    age.stdin.close()
                for key in list(sel.get_map().values()):
                    sel.unregister(key.fileobj)
                if not source_eof and len(pending) < 65536:
                    sel.register(producer.stdout, selectors.EVENT_READ, 'source')
                if pending:
                    sel.register(age.stdin, selectors.EVENT_WRITE, 'input')
                if not encrypted_eof:
                    sel.register(age.stdout, selectors.EVENT_READ, 'cipher')
                for key, _ in sel.select(0.025):
                    if key.data == 'input':
                        n = os.write(age.stdin.fileno(), pending)
                        if n <= 0:
                            raise Rejected('encrypt-input-no-progress')
                        del pending[:n]
                    else:
                        chunk = os.read(key.fd, 65536)
                        if key.data == 'source':
                            if not chunk:
                                source_eof = True
                            else:
                                source_count += len(chunk)
                                if source_count > expected_bytes:
                                    raise Rejected('plaintext-limit')
                                source_hash.update(chunk)
                                pending.extend(chunk)
                        elif not chunk:
                            encrypted_eof = True
                        else:
                            cipher_count += len(chunk)
                            if cipher_count > max_ciphertext_bytes:
                                raise Rejected('ciphertext-limit')
                            cipher_hash.update(chunk)
                            view = memoryview(chunk)
                            while view:
                                check()
                                written = os.write(output, view)
                                if written <= 0:
                                    raise Rejected('ciphertext-write-no-progress')
                                view = view[written:]
        finish(producer, 'producer')
        finish(age, 'age')
        if source_count != expected_bytes or source_hash.hexdigest() != expected_sha256:
            raise Rejected('source-mismatch')
        os.fsync(output)
        decrypt_input = reader()
        decrypt = spawn(decrypt_argv, 'decrypt', stdin=decrypt_input, stdout=subprocess.PIPE)
        assert decrypt.stdout is not None
        os.set_blocking(decrypt.stdout.fileno(), False)
        restored_hash = hashlib.sha256()
        restored_count = 0
        with selectors.DefaultSelector() as sel:
            sel.register(decrypt.stdout, selectors.EVENT_READ)
            eof = False
            while not eof:
                check()
                for key, _ in sel.select(0.025):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        eof = True
                    else:
                        restored_count += len(chunk)
                        if restored_count > expected_bytes:
                            raise Rejected('decrypted-limit')
                        restored_hash.update(chunk)
        finish(decrypt, 'decrypt')
        if os.lseek(decrypt_input, 0, os.SEEK_CUR) != cipher_count:
            raise Rejected('decrypt-short-read')
        if restored_count != expected_bytes or restored_hash.hexdigest() != expected_sha256:
            raise Rejected('decrypted-mismatch')
        if sink_argv is not None:
            sink_input = reader()
            sink = spawn(sink_argv, 'sink', stdin=sink_input, stdout=subprocess.DEVNULL)
            finish(sink, 'sink')
            if os.lseek(sink_input, 0, os.SEEK_CUR) != cipher_count:
                raise Rejected('sink-short-read')
        check()
        _private(directory_fd)
        _publish(output, directory_fd, name)
        receipt = name + '.complete.json'
        _record(directory_fd, receipt, {'status': 'COMPLETE', 'scope': 'local-publication',
                'ciphertext_bytes': cipher_count, 'ciphertext_sha256': cipher_hash.hexdigest(),
                'plaintext_bytes': expected_bytes, 'plaintext_sha256': expected_sha256,
                'exits': exits, 'remote_durability_verified': False,
                'incomplete_receipt': incomplete})
        return CaptureResult(True, receipt, partial, 'complete')
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, Rejected) else 'io-or-process-failure'
        failure = token + '.failure.json'
        _record(directory_fd, failure, {'status': 'INCOMPLETE', 'reason': reason,
                                       'exits': exits, 'partial': partial})
        return CaptureResult(False, failure, partial, reason)
    finally:
        for p in children:
            # Kill the group even if the leader exited but left descendants.
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for p in children:
            p.wait()
            for stream in (p.stdin, p.stdout):
                if stream is not None:
                    stream.close()
        for fd in readers:
            os.close(fd)
        os.close(output)
