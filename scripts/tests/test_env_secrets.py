"""Run only an isolated copy of the writer with fake Bitwarden helpers."""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "env-secrets.sh"
FAKE_GRAFANA = "FAKE_TEST_ONLY_GRAFANA_TOKEN"
FAKE_ARGOCD = "FAKE_TEST_ONLY_ARGOCD_TOKEN"


class EnvSecretsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        self.script = self.root / "scripts/env-secrets.sh"
        shutil.copyfile(SCRIPT, self.script)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.helper("bw-ensure-unlocked", "umask > \"$TEST_ROOT/observed-umask\"\n: > \"$TEST_ROOT/helper-output\"\n")
        self.helper("bw-field", """case "$1:$2" in
  0e456863-1143-4c67-9f11-1d3be2b14a2f:grafana-mcp) printf '%s\\n' "$FAKE_GRAFANA" ;;
  7f52fd96-a070-4e18-8f1c-9cb23b53104b:argocd-mcp) printf '%s\\n' "$FAKE_ARGOCD" ;;
  *) exit 99 ;;
esac
""")
        self.env = {
            "PATH": str(self.bin) + os.pathsep + os.defpath,
            "HOME": str(self.root),
            "TEST_ROOT": str(self.root),
            "FAKE_GRAFANA": FAKE_GRAFANA,
            "FAKE_ARGOCD": FAKE_ARGOCD,
        }
        self.cache = self.root / ".env.local"

    def helper(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body)
        path.chmod(0o755)

    def run_writer(self, *flags):
        return subprocess.run(
            ["bash", *flags, str(self.script)], env=self.env,
            capture_output=True, text=True, umask=0,
        )

    def test_success_atomically_replaces_cache_without_modifying_old_inode(self):
        self.cache.write_text("OLD_FAKE_CACHE\n")
        old_link = self.root / "old-inode"
        os.link(self.cache, old_link)
        result = self.run_writer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(old_link.read_text(), "OLD_FAKE_CACHE\n")
        self.assertEqual(self.cache.read_text(),
                         f"GRAFANA_SERVICE_ACCOUNT_TOKEN={FAKE_GRAFANA}\n"
                         f"ARGOCD_API_TOKEN={FAKE_ARGOCD}\n")
        self.assertEqual(list(self.root.glob(".env.local.*")), [])

    def test_accepts_normal_jq_line_terminator(self):
        result = self.run_writer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"GRAFANA_SERVICE_ACCOUNT_TOKEN={FAKE_GRAFANA}\n", self.cache.read_text())

    def test_invalid_values_retain_old_cache(self):
        for key in ("FAKE_GRAFANA", "FAKE_ARGOCD"):
            for value in ("", "FAKE_LINE\nINJECTED=value", "FAKE_TRAILING\n", "FAKE\rVALUE"):
                with self.subTest(key=key, value=repr(value)):
                    self.cache.write_text("OLD_FAKE_CACHE\n")
                    self.env[key] = value
                    result = self.run_writer()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.cache.read_text(), "OLD_FAKE_CACHE\n")
                    self.assertEqual(list(self.root.glob(".env.local.*")), [])
            self.env[key] = FAKE_GRAFANA if key == "FAKE_GRAFANA" else FAKE_ARGOCD

    def test_tokens_are_not_exposed_with_shell_tracing(self):
        result = self.run_writer("-x")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(FAKE_GRAFANA, result.stdout + result.stderr)
        self.assertNotIn(FAKE_ARGOCD, result.stdout + result.stderr)

    def test_retrieval_failure_retains_cache_without_exposing_helper_output(self):
        for name in ("bw-ensure-unlocked", "bw-field"):
            with self.subTest(helper=name):
                original = (self.bin / name).read_text()
                self.helper(name, 'printf "%s" "$FAKE_GRAFANA"\nprintf "%s" "$FAKE_ARGOCD" >&2\nreturn 1 2>/dev/null || exit 1\n')
                self.cache.write_text("OLD_FAKE_CACHE\n")
                result = self.run_writer()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.cache.read_text(), "OLD_FAKE_CACHE\n")
                self.assertNotIn(FAKE_GRAFANA, result.stdout + result.stderr)
                self.assertNotIn(FAKE_ARGOCD, result.stdout + result.stderr)
                (self.bin / name).write_text(original)

    def test_replacement_failure_retains_cache_and_cleans_temp_file(self):
        self.helper("mv", "exit 1\n")
        self.cache.write_text("OLD_FAKE_CACHE\n")
        result = self.run_writer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.cache.read_text(), "OLD_FAKE_CACHE\n")
        self.assertEqual(list(self.root.glob(".env.local.*")), [])

    def test_umask_is_restrictive_before_helpers_create_output(self):
        result = self.run_writer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "observed-umask").read_text().strip(), "0077")
        self.assertEqual(stat.S_IMODE((self.root / "helper-output").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.cache.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
