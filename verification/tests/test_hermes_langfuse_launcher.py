"""Run the launcher against a PATH containing only a fake Hermes executable."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / 'scripts/hermes-langfuse-desktop.sh'


class LauncherTests(unittest.TestCase):
    def test_profile_arguments_and_safe_launch_environment(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'verification') as directory:
            stub = Path(directory) / 'hermes'
            stub.write_text('#!/bin/bash\n'
                            'printf "%s\\0" "$@"\n'
                            'printf "%s\\0" "$HERMES_LANGFUSE_CAPTURE" '
                            '"$HERMES_LANGFUSE_ENV" "$HERMES_LANGFUSE_SAMPLE_RATE" '
                            '"$OTEL_SERVICE_NAME" "$HERMES_LANGFUSE_BASE_URL"\n'
                            'exit 17\n')
            stub.chmod(0o700)
            env = {'PATH': directory, 'HERMES_LANGFUSE_CAPTURE': 'full',
                   'HERMES_LANGFUSE_SAMPLE_RATE': '0', 'HERMES_LANGFUSE_ENV': 'wrong'}
            arguments = ['chat', '-q', 'two words', '', 'a\nb', '*', '$(false)']
            result = subprocess.run(['/bin/bash', str(LAUNCHER), 'test-profile', *arguments],
                                    env=env, capture_output=True)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stdout.decode().split('\0')[:-1],
                         ['-p', 'test-profile', *arguments, 'metadata', 'homelab-desktop', '1',
                          'hermes-desktop-test-profile', 'https://langfuse.tailbd291c.ts.net'])
        source = LAUNCHER.read_text()
        for forbidden in ('REAL-TAILNET', 'SECRET_KEY=', 'PUBLIC_KEY=', 'HERMES_HOME='):
            self.assertNotIn(forbidden, source)

    def test_missing_or_empty_profile_fails_with_usage(self):
        for args in ([], ['']):
            with self.subTest(args=args):
                result = subprocess.run(['/bin/bash', str(LAUNCHER), *args],
                                        env={'PATH': ''}, text=True, capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn('usage:', result.stderr)
                self.assertEqual(result.stdout, '')
