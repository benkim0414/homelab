"""Fail-closed aggregate drain checks; fixtures contain no application records."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'langfuse/recovery/inspect-drain.py'
JS = HELPER.with_name('inspect-drain-queues.js')
spec = importlib.util.spec_from_file_location('recovery_drain_tested', HELPER)
assert spec and spec.loader
drain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drain)


def summary():
    return {'schema': 1, 'queue_count': 46, 'registry_sha256': 'a' * 64,
            'source_tree_sha256': drain.TREE_HASHES[:],
            'counts': dict.fromkeys(drain.STATE_KEYS, 0),
            'sampled_no_pending_work': True, 'writer_exclusion_verified': False,
            'client_idleness_verified': False, 'capture_ready': False}


class QueueParser(unittest.TestCase):
    def parse(self, value):
        return drain.parse_queues(json.dumps(value))

    def test_empty_is_sample_only(self):
        value = self.parse(summary())
        self.assertTrue(value['sampled_no_pending_work'])
        for k in ['writer_exclusion_verified', 'client_idleness_verified', 'capture_ready']:
            self.assertFalse(value[k])

    def test_every_nonterminal_state_blocks_including_repeat_and_pause(self):
        for state in drain.STATE_KEYS - {'completed', 'failed'}:
            with self.subTest(state=state):
                value = summary()
                value['counts'][state] = 1
                with self.assertRaises(drain.ProbeError):
                    self.parse(value)  # Contradictory empty claim.
                value['sampled_no_pending_work'] = False
                self.assertFalse(self.parse(value)['sampled_no_pending_work'])

    def test_retained_terminal_jobs_reported_not_pending(self):
        value = summary()
        value['counts'].update(completed=7, failed=3)
        self.assertTrue(self.parse(value)['sampled_no_pending_work'])

    def test_counts_schema_and_claims_fail_closed(self):
        mutations = [lambda v: v.update(queue_count=45),
                     lambda v: v.update(schema=True),
                     lambda v: v.update(registry_sha256='payload'),
                     lambda v: v.update(source_tree_sha256=['a' * 64]),
                     lambda v: v.update(capture_ready=True),
                     lambda v: v.update(writer_exclusion_verified=0),
                     lambda v: v.update(client_idleness_verified=True),
                     lambda v: v.update(payload='not-allowed'),
                     lambda v: v['counts'].update(extra=0),
                     lambda v: v['counts'].pop('repeat'),
                     lambda v: v['counts'].update(active=True),
                     lambda v: v['counts'].update(active=1.0),
                     lambda v: v['counts'].update(active=-1),
                     lambda v: v['counts'].update(active=9007199254740992),
                     lambda v: v['counts'].update(paused_queues=47)]
        for mutate in mutations:
            value = summary()
            mutate(value)
            with self.assertRaises(drain.ProbeError):
                self.parse(value)

    def test_duplicates_malformed_and_oversize(self):
        for text in ['{}', 'null', '[]', '{"schema":1,"schema":1}', 'private-error', ' ' * 4097]:
            with self.assertRaises(drain.ProbeError):
                drain.parse_queues(text)


class PostgresParser(unittest.TestCase):
    def test_empty_sample_excludes_probe_not_writer_claim(self):
        result = drain.parse_pg('180001|1|1|0|0|0|0|0')
        self.assertTrue(result['sampled_no_inflight_work'])
        self.assertNotIn('writer_exclusion_verified', result)
        self.assertIn('pid<>pg_backend_pid()', drain.PG_IDLE_SQL)
        self.assertNotIn('query,', drain.PG_IDLE_SQL)

    def test_transactions_active_prepared_and_unknown_block(self):
        for fields in [[1, 0, 1, 0, 0], [1, 1, 0, 0, 0], [0, 0, 0, 1, 0], [0, 0, 0, 0, 1]]:
            text = '180001|1|1|' + '|'.join(map(str, fields))
            self.assertFalse(drain.parse_pg(text)['sampled_no_inflight_work'])

    def test_wrong_database_visibility_format_or_contradiction(self):
        for text in ['180001|0|1|0|0|0|0|0', '180001|1|0|0|0|0|0|0',
                     '170001|1|1|0|0|0|0|0', '180001|1|1|0|0|1|0|0',
                     '180001|1|1|-1|0|0|0|0', '180001|1|1|0|0|0|0|0\nprivate']:
            with self.assertRaises(drain.ProbeError):
                drain.parse_pg(text)


class JavascriptProbe(unittest.TestCase):
    def node(self, code):
        script = 'const p=require(' + json.dumps(str(JS)) + '); const a=require("assert");\n' + code
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=15, cwd=ROOT)
        self.assertEqual(result.returncode, 0, 'JS fixture assertion failed (raw diagnostics withheld)')
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')

    def test_fixed_destination_auth_and_unknown_configuration(self):
        self.node('''
const env={REDIS_CONNECTION_STRING:'redis://default:synthetic@langfuse-redis:6379/0'};
const o=p.options(env);a.strictEqual(o.db,0);a.strictEqual(o.password,'synthetic');
a.strictEqual(o.enableOfflineQueue,false);a.strictEqual(o.maxRetriesPerRequest,0);
// App factory uses URL auth, not an unrelated password override.
a.strictEqual(p.options({...env,REDIS_PASSWORD:'different'}).password,'synthetic');
for(const url of ['redis://default:x@elsewhere/0','redis://default:x@langfuse-redis/1',
'rediss://default:x@langfuse-redis/0','redis://default:x@langfuse-redis/0?db=1',
'redis://other:x@langfuse-redis/0','redis://langfuse-redis/0'])
 a.throws(()=>p.options({...env,REDIS_CONNECTION_STRING:url}));
for(const field of ['REDIS_KEY_PREFIX','REDIS_TLS_ENABLED','REDIS_CLUSTER_ENABLED','REDIS_SENTINEL_ENABLED',
'LANGFUSE_UNKNOWN_QUEUE_SHARD_COUNT']) a.throws(()=>p.options({...env,[field]:'true'}));
''')

    def test_registry_unknown_malformed_and_same_size_substitution(self):
        self.node('''
a.throws(()=>p.registry('',{}));
const block=Array.from({length:46},(_,i)=>`QueueName["Synthetic${i}"] = "synthetic-${i}";`).join('\\n');
a.throws(()=>p.registry('var QueueName; (function (QueueName) {'+block+'})(QueueName',{}));
a.throws(()=>p.registry('var QueueName; (function (QueueName) {'+block+'unsafe();})(QueueName',{}));
''')

    def test_native_commands_only_aggregates_and_unknown_reply_types(self):
        self.node('''
(async()=>{
let calls=0;
const client={call:async(cmd,lua,n,...args)=>{calls++;a.strictEqual(cmd,'EVAL_RO');
a.strictEqual(lua,p.COUNT_LUA);a.strictEqual(n,11);a.strictEqual(args.length,21);
return [1,2,3,4,5,6,7,8,9,10,1];}};
const c=await p.counts(client,['synthetic-a','synthetic-b']);a.strictEqual(calls,2);
a.strictEqual(c.wait,2);a.strictEqual(c.repeat,14);a.strictEqual(c.paused_queues,2);
for(const reply of [[-1],Array(11).fill(-1),Array(11).fill(true),Array(11).fill(1.5),
Array(11).fill('0'),Array(11).fill(9007199254740992)])
 await a.rejects(p.counts({call:async()=>reply},['synthetic']));
for(const forbidden of ['RPOP','LPOP','HGETALL','LRANGE','ZRANGE','SET','DEL','DBSIZE'])
 a.ok(!p.COUNT_LUA.includes("'"+forbidden+"'"));
})().catch(()=>process.exitCode=1);
''')

    def test_namespace_scan_is_bounded_and_rejects_unknown(self):
        self.node('''
(async()=>{
await p.checkNamespaces({scan:async()=>['0',['bull:synthetic:wait','bull:synthetic:job-id']]},['synthetic']);
await a.rejects(p.checkNamespaces({scan:async()=>['0',['bull:unknown:wait']]},['synthetic']));
await a.rejects(p.checkNamespaces({scan:async()=>['1',[]]},['synthetic']));
await a.rejects(p.checkNamespaces({scan:async()=>['0',Array(32769).fill('bull:synthetic:wait')]},['synthetic']));
})().catch(()=>process.exitCode=1);
''')

    def test_no_application_import_or_mutating_bullmq_api(self):
        source = JS.read_text()
        self.assertNotIn('new Queue(', source)
        self.assertNotIn('require("@langfuse/shared")', source)
        self.assertNotIn('require("bullmq")', source)
        self.assertIn('treeHash(r)', source)
        self.assertIn('"5.76.3"', source)
        self.assertIn('"5.10.1"', source)
        self.assertIn('client.disconnect()', source)


class CollectionSafety(unittest.TestCase):
    def test_workload_change_invalidates_complete_sample(self):
        rows = {'langfuse-worker': {'name': 'synthetic-worker'}, 'postgresql': {'name': 'synthetic-pg'}}
        with mock.patch.object(drain.native, 'probe_workloads', side_effect=[rows, {}]), \
                mock.patch.object(drain.native, 'execute', side_effect=[json.dumps(summary()), '180001|1|1|0|0|0|0|0']):
            with self.assertRaises(drain.ProbeError):
                drain.collect()

    def test_native_failure_is_blocked_never_empty_success(self):
        rows = {'langfuse-worker': {'name': 'synthetic-worker'}, 'postgresql': {'name': 'synthetic-pg'}}
        with mock.patch.object(drain.native, 'probe_workloads', return_value=rows), \
                mock.patch.object(drain.native, 'execute', side_effect=drain.ProbeError('native-probe-failed')):
            result = drain.collect()
        self.assertFalse(result['capture_ready'])
        self.assertTrue(all(v['status'] == 'blocked' for v in result['results'].values()))


if __name__ == '__main__':
    unittest.main()
