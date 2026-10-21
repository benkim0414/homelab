"""Evaluate Hermes backup alerts against representative Prometheus series."""
import copy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROMTOOL = shutil.which('promtool') or str(ROOT / 'verification/cache/bin/promtool')


@unittest.skipUnless(Path(PROMTOOL).is_file(), 'promtool is required for alert evaluation')
class HermesAlertTests(unittest.TestCase):
    def test_backup_alerts_with_prometheus_evaluation(self):
        document = yaml.safe_load((ROOT / 'monitoring/prometheus-rules.yaml').read_text())
        group = next(group for group in document['spec']['groups'] if group['name'] == 'hermes-backup')
        # Evaluate firing/label behavior independently of annotation wording.
        group = copy.deepcopy(group)
        for rule in group['rules']:
            rule.pop('annotations', None)

        labels = {'namespace': 'hermes', 'cronjob': 'hermes-backup', 'severity': 'warning'}
        info = {'series': 'kube_cronjob_info{namespace="hermes",cronjob="hermes-backup"}',
                'values': '1+0x2400'}
        created = {'series': 'kube_cronjob_created{namespace="hermes",cronjob="hermes-backup"}',
                   'values': '0+0x2400'}

        def success(cronjob='hermes-backup', values='1+60x2400'):
            return {'series': 'kube_cronjob_status_last_successful_time{namespace="hermes",cronjob="'
                    + cronjob + '"}', 'values': values}

        def case(name, series, when, fires):
            return {'name': name, 'interval': '1m', 'input_series': series,
                    'alert_rule_test': [{'eval_time': when, 'alertname': 'HermesBackupStale',
                                         'exp_alerts': [{'exp_labels': labels}] if fires else []}]}

        tests = [
            case('fresh nightly backup', [info, created, success()], '38h', False),
            case('missed nightly backup', [info, created, success(values='1+0x2400')], '38h', True),
            case('new schedule grace', [info, created], '24h', False),
            case('never succeeded', [info, created], '38h', True),
            case('zero timestamp grace', [info, created, success(values='0+0x2400')], '24h', False),
            case('zero timestamp expired', [info, created, success(values='0+0x2400')], '38h', True),
            case('watchdog cannot mask missing backup',
                 [info, created, success('hermes-backup-recovery')], '38h', True),
            case('missing nightly schedule', [success('hermes-backup-recovery')], '61m', True),
        ]
        jobs = ['hermes-backup-123', 'hermes-backup-recovery-456', 'hermes-backup-manual-test']
        tests.append({'name': 'backup and recovery failures only', 'interval': '1m',
                      'input_series': [
                          {'series': f'kube_job_status_failed{{namespace="hermes",job_name="{job}"}}',
                           'values': '1+0x10'} for job in jobs + ['unrelated-job']
                      ] + [{'series': 'kube_job_status_failed{namespace="other",job_name="hermes-backup-123"}',
                            'values': '1+0x10'}],
                      'alert_rule_test': [{'eval_time': '6m', 'alertname': 'HermesBackupJobFailed',
                                           'exp_alerts': [{'exp_labels': {'namespace': 'hermes',
                                               'job_name': job, 'severity': 'critical'}} for job in jobs]}]})
        with tempfile.TemporaryDirectory(dir=ROOT / 'verification/cache') as directory:
            root = Path(directory)
            rules = root / 'rules.yaml'
            rules.write_text(yaml.safe_dump({'groups': document['spec']['groups']}))
            check = subprocess.run([PROMTOOL, 'check', 'rules', str(rules)], capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            rules.write_text(yaml.safe_dump({'groups': [group]}))
            fixture = root / 'tests.yaml'
            fixture.write_text(yaml.safe_dump({'rule_files': [str(rules)],
                'evaluation_interval': '1m', 'tests': tests}))
            result = subprocess.run([PROMTOOL, 'test', 'rules', str(fixture)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
