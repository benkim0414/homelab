import base64
import importlib.util
import io
import json
from pathlib import Path
import secrets
import subprocess
import sys
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'gerrit'
spec = importlib.util.spec_from_file_location('gerrit_provision', APP / 'provision-auth.py')
assert spec and spec.loader
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)


class GerritManifestTests(unittest.TestCase):
    def test_configmap_sources_and_rollout_checksum_are_current(self):
        subprocess.run([sys.executable, APP / 'render-config.py', '--check'], check=True, capture_output=True)
        subprocess.run(['bash', '-n', APP / 'start.sh'], check=True)

    def test_single_writer_pins_security_and_storage(self):
        obj = yaml.safe_load((APP / 'statefulset.yaml').read_text())
        self.assertEqual(obj['spec']['replicas'], 1)
        self.assertEqual(obj['spec']['persistentVolumeClaimRetentionPolicy'], {'whenDeleted': 'Retain', 'whenScaled': 'Retain'})
        pod = obj['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertEqual(pod['nodeSelector']['kubernetes.io/arch'], 'amd64')
        self.assertEqual(pod['securityContext']['fsGroup'], 1000)
        for c in pod['containers']:
            self.assertRegex(c['image'], r'@sha256:[a-f0-9]{64}$')
            self.assertTrue(c['securityContext']['readOnlyRootFilesystem'])
            self.assertFalse(c['securityContext']['allowPrivilegeEscalation'])
            self.assertEqual(c['securityContext']['capabilities']['drop'], ['ALL'])
            self.assertIn('cpu', c['resources']['limits'])
            self.assertIn('memory', c['resources']['limits'])
        gerrit = pod['containers'][0]
        self.assertEqual(gerrit['command'], ['/bin/bash', '/config/start.sh'])
        self.assertNotIn('ports', gerrit)
        self.assertIn('/config/server/version', gerrit['readinessProbe']['exec']['command'][-1])
        storage = list(yaml.safe_load_all((APP / 'storage.yaml').read_text()))
        self.assertEqual(storage[0]['reclaimPolicy'], 'Retain')
        self.assertEqual(storage[0]['parameters']['numberOfReplicas'], '2')
        self.assertEqual(storage[1]['metadata']['name'], 'gerrit-site')
        self.assertEqual(storage[1]['spec']['storageClassName'], storage[0]['metadata']['name'])

    def test_auth_network_and_manual_sync_boundaries(self):
        def get(section, key):
            return subprocess.check_output(['git', 'config', '--file', APP / 'gerrit.config', '--get', section + '.' + key], text=True).strip()
        self.assertEqual(get('auth', 'type'), 'HTTP')
        self.assertEqual(get('auth', 'trustContainerAuth'), 'true')
        self.assertEqual(get('auth', 'httpTrustedProxyNetworks'), '127.0.0.1/32')
        self.assertEqual(get('httpd', 'listenUrl'), 'proxy-https://127.0.0.1:8081/')
        self.assertEqual(get('sshd', 'listenAddress'), 'off')
        self.assertEqual(get('sendemail', 'enable'), 'false')
        self.assertEqual(get('plugins', 'allowRemoteAdmin'), 'false')
        proxy = (APP / 'nginx.conf').read_text()
        self.assertIn('proxy_set_header X-Gerrit-User $remote_user;', proxy)
        self.assertIn('proxy_set_header Authorization "";', proxy)
        service = yaml.safe_load((APP / 'service.yaml').read_text())
        self.assertEqual(service['spec']['type'], 'ClusterIP')
        self.assertEqual(service['spec']['ports'][0]['targetPort'], 'proxy')
        policy = yaml.safe_load((APP / 'network-policy.yaml').read_text())
        self.assertEqual(policy['spec']['egress'], [])
        app = yaml.safe_load((ROOT / 'argocd/apps/gerrit.yaml').read_text())
        self.assertNotIn('automated', app['spec']['syncPolicy'])
        self.assertNotIn('finalizers', app['metadata'])
        self.assertEqual(app['spec']['source']['targetRevision'], 'main')
        self.assertIn('auth-sealed-secret.yaml', app['spec']['source']['directory']['include'])
        self.assertNotIn('DEVELOPMENT_BECOME_ANY_ACCOUNT', (APP / 'gerrit.config').read_text())


class GerritCredentialTests(unittest.TestCase):
    def test_short_password_reprompts_without_echoing_input(self):
        password = secrets.token_urlsafe(24)
        diagnostic = io.StringIO()
        with patch.object(provision.getpass, 'getpass', side_effect=['short', password, password]), patch.object(provision.sys, 'stderr', diagnostic):
            self.assertEqual(provision.prompt_password(), password)
        self.assertIn('at least 16 characters', diagnostic.getvalue())
        self.assertNotIn(password, diagnostic.getvalue())
        self.assertNotIn('short', diagnostic.getvalue())

    def test_confirmation_mismatch_reprompts_without_echoing_input(self):
        password, other = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        diagnostic = io.StringIO()
        with patch.object(provision.getpass, 'getpass', side_effect=[password, other, password, password]), patch.object(provision.sys, 'stderr', diagnostic):
            self.assertEqual(provision.prompt_password(), password)
        self.assertIn('Passwords differ', diagnostic.getvalue())
        self.assertNotIn(password, diagnostic.getvalue())
        self.assertNotIn(other, diagnostic.getvalue())

    def test_hash_and_seal_failures_report_stage_without_subprocess_output(self):
        sensitive = secrets.token_urlsafe(24)
        failure = subprocess.CalledProcessError(7, ['test'], output=sensitive.encode(), stderr=sensitive.encode())
        with patch.object(provision.subprocess, 'run', side_effect=failure):
            with self.assertRaises(provision.ProvisionError) as hashing:
                provision.build_secret([('admin', 'a@example.invalid', secrets.token_urlsafe(24))])
            with self.assertRaises(provision.ProvisionError) as sealing:
                provision.seal({'kind': 'Secret'}, '/test/kubeseal')
            with self.assertRaises(provision.ProvisionError) as certificate:
                provision.check_sealer('/test/kubeseal')
        self.assertIn('OpenSSL exit 7', str(hashing.exception))
        self.assertIn('kubeseal exit 7', str(sealing.exception))
        self.assertIn('public-certificate lookup failed', str(certificate.exception))
        for error in (hashing, sealing, certificate):
            self.assertNotIn(sensitive, str(error.exception))

    def test_sealer_preflight_requires_certificate_and_times_out_safely(self):
        with patch.object(provision.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=b'not a certificate')):
            with self.assertRaises(provision.ProvisionError):
                provision.check_sealer('/test/kubeseal')
        with patch.object(provision.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['test'], 45)):
            with self.assertRaisesRegex(provision.ProvisionError, 'timed out'):
                provision.check_sealer('/test/kubeseal')

    def test_invalid_identities_and_passwords_fail_before_hashing(self):
        bad = [('Admin', 'a@example.invalid'), ('admin;', 'a@example.invalid'),
               ('admin', 'a@example.invalid;'), ('admin', 'not-an-email')]
        with patch.object(provision.subprocess, 'run') as run:
            for username, email in bad:
                with self.subTest(username=username, email=email), self.assertRaises(ValueError):
                    provision.build_secret([(username, email, secrets.token_urlsafe(24))])
            with self.assertRaises(ValueError):
                provision.build_secret([('admin', 'a@example.invalid', 'short')])
            with self.assertRaises(ValueError):
                provision.build_secret([])
            run.assert_not_called()

    def test_actual_hashing_keeps_plaintext_out_of_manifest_and_arguments(self):
        password = secrets.token_urlsafe(24)
        original = subprocess.run
        with patch.object(provision.subprocess, 'run', wraps=original) as calls:
            secret = provision.build_secret([('admin', 'a@example.invalid', password)])
        self.assertNotIn(password, json.dumps(secret))
        self.assertNotIn(password, str(calls.call_args.args))
        value = base64.b64decode(secret['data']['htpasswd']).decode()
        self.assertTrue(value.startswith('admin:$6$'))
        self.assertEqual(secret['metadata'], {'name': 'gerrit-auth', 'namespace': 'gerrit'})
        mapping = base64.b64decode(secret['data']['identities.conf']).decode()
        self.assertIn('"admin" "a@example.invalid";', mapping)

    def test_sealing_scope_and_output_identity_are_checked(self):
        secret = {'kind': 'Secret'}
        sealed = {'kind': 'SealedSecret', 'metadata': {'name': 'gerrit-auth', 'namespace': 'gerrit'},
                  'spec': {'encryptedData': {'htpasswd': 'unit-test-ciphertext', 'identities.conf': 'unit-test-ciphertext'}}}
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(sealed).encode())
        with patch.object(provision.subprocess, 'run', return_value=completed) as call:
            self.assertEqual(json.loads(provision.seal(secret, '/test/kubeseal')), sealed)
            self.assertIn('strict', call.call_args.args[0])
            self.assertNotIn(secret, call.call_args.args[0])
        sealed['metadata']['namespace'] = 'wrong'
        completed.stdout = json.dumps(sealed).encode()
        with patch.object(provision.subprocess, 'run', return_value=completed), self.assertRaises(ValueError):
            provision.seal(secret, '/test/kubeseal')

    def test_noninteractive_provisioning_refuses_before_credentials(self):
        result = subprocess.run([sys.executable, APP / 'provision-auth.py'], capture_output=True, input=b'')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'private terminal', result.stderr)


if __name__ == '__main__':
    unittest.main()
