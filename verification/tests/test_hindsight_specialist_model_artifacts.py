"""Public model artifact integrity tests. No network calls."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'hindsight/extensions/specialist-memory/validation/model_artifacts.py'


class ModelArtifactsTests(unittest.TestCase):
    def load(self):
        self.assertTrue(SOURCE.is_file(), 'pinned model preparation helper is missing')
        spec = importlib.util.spec_from_file_location('specialist_model_artifacts', SOURCE)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_sha256_and_git_blob_integrity(self):
        module = self.load()
        data = b'public artifact fixture'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture'
            path.write_bytes(data)
            self.assertTrue(module.verify_file(path, len(data), 'sha256', hashlib.sha256(data).hexdigest()))
            digest = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            self.assertTrue(module.verify_file(path, len(data), 'git-sha1', digest))
            path.write_bytes(b'changed')
            self.assertFalse(module.verify_file(path, len(data), 'git-sha1', digest))

    def test_symlink_is_not_an_artifact(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'
            target.write_bytes(b'fixture')
            link = Path(tmp) / 'link'
            link.symlink_to(target)
            self.assertFalse(module.verify_file(link, 7, 'sha256', hashlib.sha256(b'fixture').hexdigest()))

    def test_revision_and_model_digest_are_frozen(self):
        module = self.load()
        self.assertEqual(module.REVISION, '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a')
        self.assertEqual(module.FILES['onnx/model.onnx'], (133093490, 'sha256', '828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35'))
        self.assertEqual(len(module.FILES), 6)


if __name__ == '__main__':
    unittest.main()
