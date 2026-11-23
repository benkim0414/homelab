"""Offline regression checks for isolated specialist scheduled backup controllers."""
import copy
import datetime as dt
from pathlib import Path
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import yaml
import test_hermes_backup as existing

ROOT = Path(__file__).resolve().parents[2]
PROFILES = {
    'learning-coach': ('6fae088c-2245-47aa-82ba-cf48ce7dc8f6', '9d208021-9c6f-44c5-ad5c-0448800a704c', '15 4 * * *'),
    'career-advisor': ('f4805c89-7cfe-4592-a413-b0ea7f1715af', '4e344dc7-e178-4a3d-9d29-22676636a91f', '30 4 * * *'),
}


class SpecialistManifestTests(unittest.TestCase):
    def test_standalone_backup_manifests_exist(self):
        for profile in PROFILES:
            for kind in ('configmap', 'cronjob', 'rbac', 'network-policy'):
                with self.subTest(profile=profile, kind=kind):
                    self.assertTrue((ROOT / f'hermes/profiles/{profile}/backup-{kind}.yaml').is_file())


    def test_schedules_identity_and_runtime_limits(self):
        image = 'nousresearch/hermes-agent:v0.23.2@sha256:d6746a084e9341baada483e3d6210444d3c1aeb7c130f0915150065fb2851459'
        for profile, (pvc_uid, _, schedule) in PROFILES.items():
            docs = list(yaml.safe_load_all((ROOT / f'hermes/profiles/{profile}/backup-cronjob.yaml').read_text()))
            self.assertEqual(len(docs), 2)
            for index, doc in enumerate(docs):
                with self.subTest(profile=profile, job=index):
                    self.assertEqual(doc['metadata']['namespace'], profile)
                    self.assertEqual(doc['spec']['schedule'], schedule if index == 0 else '*/5 * * * *')
                    self.assertEqual(doc['spec']['timeZone'], 'Australia/Melbourne')
                    self.assertEqual(doc['spec']['concurrencyPolicy'], 'Forbid')
                    job = doc['spec']['jobTemplate']['spec']
                    self.assertEqual(job['backoffLimit'], 0)
                    self.assertEqual(job['activeDeadlineSeconds'], 1200 if index == 0 else 90)
                    pod = job['template']['spec']
                    self.assertEqual(pod['restartPolicy'], 'Never')
                    self.assertEqual(pod['serviceAccountName'], profile + '-backup' + ('-recovery' if index else ''))
                    self.assertTrue(pod['automountServiceAccountToken'])
                    self.assertTrue(pod['securityContext']['runAsNonRoot'])
                    self.assertEqual(pod['volumes'], [{'name': 'script', 'configMap': {'name': profile + '-backup'}}])
                    container = pod['containers'][0]
                    self.assertEqual(container['image'], image)
                    self.assertTrue(container['securityContext']['readOnlyRootFilesystem'])
                    env = {e['name']: e.get('value') for e in container['env']}
                    self.assertEqual(env['HERMES_VOLUME'], 'pvc-' + pvc_uid)
                    self.assertEqual(env.get('BACKUP_MODE'), 'recover' if index else None)
                    if index == 0:
                        self.assertEqual(env['BACKUP_KEEP'], '7')

    def test_network_is_api_only_for_both_runner_labels(self):
        for profile in PROFILES:
            doc = yaml.safe_load((ROOT / f'hermes/profiles/{profile}/backup-network-policy.yaml').read_text())
            spec = doc['spec']
            self.assertEqual(doc['metadata']['namespace'], profile)
            self.assertEqual(spec['podSelector']['matchLabels'], {'app.kubernetes.io/name': profile + '-backup'})
            self.assertEqual(set(spec['policyTypes']), {'Ingress', 'Egress'})
            self.assertEqual(spec['ingress'], [])
            self.assertEqual(spec['egress'], [
                {'to': [{'ipBlock': {'cidr': '10.43.0.1/32'}}], 'ports': [{'protocol': 'TCP', 'port': 443}]},
                {'to': [{'ipBlock': {'cidr': '192.168.0.' + suffix + '/32'}} for suffix in ('11', '12', '13')],
                 'ports': [{'protocol': 'TCP', 'port': 6443}]}])
            for job in yaml.safe_load_all((ROOT / f'hermes/profiles/{profile}/backup-cronjob.yaml').read_text()):
                self.assertEqual(job['spec']['jobTemplate']['spec']['template']['metadata']['labels'], spec['podSelector']['matchLabels'])

    def test_rbac_is_namespaced_restricted_and_has_no_cross_specialist_subjects(self):
        longhorn_names = set()
        for profile, (pvc_uid, _, _) in PROFILES.items():
            docs = list(yaml.safe_load_all((ROOT / f'hermes/profiles/{profile}/backup-rbac.yaml').read_text()))
            roles = {(d['metadata']['namespace'], d['metadata']['name']): d for d in docs if d['kind'] == 'Role'}
            self.assertEqual({d['metadata']['name'] for d in docs if d['kind'] == 'ServiceAccount'},
                             {profile + '-backup', profile + '-backup-recovery'})
            for doc in docs:
                self.assertIn(doc['kind'], ('Role', 'RoleBinding', 'ServiceAccount'))
                ns, name = doc['metadata']['namespace'], doc['metadata']['name']
                self.assertIn(ns, (profile, 'longhorn-system'))
                self.assertTrue(name.startswith(profile + '-backup'))
                if ns == 'longhorn-system':
                    identity = (doc['kind'], name)
                    self.assertNotIn(identity, longhorn_names)
                    longhorn_names.add(identity)
                if doc['kind'] == 'RoleBinding':
                    self.assertEqual(doc['roleRef']['kind'], 'Role')
                    role = roles[ns, doc['roleRef']['name']]
                    for subject in doc['subjects']:
                        self.assertEqual(subject['namespace'], profile)
                        self.assertIn(subject['name'], (profile + '-backup', profile + '-backup-recovery'))
                        if subject['name'].endswith('-recovery'):
                            self.assertEqual(ns, profile)
                            self.assertEqual({r for rule in role['rules'] for r in rule['resources']},
                                             {'deployments', 'deployments/scale', 'leases'})
                if doc['kind'] != 'Role':
                    continue
                for rule in doc['rules']:
                    self.assertNotIn('*', rule['verbs'])
                    self.assertNotIn('*', rule['resources'])
                    for resource in rule['resources']:
                        expected = {
                            'deployments': ([profile], ['get']),
                            'deployments/scale': ([profile], ['get', 'patch']),
                            'persistentvolumeclaims': ([profile + '-data'], ['get']),
                            'pods': (None, ['list']),
                            'volumes': (['pvc-' + pvc_uid], ['get']),
                            'backuptargets': (['default'], ['get']),
                            'snapshots': (None, ['get', 'list', 'create', 'delete']),
                            'backups': (None, ['get', 'list', 'create', 'delete']),
                            'leases': ([profile + '-backup'], ['get', 'update']) if 'get' in rule['verbs'] else (None, ['create']),
                        }[resource]
                        self.assertEqual((rule.get('resourceNames'), rule['verbs']), expected)

    def test_argo_covers_exact_backup_files_and_preserves_manual_sync(self):
        for profile in PROFILES:
            app = yaml.safe_load((ROOT / f'argocd/apps/{profile}.yaml').read_text())
            source = app['spec']['source']
            self.assertEqual(source['path'], f'hermes/profiles/{profile}')
            self.assertEqual(source['targetRevision'], 'main')
            self.assertNotIn('automated', app['spec']['syncPolicy'])
            self.assertEqual(source['directory']['include'], '{resources.yaml,backup-*.yaml}')


class SpecialistControllerMixin:
    """Run every original failure/retention test against each standalone copy."""
    def setUp(self):
        pvc_uid, deployment_uid, _ = PROFILES[self.profile]
        module = types.ModuleType(self.profile.replace('-', '_') + '_backup')
        source = yaml.safe_load((ROOT / f'hermes/profiles/{self.profile}/backup-configmap.yaml').read_text())['data']['backup.py']
        exec(compile(source, self.profile + ':backup.py', 'exec'), module.__dict__)
        self.module = module
        profile = self.profile
        original_fake = existing.FakeAPI

        class SpecialistAPI(original_fake):
            def __init__(self):
                super().__init__()
                self.deployment['metadata'].update(uid=deployment_uid, resourceVersion='1')
                self.pvc_uid = pvc_uid
                self.fail_pvc = False
                self.replace_on_patch = self.conflict_on_patch = False

            def call(self, method, path, body=None, *args):
                clean = urlsplit(path).path
                if clean.endswith('/persistentvolumeclaims/' + profile + '-data'):
                    self.calls.append((method, path, copy.deepcopy(body)))
                    if self.fail_pvc:
                        raise module.ApiError(503, path)
                    return {'metadata': {'uid': self.pvc_uid},
                            'spec': {'volumeName': self.volume}, 'status': {'phase': 'Bound'}}
                if clean == module.CONTROL + '/scale':
                    if method == 'GET':
                        self.calls.append((method, path, copy.deepcopy(body)))
                        return copy.deepcopy(self.deployment)
                    if self.replace_on_patch:
                        self.deployment['metadata']['uid'] = 'replacement'
                    if self.conflict_on_patch:
                        self.deployment['metadata']['resourceVersion'] = '2'
                    metadata = body.get('metadata', {})
                    if any(metadata.get(key, self.deployment['metadata'][key]) != self.deployment['metadata'][key]
                           for key in ('uid', 'resourceVersion')):
                        self.calls.append((method, path, copy.deepcopy(body)))
                        raise module.ApiError(409, path)
                    result = super().call(method, path, body, *args)
                    self.deployment['metadata']['resourceVersion'] = str(int(self.deployment['metadata']['resourceVersion']) + 1)
                    return result
                return super().call(method, path, body, *args)

        self.api_class = SpecialistAPI
        for key, value in {'MODULE': module, 'VOLUME': 'pvc-' + pvc_uid, 'FakeAPI': SpecialistAPI}.items():
            patcher = patch.object(existing, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_controller_pins_source_target_and_policy(self):
        pvc_uid, deployment_uid, _ = PROFILES[self.profile]
        self.assertEqual(self.module.PVC_UID, pvc_uid)
        self.assertEqual(self.module.DEPLOYMENT_UID, deployment_uid)
        self.assertEqual(self.module.POLICY, self.profile + '-nightly')
        self.assertEqual(self.module.TARGET, 'nfs://192.168.0.40:/longhorn-backups')
        self.assertEqual(self.module.CONTROL,
                         f'/apis/apps/v1/namespaces/{self.profile}/deployments/{self.profile}')
        self.assertEqual(self.module.LEASE_NAME, self.profile + '-backup')

    def test_replaced_pvc_uid_does_not_pause(self):
        api = self.api_class()
        api.pvc_uid = 'replacement'
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            self.runner(api).backup()
        self.assertEqual(api.deployment['spec']['replicas'], 1)
        self.assertFalse(any(m == 'PATCH' for m, _, _ in api.calls))

    def test_replaced_deployment_uid_does_not_pause(self):
        api = self.api_class()
        api.deployment['metadata']['uid'] = 'replacement'
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            self.runner(api).backup()
        self.assertEqual(api.deployment['spec']['replicas'], 1)
        self.assertFalse(any(m == 'PATCH' for m, _, _ in api.calls))

    def paused(self):
        api = self.api_class()
        runner = self.runner(api)
        api.deployment['spec']['replicas'] = 0
        api.lease['metadata']['annotations'] = {
            self.module.PREFIX + 'holder': 'runner-1', self.module.PREFIX + 'replicas': '1'}
        return api, runner

    def test_watchdog_resumes_without_pvc_access_after_expired_lease_takeover(self):
        api, _ = self.paused()
        api.fail_pvc = True
        api.lease['spec']['renewTime'] = self.module.stamp(self.module.utcnow() - dt.timedelta(minutes=5))
        with patch.dict(self.module.os.environ, {'POD_UID': 'watchdog', 'HERMES_VOLUME': api.volume,
                                               'BACKUP_MODE': 'recover'}), \
                patch.object(self.module, 'API', return_value=api), patch.object(self.module.signal, 'signal'):
            self.module.main()
        self.assertEqual(api.deployment['spec']['replicas'], 1)
        self.assertEqual(api.lease['metadata']['annotations'], {})
        self.assertEqual(api.lease['spec']['holderIdentity'], '')
        self.assertFalse(any('persistentvolumeclaims' in p for _, p, _ in api.calls))

    def test_watchdog_refuses_uid_replaced_deployment_and_retains_marker(self):
        api, _ = self.paused()
        api.deployment['metadata']['uid'] = 'replacement'
        api.lease['spec']['renewTime'] = self.module.stamp(self.module.utcnow() - dt.timedelta(minutes=5))
        with patch.dict(self.module.os.environ, {'POD_UID': 'watchdog', 'HERMES_VOLUME': api.volume,
                                               'BACKUP_MODE': 'recover'}), \
                patch.object(self.module, 'API', return_value=api), patch.object(self.module.signal, 'signal'):
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                self.module.main()
        self.assertEqual(api.deployment['spec']['replicas'], 0)
        self.assertEqual(api.lease['metadata']['annotations'][self.module.PREFIX + 'holder'], 'runner-1')
        self.assertFalse(any(m == 'PATCH' for m, _, _ in api.calls))

    def test_finally_resumes_when_pvc_lookups_fail_after_pause(self):
        api = self.api_class()
        original_call = api.call

        def fail_after_pause(method, path, body=None, *args):
            if method == 'POST' and path.endswith('/snapshots'):
                api.fail_pvc = True
                raise self.module.ApiError(503, path)
            return original_call(method, path, body, *args)

        api.call = fail_after_pause
        with self.assertRaises(self.module.ApiError):
            self.runner(api).backup()
        self.assertTrue(api.fail_pvc)
        self.assertEqual(api.deployment['spec']['replicas'], 1)
        self.assertEqual(api.lease['metadata']['annotations'], {})

    def test_resume_scale_patch_has_uid_and_resourceversion_preconditions(self):
        api, runner = self.paused()
        runner.resume('runner-1')
        patches = [b for m, p, b in api.calls if m == 'PATCH' and p.endswith('/scale')]
        self.assertEqual(patches[0].get('metadata'), {'uid': PROFILES[self.profile][1], 'resourceVersion': '1'})

    def test_resume_refuses_replacement_between_scale_get_and_patch(self):
        api, runner = self.paused()
        api.replace_on_patch = True
        with self.assertRaises(self.module.ApiError):
            runner.resume('runner-1')
        self.assertEqual(api.deployment['spec']['replicas'], 0)
        self.assertIn(self.module.PREFIX + 'holder', api.lease['metadata']['annotations'])

    def test_resume_does_not_retry_resourceversion_conflict(self):
        api, runner = self.paused()
        api.conflict_on_patch = True
        with self.assertRaises(self.module.ApiError):
            runner.resume('runner-1')
        self.assertEqual(api.deployment['spec']['replicas'], 0)
        self.assertEqual(sum(m == 'PATCH' for m, _, _ in api.calls), 1)


    def test_retention_excludes_manual_foreign_and_failed_backups(self):
        api = self.api_class()
        labels = {'backup-volume': api.volume, 'backup-target': 'default',
                  self.module.PREFIX + 'policy': self.module.POLICY}
        for day in range(1, 9):
            name = f'owned-{day:02}'
            api.backups[name] = {
                'metadata': {'name': name, 'uid': name, 'labels': dict(labels)},
                'spec': {'snapshotName': name},
                'status': {'state': 'Completed', 'volumeName': api.volume,
                           'url': self.module.TARGET + '?backup=' + name,
                           'backupCreatedAt': f'2026-10-{day:02}T04:00:00Z'}}
        excluded = {}
        for name, changes, state in (
                ('manual-learning-coach', {self.module.PREFIX + 'policy': None}, 'Completed'),
                ('foreign-policy', {self.module.PREFIX + 'policy': 'another-specialist-nightly'}, 'Completed'),
                ('foreign-volume', {'backup-volume': 'pvc-foreign'}, 'Completed'),
                ('foreign-target', {'backup-target': 'another-target'}, 'Completed'),
                ('failed', {}, 'Error'), ('unknown', {}, 'Unknown'), ('pending', {}, 'Pending')):
            item = copy.deepcopy(api.backups['owned-01'])
            item['metadata'].update(name=name, uid=name)
            item['metadata']['labels'].update(changes)
            item['status']['state'] = state
            excluded[name] = item
        api.backups.update(copy.deepcopy(excluded))
        self.runner(api).backup()
        for name, original in excluded.items():
            self.assertEqual(api.backups[name], original)
        owned = [b for b in api.backups.values() if b['metadata']['labels'] == labels
                 and b['status']['state'] == 'Completed']
        self.assertEqual(len(owned), 7)
        self.assertCountEqual([p.rsplit('/', 1)[-1] for m, p, _ in api.calls if m == 'DELETE'],
                              ['owned-01', 'owned-02'])

    def test_snapshot_failure_has_no_operation_retry(self):
        api = self.api_class()
        api.fail_snapshot = True
        with self.assertRaises(self.module.ApiError):
            self.runner(api).backup()
        self.assertEqual(sum(m == 'POST' and p.endswith('/snapshots') for m, p, _ in api.calls), 1)
        self.assertFalse(any(m == 'POST' and p.endswith('/backups') for m, p, _ in api.calls))

    def test_pause_scale_patch_has_uid_and_resourceversion_preconditions(self):
        api = self.api_class()
        self.runner(api).backup()
        patches = [b for m, p, b in api.calls if m == 'PATCH' and p.endswith('/scale')]
        self.assertEqual(patches[0]['metadata'], {'uid': PROFILES[self.profile][1], 'resourceVersion': '1'})
        self.assertEqual(patches[0]['spec'], {'replicas': 0})
        self.assertEqual(patches[1]['metadata']['resourceVersion'], '2')

    def test_resume_preserves_operator_positive_replica_count(self):
        api, runner = self.paused()
        api.deployment['spec']['replicas'] = 2
        self.assertTrue(runner.resume('runner-1'))
        self.assertEqual(api.deployment['spec']['replicas'], 2)
        self.assertFalse(any(m == 'PATCH' for m, _, _ in api.calls))

    def test_resume_accepts_api_omitted_zero_scale_replicas(self):
        api, runner = self.paused()
        original_call = api.call

        def omit_zero(method, path, body=None, *args):
            value = original_call(method, path, body, *args)
            if method == 'GET' and path.endswith('/scale') and value['spec'].get('replicas') == 0:
                value['spec'].pop('replicas')
            return value

        api.call = omit_zero
        self.assertTrue(runner.resume('runner-1'))
        self.assertEqual(api.deployment['spec']['replicas'], 1)
        self.assertEqual(api.lease['metadata']['annotations'], {})

    def test_initial_pvc_lookup_failure_never_pauses(self):
        api = self.api_class()
        api.fail_pvc = True
        with self.assertRaises(self.module.ApiError):
            self.runner(api).backup()
        self.assertEqual(api.deployment['spec']['replicas'], 1)
        self.assertFalse(any(m == 'PATCH' for m, _, _ in api.calls))


class LearningCoachBackupTests(SpecialistControllerMixin, existing.HermesBackupTests):
    profile = 'learning-coach'


class CareerAdvisorBackupTests(SpecialistControllerMixin, existing.HermesBackupTests):
    profile = 'career-advisor'


if __name__ == '__main__':
    unittest.main()
