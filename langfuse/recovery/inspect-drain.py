#!/usr/bin/env python3
"""Read-only sampled worker-queue and PostgreSQL in-flight prerequisites.

Prints bounded, allowlisted aggregates only. No receipt/file/export/pause writes.
An empty sample NEVER proves writer exclusion, client idleness or capture safety.
Queue source/layout is pinned to installed 4.77.0 code, not DBSIZE or job payloads.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('drain_native', HERE / 'inspect-native.py')
assert _spec and _spec.loader
native = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(native)
ProbeError = native.ProbeError
STATE_KEYS = {'wait', 'active', 'delayed', 'prioritized', 'paused', 'waiting-children',
              'repeat', 'stalled', 'failed', 'completed', 'paused_queues'}
TREE_HASHES = ['512594a1d7ecf650aa15b7364c41984ba05d99b3566d25207f30e421ac76272a',
               '4a1561fcdefc5dbd928535163416cb29fa64bb65b85bcbd2934857f1e6e02ca4',
               'd1529f2c9dc0d994a0899b3063bcd2102924fe0d30842f64136dfedf449cb13f']
# No query text, usernames, client addresses, transaction IDs or application
# names are selected. All same-database backends count, not just named clients.
# Visibility and prepared transactions are checked to avoid a false empty sample.
PG_IDLE_SQL = """SELECT
 current_setting('server_version_num'),
 CASE WHEN current_database()='langfuse' THEN 1 ELSE 0 END,
 CASE WHEN (SELECT rolsuper FROM pg_roles WHERE rolname=current_user)
   OR pg_has_role(current_user,'pg_read_all_stats','MEMBER') THEN 1 ELSE 0 END,
 count(*) FILTER (WHERE xact_start IS NOT NULL),
 count(*) FILTER (WHERE state='active'),
 count(*) FILTER (WHERE state IN ('idle in transaction','idle in transaction (aborted)')),
 count(*) FILTER (WHERE state IS NULL),
 (SELECT count(*) FROM pg_prepared_xacts WHERE database=current_database())
 FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()"""


def parse_pg(text):
    if not re.fullmatch(r'[0-9]{6}(?:\|[0-9]{1,15}){7}', text):
        raise ProbeError('postgres-inflight-format')
    version, db, visible, transactions, active, idle, unknown, prepared = map(int, text.split('|'))
    if not 180000 <= version < 190000 or db != 1 or visible != 1:
        raise ProbeError('postgres-inflight-visibility-not-admitted')
    if idle > transactions:
        raise ProbeError('postgres-inflight-contradiction')
    return {'inflight_transactions': transactions, 'active_backends': active,
            'idle_in_transaction_backends': idle, 'unknown_state_backends': unknown,
            'prepared_transactions': prepared,
            'sampled_no_inflight_work': not any([transactions, active, idle, unknown, prepared]),
            'full_statistics_visibility_verified': True}


def parse_queues(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProbeError('queue-duplicate-field')
            result[key] = value
        return result
    if len(text) > 4096:
        raise ProbeError('queue-summary-too-large')
    try:
        result = json.loads(text, object_pairs_hook=unique)
    except (ValueError, TypeError):
        raise ProbeError('queue-summary-not-json') from None
    expected = {'schema', 'queue_count', 'registry_sha256', 'source_tree_sha256', 'counts',
                'sampled_no_pending_work', 'writer_exclusion_verified',
                'client_idleness_verified', 'capture_ready'}
    if not isinstance(result, dict) or set(result) != expected:
        raise ProbeError('queue-summary-fields-not-admitted')
    if (type(result['schema']) is not int or result['schema'] != 1
            or type(result['queue_count']) is not int or not 46 <= result['queue_count'] <= 512
            or not isinstance(result['registry_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', result['registry_sha256'])
            or result['source_tree_sha256'] != TREE_HASHES
            or not isinstance(result['counts'], dict) or set(result['counts']) != STATE_KEYS):
        raise ProbeError('queue-summary-values-not-admitted')
    counts = result['counts']
    if any(type(n) is not int or not 0 <= n <= 9007199254740991 for n in counts.values()):
        raise ProbeError('queue-count-not-admitted')
    if counts['paused_queues'] > result['queue_count']:
        raise ProbeError('queue-paused-count-contradiction')
    empty = not any(n for k, n in counts.items() if k not in {'failed', 'completed'})
    if (type(result['sampled_no_pending_work']) is not bool
            or result['sampled_no_pending_work'] != empty
            or any(result[k] is not False for k in
                   ['writer_exclusion_verified', 'client_idleness_verified', 'capture_ready'])):
        raise ProbeError('queue-safety-claim-not-admitted')
    return result


def collect():
    before = native.probe_workloads()
    result = {}
    for name in ['queues', 'postgresql']:
        try:
            if name == 'queues':
                script = (HERE / 'inspect-drain-queues.js').read_text()
                worker = before['langfuse-worker']
                result[name] = parse_queues(native.execute(worker['name'], 'langfuse-worker',
                    ['node', '-e', script + '\nmain();']))
            else:
                pg = before['postgresql']
                result[name] = parse_pg(native.execute(pg['name'], 'postgresql',
                    ['/bin/sh', '-ec', native.PG_SHELL, 'recovery-drain-readonly', PG_IDLE_SQL]))
        except ProbeError as error:
            result[name] = {'status': 'blocked', 'reason': str(error)}
    if before != native.probe_workloads():
        raise ProbeError('workload-changed-during-drain-sample')
    return {'schema': 1, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'helper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'queue_helper_sha256': hashlib.sha256((HERE / 'inspect-drain-queues.js').read_bytes()).hexdigest(),
            'results': result, 'writer_exclusion_verified': False,
            'client_idleness_verified': False, 'capture_ready': False,
            'limitations': ['Worker-configured DB0/default BullMQ namespaces only; unknown namespace/type/config fails closed.',
                            'Atomic counts per queue, not across queues/stores; live writers can race every sample.',
                            'Legacy repeatables and modern schedulers share repeat count; any scheduled work blocks empty result.',
                            'Failed/completed retained jobs are reported, not pending work; failed-job disposition still requires review.',
                            'No writer exclusion, client-idle confirmation, export or capture acceptance.']}


def main():
    if len(sys.argv) != 1:
        print('Read-only drain probe accepts no arguments.', file=sys.stderr)
        return 2
    try:
        result = collect()
    except Exception:
        print('Read-only drain sample unavailable; no capture acceptance.', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if all('status' not in r for r in result['results'].values()) else 1


if __name__ == '__main__':
    sys.exit(main())
