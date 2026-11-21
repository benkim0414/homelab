import base64
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name, source):
    spec = importlib.util.spec_from_file_location(name, ROOT / source)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


installer = module("herdr_install", "herdr/image/install_releases.py")
clients = module("herdr_clients", "herdr/image/managed_clients.py")
core_health = module("herdr_core_health", "herdr/image/core_health.py")
publisher = module("herdr_publish", "herdr/publish_tested_image.py")
PINS = ROOT / "herdr/image/releases.json"
DEPLOYMENT = (ROOT / "herdr/deployment.yaml").read_text()
SOURCE = "a" * 40
BASE = "b" * 40
COMMIT = "c" * 40
DIGEST = "sha256:" + "d" * 64
RUN = "https://github.com/benkim0414/homelab/actions/runs/123"


class PinTests(unittest.TestCase):
    def test_real_pins_cover_both_components_and_architectures(self):
        self.assertEqual(len(installer.load_pins(PINS)), 4)

    def test_malformed_or_partial_pins_are_rejected(self):
        originals = json.loads(PINS.read_text())
        candidates = []
        missing = copy.deepcopy(originals)
        del missing["herdr-arm64"]
        candidates.append(missing)
        for field, value in (("version", "../escape"), ("version", "1.2.3-beta"),
                             ("digest", "sha256:wrong"), ("digest", None)):
            changed = copy.deepcopy(originals)
            changed["herdr-amd64"][field] = value
            candidates.append(changed)
        mismatch = copy.deepcopy(originals)
        mismatch["herdr-core-arm64"]["version"] = "9.9.9"
        candidates.append(mismatch)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pins.json"
            for candidate in candidates:
                with self.subTest(candidate=candidate):
                    path.write_text(json.dumps(candidate))
                    with self.assertRaises(ValueError):
                        installer.load_pins(path)

    def test_checksum_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binary"
            path.write_bytes(b"synthetic executable")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                installer.verify(path, "sha256:" + "0" * 64)

    def archive(self, path, extra=None, link=False):
        with tarfile.open(path, "w:gz") as archive:
            for name in ("herdr-core", "LICENSE", "THIRD-PARTY-NOTICES"):
                member = tarfile.TarInfo(name)
                if link and name == "herdr-core":
                    member.type = tarfile.SYMTYPE
                    member.linkname = "../outside"
                    archive.addfile(member)
                else:
                    member.size = 7
                    archive.addfile(member, io.BytesIO(b"fixture"))
            if extra:
                member = tarfile.TarInfo(extra)
                member.size = 7
                archive.addfile(member, io.BytesIO(b"fixture"))

    def test_core_archive_extracts_binary_and_keeps_notices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.archive(root / "archive")
            installer.extract_core(root / "archive", root / "binary")
            self.assertEqual((root / "binary").read_bytes(), b"fixture")
            self.assertEqual((root / "herdr-core.LICENSE").read_bytes(), b"fixture")
            self.assertTrue((root / "herdr-core.THIRD-PARTY-NOTICES").is_file())

    def test_extra_traversal_duplicate_and_symlink_members_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for extra, link in (("../outside", False), ("herdr-core", False), (None, True)):
                with self.subTest(extra=extra, link=link):
                    self.archive(root / "archive", extra, link)
                    with self.assertRaises(ValueError):
                        installer.extract_core(root / "archive", root / "binary")


class ManagedClientTests(unittest.TestCase):
    def test_unprivileged_install_preserves_old_binaries_and_unrelated_data(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            binary_dir = home / ".local/bin"
            binary_dir.mkdir(parents=True)
            state = home / "untouched-state"
            state.write_text("fixture state")
            for name in clients.TARGETS:
                (binary_dir / name).write_bytes(b"old public executable")
            clients.reconcile(home)
            for name, target in clients.TARGETS.items():
                self.assertEqual(os.readlink(binary_dir / name), target)
                backups = list(binary_dir.glob(name + ".before-image-*"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), b"old public executable")
            clients.reconcile(home)
            self.assertEqual(len(list(binary_dir.glob("*.before-image-*"))), 3)
            self.assertEqual(state.read_text(), "fixture state")

    def test_interrupted_link_replacement_remains_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            binary_dir = home / ".local/bin"
            binary_dir.mkdir(parents=True)
            path = binary_dir / "herdr"
            path.write_bytes(b"old public executable")
            original_replace = Path.replace

            def interrupted_replace(source, destination):
                if source.name.startswith(".herdr.image-"):
                    raise OSError("injected replacement interruption")
                return original_replace(source, destination)

            with patch.object(Path, "replace", interrupted_replace):
                with self.assertRaisesRegex(OSError, "injected"):
                    clients.reconcile(home)
            self.assertEqual(path.stat().st_nlink, 1)
            self.assertEqual(path.read_bytes(), b"old public executable")
            clients.reconcile(home)
            self.assertEqual(os.readlink(path), clients.TARGETS["herdr"])
            self.assertTrue(all(backup.read_bytes() == b"old public executable"
                                for backup in binary_dir.glob("herdr.before-image-*")))

    def test_interrupted_backup_remains_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            binary_dir = home / ".local/bin"
            binary_dir.mkdir(parents=True)
            path = binary_dir / "herdr"
            path.write_bytes(b"old public executable")
            with patch.object(clients.shutil, "copyfileobj", side_effect=OSError("injected copy failure")):
                with self.assertRaisesRegex(OSError, "injected"):
                    clients.reconcile(home)
            self.assertEqual(path.stat().st_nlink, 1)
            self.assertEqual(path.read_bytes(), b"old public executable")
            self.assertEqual(list(binary_dir.glob("herdr.before-image-*")), [])
            clients.reconcile(home)
            self.assertEqual(os.readlink(path), clients.TARGETS["herdr"])

    def test_root_is_rejected_before_any_write(self):
        with patch.object(clients.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(ValueError, "herdr user"):
                clients.reconcile("/does-not-exist")

    def test_symlink_directory_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            outside = home / "outside"
            outside.mkdir()
            (home / ".local").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                clients.reconcile(home)
            self.assertEqual(list(outside.iterdir()), [])

    def test_hardlinked_binary_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            binary_dir = home / ".local/bin"
            binary_dir.mkdir(parents=True)
            path = binary_dir / "herdr"
            path.write_bytes(b"public binary")
            os.link(path, binary_dir / "other")
            with self.assertRaisesRegex(ValueError, "unexpected binary"):
                clients.reconcile(home)
            self.assertFalse(path.is_symlink())


class CoreHealthTests(unittest.TestCase):
    def test_socket_peer_must_be_expected_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            endpoint = home / ".local/state/herdr-core/default/default.sock"
            endpoint.parent.mkdir(parents=True)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(endpoint))
                listener.listen()
                core_health.check_core(home, Path(sys.executable))
                with self.assertRaisesRegex(ValueError, "image-managed binary"):
                    core_health.check_core(home, Path("/usr/bin/bash"))

    def test_stopped_or_missing_core_is_not_auto_started(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with self.assertRaises(OSError):
                core_health.check_core(home)
            self.assertEqual(list(home.iterdir()), [])


class FakeGitHub:
    def __init__(self, stale=False, conflict=False):
        self.calls = []
        self.ref = BASE
        self.updated = None
        self.stale = stale
        self.conflict = conflict

    def __call__(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, payload))
        if method == "GET" and endpoint == "git/ref/heads/main":
            return {"object": {"sha": self.ref}}
        if method == "GET" and endpoint.startswith("git/commits/"):
            return {"tree": {"sha": endpoint.rsplit("/", 1)[1]}}
        if method == "GET" and endpoint.startswith("git/trees/"):
            sha = "new-herdr" if self.stale and endpoint.endswith(BASE) else "tested-herdr"
            return {"tree": [{"path": "herdr", "type": "tree", "sha": sha}]}
        if method == "GET" and endpoint.startswith("contents/herdr/deployment.yaml?ref="):
            content = self.updated if endpoint.endswith(COMMIT) else DEPLOYMENT
            assert content is not None
            return {"content": base64.b64encode(content.encode()).decode()}
        if method == "POST" and endpoint == "git/blobs":
            assert payload is not None
            self.updated = payload["content"]
            return {"sha": "generated-blob"}
        if method == "POST" and endpoint == "git/trees":
            return {"sha": "generated-tree"}
        if method == "POST" and endpoint == "git/commits":
            return {"sha": COMMIT}
        if method == "PATCH" and endpoint == "git/refs/heads/main":
            assert payload is not None
            if self.conflict:
                raise RuntimeError("concurrent main advance")
            self.ref = payload["sha"]
            return {"object": {"sha": self.ref}}
        raise AssertionError((method, endpoint, payload))


class PublisherTests(unittest.TestCase):
    def test_only_two_image_fields_change(self):
        updated = publisher.image_update(DEPLOYMENT, DIGEST)
        before = DEPLOYMENT.splitlines()
        after = updated.splitlines()
        changes = [(left, right) for left, right in zip(before, after) if left != right]
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(changes), 2)
        self.assertTrue(all(right.strip() == f"image: {publisher.IMAGE}@{DIGEST}"
                            for _, right in changes))

    def test_invalid_and_unexpected_image_references_are_rejected(self):
        with self.assertRaises(ValueError):
            publisher.image_update(DEPLOYMENT, "not-a-digest")
        with self.assertRaises(ValueError):
            publisher.image_update(DEPLOYMENT + f"  image: {publisher.IMAGE}@{DIGEST}\n", DIGEST)
        with self.assertRaises(ValueError):
            publisher.image_update("no images", DIGEST)

    def test_generated_commit_is_one_file_fast_forward_only_and_read_back(self):
        api = FakeGitHub()
        with patch.object(publisher, "api", api):
            self.assertEqual(publisher.publish(SOURCE, DIGEST, RUN), COMMIT)
        trees = [payload for method, endpoint, payload in api.calls
                 if method == "POST" and endpoint == "git/trees"]
        self.assertEqual(trees, [{"base_tree": BASE, "tree": [{
            "path": "herdr/deployment.yaml", "mode": "100644",
            "type": "blob", "sha": "generated-blob"}]}])
        refs = [payload for method, endpoint, payload in api.calls if method == "PATCH"]
        self.assertEqual(refs, [{"sha": COMMIT, "force": False}])
        commit = next(payload for method, endpoint, payload in api.calls
                      if method == "POST" and endpoint == "git/commits")
        self.assertEqual(commit["parents"], [BASE])
        self.assertEqual(api.calls[-1][1], f"contents/herdr/deployment.yaml?ref={COMMIT}")

    def test_stale_build_never_writes(self):
        api = FakeGitHub(stale=True)
        with patch.object(publisher, "api", api):
            self.assertIsNone(publisher.publish(SOURCE, DIGEST, RUN))
        self.assertTrue(all(method == "GET" for method, _, _ in api.calls))

    def test_concurrent_commit_is_not_forced_or_retried(self):
        api = FakeGitHub(conflict=True)
        with patch.object(publisher, "api", api):
            with self.assertRaisesRegex(RuntimeError, "concurrent"):
                publisher.publish(SOURCE, DIGEST, RUN)
        self.assertEqual(sum(method == "PATCH" for method, _, _ in api.calls), 1)

    def test_invalid_source_or_evidence_url_fails_before_api(self):
        with patch.object(publisher, "api") as api:
            for source, digest, url in (("main", DIGEST, RUN), (SOURCE, "bad", RUN),
                                        (SOURCE, DIGEST, "https://example.invalid/run")):
                with self.subTest(source=source, digest=digest, url=url):
                    with self.assertRaises(ValueError):
                        publisher.publish(source, digest, url)
            api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
