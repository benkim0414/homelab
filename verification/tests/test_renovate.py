"""Regression contracts for the self-hosted Renovate runner."""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class RenovateRunnerTests(unittest.TestCase):
    def test_repository_errors_are_process_failures(self):
        values = yaml.safe_load((ROOT / 'renovate/values.yaml').read_text())
        self.assertRegex(values['renovate']['config'], r'\bexitCodeForErrors:\s*true\b')
        self.assertNotIn('exitCodeForErrors', (ROOT / 'renovate.json5').read_text())
        self.assertEqual(values['env']['LOG_FORMAT'], 'json')
        self.assertEqual(values['env']['LOG_LEVEL'], 'info')

    def test_schedule_and_no_retry_boundary_are_preserved(self):
        values = yaml.safe_load((ROOT / 'renovate/values.yaml').read_text())
        cron = values['cronjob']
        self.assertEqual(cron['schedule'], '0 4 * * *')
        self.assertEqual(cron['timeZone'], 'Australia/Melbourne')
        self.assertEqual(cron['concurrencyPolicy'], 'Forbid')
        self.assertFalse(cron['suspend'])
        self.assertEqual(cron['jobRestartPolicy'], 'Never')
        # The chart's truthiness guard needs a string zero, not a numeric zero.
        self.assertEqual(cron['jobBackoffLimit'], '0')
        self.assertEqual(cron['activeDeadlineSeconds'], 1800)
        self.assertRegex((ROOT / 'renovate.json5').read_text(), r'"automerge":\s*false')
