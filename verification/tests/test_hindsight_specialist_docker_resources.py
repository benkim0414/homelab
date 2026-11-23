"""Offline lifecycle tests: the injected runner never executes Docker."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable
import unittest

PATH = Path(__file__).resolve().parents[2] / 'hindsight/extensions/specialist-memory/validation/docker_resources.py'
module: Any = None
if PATH.exists():
    spec = importlib.util.spec_from_file_location('docker_resources', PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
else:
    module = None

CID = 'a' * 64

class Runner:
    def __init__(self):
        self.calls = []
        self.responses = []
        self.before: Callable | None = None

    def __call__(self, args):
        self.calls.append(args)
        if self.before:
            self.before(args)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return subprocess.CompletedProcess(args, *value)


def ok(text=''):
    return (0, text, '')


def metadata(h, **updates):
    data = {'Id': h.id, 'Name': '/' + h.name, 'Config': {'Image': h.image, 'Labels': {module.LABEL: h.owner}}, 'State': {'Status': 'created'}}
    data.update(updates)
    return ok(json.dumps([data]))


def absent(h):
    return (1, '', f'Error response from daemon: No such {h.kind}: {h.id or h.name}')


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'lifecycle helper is not implemented')
        self.runner = Runner()
        self.life = module.DockerResources(self.runner)

    def container(self):
        self.runner.responses = [ok(CID + '\n')]
        h = self.life.create('container', image='approved@sha256:test', command=('serve',))
        self.assertEqual(h.id, CID)
        return h

    def test_model_data_mount_is_readonly_nonroot_and_from_public_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models = root / 'pinned-public-model'
            models.mkdir()
            previous = getattr(module,'MODEL_ROOT',None)
            module.MODEL_ROOT = root
            try:
                self.runner.responses = [ok(CID)]
                h = self.life.create('container',image='sha256:'+'b'*64,models=str(models))
                self.assertEqual(h.id,CID)
                args = self.runner.calls[-1]
                self.assertIn(f'type=bind,src={models},dst=/models,readonly',args)
                self.assertIn('--read-only',args)
                self.assertIn('1000:1000',args)
                self.assertIn('/tmp',args)
                self.assertIn('ALL',args)
                before = len(self.runner.calls)
                with self.assertRaises(ValueError):
                    self.life.create('container',image='approved',models='/home')
                self.assertEqual(len(self.runner.calls),before)
            finally:
                if previous is None: delattr(module,'MODEL_ROOT')
                else: module.MODEL_ROOT = previous

    def test_internal_network_uses_explicit_private_subnet(self):
        self.runner.responses = [ok('b'*64)]
        h = self.life.create('network',subnet='172.30.240.0/28')
        self.assertEqual(h.id,'b'*64)
        self.assertIn('--internal',self.runner.calls[-1])
        self.assertIn('--subnet',self.runner.calls[-1])
        self.assertIn('172.30.240.0/28',self.runner.calls[-1])
        with self.assertRaises(ValueError):
            self.life.create('network',subnet='8.8.8.0/24')

    def test_create_records_attempt_before_dispatch(self):
        self.runner.before = lambda args: self.assertEqual(len(self.life.handles), 1)
        h = self.container()
        self.assertIn('--label', self.runner.calls[0])
        self.assertIn(f'{module.LABEL}={h.owner}', self.runner.calls[0])
        self.assertEqual(self.life.events[-1].stage, 'create')
        self.assertEqual(self.life.events[-1].exit_code, 0)

    def test_ambiguous_create_reconciles_exact_name_once_and_binds_id(self):
        def dispatch(args):
            h = self.life.handles[0]
            if args[:2] == ['container', 'create']:
                return (1, '', 'PRIVATE')
            self.assertEqual(args, ['container', 'inspect', h.name])
            data = {'Id': CID, 'Name': '/' + h.name, 'Config': {'Image': h.image, 'Labels': {module.LABEL: h.owner}}, 'State': {'Status': 'created'}}
            return ok(json.dumps([data]))
        self.runner.responses = []
        class Dynamic:
            def __call__(_, args):
                self.runner.calls.append(args)
                return subprocess.CompletedProcess(args, *dispatch(args))
        self.life.runner = Dynamic()
        h = self.life.create('container', image='approved')
        self.assertEqual(h.id, CID)
        self.assertEqual(len(self.runner.calls), 2)
        self.assertFalse(h.failed)

    def test_ambiguous_create_never_adopts_foreign_image_or_label(self):
        for change in ('image', 'label', 'id', 'null', 'missing'):
            with self.subTest(change=change):
                self.setUp()
                def dispatch(args):
                    h = self.life.handles[0]
                    if 'create' in args:
                        raise subprocess.TimeoutExpired('PRIVATE', 1)
                    data = {'Id': CID, 'Name': '/' + h.name, 'Config': {'Image': h.image, 'Labels': {module.LABEL: h.owner}}, 'State': {'Status': 'created'}}
                    if change == 'image':
                        data['Config']['Image'] = 'foreign'
                    elif change == 'label':
                        data['Config']['Labels'][module.LABEL] = 'foreign'
                    elif change == 'id':
                        data['Id'] = '--unsafe'
                    elif change == 'null':
                        return subprocess.CompletedProcess(args, *ok('null'))
                    else:
                        return subprocess.CompletedProcess(args, 1, '', 'daemon unavailable')
                    return subprocess.CompletedProcess(args, *ok(json.dumps([data])))
                self.life.runner = dispatch
                h = self.life.create('container', image='approved')
                self.assertIsNone(h.id)
                self.assertFalse(self.life.cleanup())
                self.assertTrue(h.failed)

    def test_container_id_cannot_be_reassigned(self):
        h = self.container()
        with self.assertRaises((AttributeError, TypeError)):
            h.id = 'b' * 64

    def test_malformed_success_output_is_reconciled_not_used_as_target(self):
        def dispatch(args):
            h = self.life.handles[0]
            if 'create' in args:
                return subprocess.CompletedProcess(args, *ok('PRIVATE malformed output'))
            return subprocess.CompletedProcess(args, *absent(h))
        self.life.runner = dispatch
        h = self.life.create('container', image='approved')
        self.assertIsNone(h.id)
        self.assertTrue(h.removed)
        self.assertNotIn('PRIVATE', repr(h))
        self.assertTrue(self.life.cleanup())

    def test_cleanup_continues_independent_resources_after_failure(self):
        first = self.container()
        second = self.container()
        self.runner.responses = [metadata(second), (1, '', 'PRIVATE'), metadata(first), ok(), absent(first)]
        self.assertFalse(self.life.cleanup())
        self.assertTrue(second.failed)
        self.assertTrue(first.removed)

    def test_network_and_volume_lifecycle_is_labelled_internal_and_exact(self):
        for kind in ('network', 'volume'):
            with self.subTest(kind=kind):
                self.setUp()
                def dispatch(args):
                    h = self.life.handles[0]
                    identity = h.name if kind == 'volume' else CID
                    if 'create' in args:
                        return subprocess.CompletedProcess(args, *ok(identity))
                    if 'inspect' in args:
                        if any('rm' in call for call in self.runner.calls):
                            text = f'get {identity}: no such volume' if kind == 'volume' else f'network {identity} not found'
                            return subprocess.CompletedProcess(args, 1, '', 'Error response from daemon: ' + text)
                        data = {'Id': identity, 'Name': h.name, 'Labels': {module.LABEL: h.owner}, 'Internal': True}
                        return subprocess.CompletedProcess(args, *ok(json.dumps([data])))
                    return subprocess.CompletedProcess(args, *ok())
                def runner(args):
                    self.runner.calls.append(args)
                    return dispatch(args)
                self.life.runner = runner
                h = self.life.create(kind)
                self.assertEqual(h.id, h.name if kind == 'volume' else CID)
                self.assertEqual('--internal' in self.runner.calls[0], kind == 'network')
                self.assertTrue(self.life.cleanup())
                self.assertIn([kind, 'rm', h.id], self.runner.calls)
                self.assertFalse(any('--force' in c or 'prune' in c for c in self.runner.calls))

    def test_container_accepts_only_owned_network_and_volume_and_loopback_ports(self):
        self.runner.responses = [ok(CID)]
        net = self.life.create('network')
        self.runner.responses = [ok('')]
        # Volume create returns its generated name, never an arbitrary supplied path.
        def volume_create(args):
            return subprocess.CompletedProcess(args, *ok(self.life.handles[-1].name))
        self.life.runner = volume_create
        vol = self.life.create('volume')
        self.life.runner = self.runner
        self.runner.responses = [ok(CID)]
        h = self.life.create('container', image='approved', network=net, volume=vol,
                             ports=((18080, 8080),), environment={'LOCAL_ONLY': 'test'})
        args = self.runner.calls[-1]
        self.assertIn(net.id, args)
        self.assertIn(f'type=volume,src={vol.id},dst=/var/lib/postgresql/data', args)
        self.assertIn('127.0.0.1:18080:8080', args)
        self.assertIn('LOCAL_ONLY=test', args)
        self.assertIn('--pull=never', args)
        self.assertEqual(h.owner, net.owner)
        foreign = module.Handle('network', net.name, 'foreign', id=net.id)
        calls = len(self.runner.calls)
        with self.assertRaises(ValueError):
            self.life.create('container', image='approved', network=foreign)
        self.assertEqual(len(self.runner.calls), calls)

    def test_stop_absence_after_running_does_not_target_replacement(self):
        h = self.container()
        self.runner.responses = [metadata(h, State={'Status': 'running'}), ok(), absent(h)]
        self.assertTrue(self.life.cleanup())
        self.assertTrue(h.removed)
        self.assertFalse(any('rm' in c for c in self.runner.calls))

    def test_nullable_and_invalid_inspect_documents_fail_closed(self):
        for text in ('null', '{}', '[null]', '[[]]', '[]', '[{}, {}]', 'not json'):
            with self.subTest(text=text):
                self.setUp()
                h = self.container()
                self.runner.responses = [ok(text)]
                self.assertFalse(self.life.cleanup())
                self.assertTrue(h.failed)
                self.assertEqual(len(self.runner.calls), 2)

    def test_public_stop_checks_ownership_and_stopped_state(self):
        h = self.container()
        self.runner.responses = [metadata(h, State={'Status': 'running'}), ok(), metadata(h, State={'Status': 'exited'})]
        self.assertTrue(self.life.stop(h))
        self.runner.responses = [metadata(h, Config=None)]
        self.assertFalse(self.life.stop(h))
        self.assertEqual(self.runner.calls[-1], ['container', 'inspect', CID])

    def test_real_inspect_absence_array_is_verified(self):
        h = self.container()
        self.runner.responses = [metadata(h), ok(), (1, '[]\n', f'Error response from daemon: No such container: {CID}\n')]
        self.assertTrue(self.life.cleanup())
        self.assertTrue(h.removed)

    def test_network_or_volume_foreign_metadata_blocks_cleanup(self):
        for kind in ('network', 'volume'):
            for changed in ('label', 'id', 'internal'):
                if kind == 'volume' and changed == 'internal':
                    continue
                with self.subTest(kind=kind, changed=changed):
                    self.setUp()
                    def runner(args):
                        self.runner.calls.append(args)
                        h = self.life.handles[0]
                        identity = h.name if kind == 'volume' else CID
                        if 'create' in args:
                            return subprocess.CompletedProcess(args, *ok(identity))
                        data = {'Id': identity, 'Name': h.name, 'Labels': {module.LABEL: h.owner}, 'Internal': True}
                        if changed == 'label':
                            data['Labels'] = None
                        elif changed == 'id':
                            data['Name' if kind == 'volume' else 'Id'] = 'foreign'
                        else:
                            data['Internal'] = False
                        return subprocess.CompletedProcess(args, *ok(json.dumps([data])))
                    self.life.runner = runner
                    h = self.life.create(kind)
                    self.assertFalse(self.life.cleanup())
                    self.assertTrue(h.failed)
                    self.assertEqual(len(self.runner.calls), 2)

    def test_post_stop_changed_image_prevents_removal(self):
        h = self.container()
        self.runner.responses = [metadata(h, State={'Status': 'running'}), ok(), metadata(h, Config={'Image': 'foreign', 'Labels': {module.LABEL: h.owner}})]
        self.assertFalse(self.life.cleanup())
        self.assertTrue(h.failed)
        self.assertFalse(any('rm' in c for c in self.runner.calls))

    def test_foreign_metadata_prevents_start(self):
        h = self.container()
        self.runner.responses = [metadata(h, Id='b' * 64)]
        self.assertFalse(self.life.start(h))
        self.assertFalse(any('start' in c for c in self.runner.calls))

    def test_container_defaults_to_no_network_and_rejects_unsafe_options(self):
        self.container()
        self.assertIn('none', self.runner.calls[0])
        for options in ({'image': '--privileged'}, {'image': 'has space'},
                        {'image': 'approved', 'ports': ((0, 8080),)},
                        {'image': 'approved', 'environment': {'BAD=KEY': 'x'}},
                        {'image': 'approved', 'volume': module.Handle('volume', '/home/user', 'foreign', id='/home/user')}):
            with self.subTest(options=options):
                calls = len(self.runner.calls)
                with self.assertRaises(ValueError):
                    self.life.create('container', **options)
                self.assertEqual(len(self.runner.calls), calls)

    def test_created_only_cleanup_verifies_absence_without_wait(self):
        h = self.container()
        self.runner.responses = [metadata(h), ok(), absent(h)]
        self.assertTrue(self.life.cleanup())
        self.assertTrue(h.removed)
        self.assertEqual(self.runner.calls[-2], ['container', 'rm', CID])
        self.assertFalse(any('wait' in c or 'stop' in c for c in self.runner.calls))

    def test_foreign_or_malformed_metadata_prevents_removal(self):
        for change in ({'Id': 'b' * 64}, {'Config': {'Image': 'foreign', 'Labels': {}}},
                       {'Config': {'Image': 'approved@sha256:test', 'Labels': {module.LABEL: 'foreign'}}},
                       {'Config': {'Image': 'foreign', 'Labels': None}}, {'Config': None},
                       {'State': None}, {'State': {'Status': 'mystery'}}, {'Config': []},
                       {'State': {'Status': None}}, {'Name': '/foreign'}):
            with self.subTest(change=change):
                self.setUp()
                h = self.container()
                self.runner.responses = [metadata(h, **change)]
                self.assertFalse(self.life.cleanup())
                self.assertTrue(h.failed)
                self.assertEqual(len(self.runner.calls), 2)

    def test_running_cleanup_stops_exact_id_then_rechecks(self):
        h = self.container()
        self.runner.responses = [metadata(h, State={'Status': 'running'}), ok(),
                                 metadata(h, State={'Status': 'exited'}), ok(), absent(h)]
        self.assertTrue(self.life.cleanup())
        self.assertIn(['container', 'stop', '--time', '10', CID], self.runner.calls)

    def test_start_verifies_ownership_and_observes_running(self):
        h = self.container()
        self.runner.responses = [metadata(h), ok(), metadata(h, State={'Status': 'running'})]
        self.assertTrue(self.life.start(h))
        self.assertIn(['container', 'start', CID], self.runner.calls)

    def test_cleanup_failure_is_terminal_and_does_not_leak_output(self):
        h = self.container()
        self.runner.responses = [metadata(h), (1, 'PRIVATE', 'PRIVATE')]
        self.assertFalse(self.life.cleanup())
        calls = len(self.runner.calls)
        self.assertFalse(self.life.cleanup())
        self.assertEqual(len(self.runner.calls), calls)
        self.assertNotIn('PRIVATE', repr(self.life.events))

    def test_failed_inspect_does_not_prove_absence(self):
        h = self.container()
        self.runner.responses = [metadata(h), ok(), (1, '', 'daemon unavailable')]
        self.assertFalse(self.life.cleanup())
        self.assertFalse(h.removed)

    def test_replacement_is_not_removed_by_name(self):
        h = self.container()
        self.runner.responses = [absent(h)]
        self.assertTrue(self.life.cleanup())
        self.assertEqual(self.runner.calls[-1], ['container', 'inspect', CID])
        self.assertFalse(any('rm' in c for c in self.runner.calls))


if __name__ == '__main__':
    unittest.main()
