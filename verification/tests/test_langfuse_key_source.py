"""Offline command-secret IPC tests; every credential is a fake fixture."""

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[2] / "hermes/profiles/house-manager/langfuse-key-source.py"
spec = importlib.util.spec_from_file_location("langfuse_key_source", SOURCE)
assert spec is not None and spec.loader is not None
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class LangfuseKeySourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "public-key").write_bytes(b"pk-lf-fake-public")
        (self.root / "secret-key").write_bytes(b"sk-lf-fake-secret")

    def invoke(self, argv=()):
        # Never allow main() to open the real projected Secret directory.
        render = source.render_credentials
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(source, "render_credentials", side_effect=lambda: render(self.root)):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = source.main(list(argv))
        return status, stdout.getvalue(), stderr.getvalue()

    def assert_failure(self):
        status, stdout, stderr = self.invoke()
        self.assertNotEqual(status, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "Langfuse credentials unavailable.\n")

    def test_valid_fake_fixture_exact_ipc(self):
        expected = (
            "HERMES_LANGFUSE_PUBLIC_KEY=pk-lf-fake-public\n"
            "HERMES_LANGFUSE_SECRET_KEY=sk-lf-fake-secret\n"
        )
        expected += "".join(f"{name}={value}\n" for name, value in source.SCOPED_SETTINGS.items())
        self.assertEqual(source.render_credentials(self.root), expected)
        self.assertEqual(self.invoke(), (0, expected, ""))

    def test_missing_second_file_never_emits_first_key(self):
        (self.root / "secret-key").unlink()
        self.assert_failure()

    def test_missing_first_file(self):
        (self.root / "public-key").unlink()
        self.assert_failure()

    def test_invalid_values(self):
        for filename, prefix in (("public-key", b"pk-lf-"), ("secret-key", b"sk-lf-")):
            original = (self.root / filename).read_bytes()
            for value in (b"", prefix, b"wrong-fake", prefix + b"fake\n", prefix + b"fake\r",
                          prefix + b"fake\x00", prefix + b"fake\xff", prefix + b"fake\t",
                          prefix + b"fake value", prefix + b"fake\x7f", prefix + b"fake\x1b"):
                with self.subTest(filename=filename, value=value):
                    (self.root / filename).write_bytes(value)
                    self.assert_failure()
            (self.root / filename).write_bytes(original)

    def test_swapped_prefixes_rejected(self):
        (self.root / "public-key").write_bytes(b"sk-lf-fake-public")
        self.assert_failure()
        (self.root / "public-key").write_bytes(b"pk-lf-fake-public")
        (self.root / "secret-key").write_bytes(b"pk-lf-fake-secret")
        self.assert_failure()

    def test_size_boundary(self):
        for filename, prefix in (("public-key", b"pk-lf-"), ("secret-key", b"sk-lf-")):
            with self.subTest(filename=filename):
                (self.root / filename).write_bytes(prefix + b"x" * (512 - len(prefix)))
                self.assertEqual(self.invoke()[0], 0)
                (self.root / filename).write_bytes(prefix + b"x" * (513 - len(prefix)))
                self.assert_failure()
                (self.root / filename).write_bytes(prefix + b"fake")

    def test_reads_are_bounded_and_only_named_files(self):
        handles = [mock.MagicMock(), mock.MagicMock()]
        for handle, value in zip(handles, (b"pk-lf-fake-public", b"sk-lf-fake-secret")):
            handle.__enter__.return_value.read.return_value = value
        with mock.patch.object(Path, "open", side_effect=handles) as opened:
            source.render_credentials(self.root)
        self.assertEqual(opened.call_args_list, [mock.call("rb"), mock.call("rb")])
        for handle in handles:
            handle.__enter__.return_value.read.assert_called_once_with(513)
        real_open = Path.open
        paths = []
        def record_open(path, *args, **kwargs):
            paths.append(path)
            return real_open(path, *args, **kwargs)
        with mock.patch.object(Path, "open", record_open):
            source.render_credentials(self.root)
        self.assertEqual(paths, [self.root / "public-key", self.root / "secret-key"])

    def test_permission_error_is_generic(self):
        with mock.patch.object(Path, "open", side_effect=PermissionError("fake-sensitive-path/value")):
            self.assert_failure()

    def test_second_read_permission_error_is_atomic(self):
        real_open = Path.open
        def denied(path, *args, **kwargs):
            if path.name == "secret-key":
                raise PermissionError("fake-sensitive-path/value")
            return real_open(path, *args, **kwargs)
        with mock.patch.object(Path, "open", denied):
            self.assert_failure()

    def test_projected_secret_symlinks_supported(self):
        projected = self.root / "..fake-version"
        projected.mkdir()
        (self.root / "..data").symlink_to(projected.name, target_is_directory=True)
        for filename in ("public-key", "secret-key"):
            (self.root / filename).rename(projected / filename)
            (self.root / filename).symlink_to(Path("..data") / filename)
        self.assertEqual(self.invoke()[0], 0)

    def test_unsupported_argv_not_echoed_or_read(self):
        for argv in (["--secret-key=sk-lf-fake-sensitive\nINJECTED=1"],
                     ["--help"], ["/fake/sensitive/path"], ["--", "pk-lf-fake-sensitive"]):
            with self.subTest(argv=argv):
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(source, "render_credentials") as render:
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        status = source.main(argv)
                self.assertNotEqual(status, 0)
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(stderr.getvalue(), "Langfuse credentials unavailable.\n")
                render.assert_not_called()


if __name__ == "__main__":
    unittest.main()
