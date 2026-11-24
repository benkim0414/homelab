#!/usr/bin/env python3
"""Fixed first Langfuse restore preparation. No live-write CLI.

--render exclusively writes a review bundle beneath this worktree's ignored cache.
--admit performs ONLY metadata reads (never Secrets, env values or logs).
The bundle contains real target-only native commands, not authorization to run them.
Confidential archive transport and original six-Secret reconstruction belong to
an operator-private runner. Never run kubectl apply on the entire bundle: it is
NOT a Kubernetes List. Only bundle['resources'] are Kubernetes resources.

Sequence: fresh namespace/policies/claims -> privately restore original identity
-> create held Pods -> verify fresh CSI handles/replicas and archive hashes ->
stream fully validated archives to fixed paths -> start stores -> reconcile SW
metadata while loader stdin remains open -> cold restart/recheck SW -> native
inventories/queue/migration reconciliation -> start app -> private API/UI tests.
No cleanup, retry, schedule, migration, bootstrap or production operation exists.
"""
import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import importlib.util
import selectors
import signal
import stat
import struct
import gzip
import time
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'verification/cache/langfuse-recovery'
NAMESPACE = 'langfuse-recovery-first-20261120'
IDENTITY = 'identity-20261121-bb5b26c1e5c64dd9be271473f8be74be'
CLAIMS = {'postgresql': '10Gi', 'clickhouse': '30Gi', 'valkey': '5Gi', 'seaweedfs': '20Gi'}
SOURCE_UIDS = {'dbfbc0a0-97e4-4d3d-b6ae-e4d9c581ea7f', 'e82ce5a4-cd40-4353-a02a-d54a3d96203b',
               'd8f49983-f38d-4de2-8651-283d16a732b4', '26a2ea71-3030-4d2d-b894-b8f8cf5627f9'}
IMAGES = {
 'postgresql': 'postgres:18@sha256:2ea8630df176ad090ec92136dee850397c5af8781e4bcf2e4162593691c61bbc',
 'clickhouse': 'clickhouse/clickhouse-server:26.8.36.3@sha256:d426d2f612e1e189c90f9a3f8dcd85a03c6851273833817a296bb327e63aa7a7',
 'valkey': 'valkey/valkey:8.0@sha256:04b9002ae24bbe66687fb025052ed9bcebb54f8da3937338eb718d98d362887f',
 'seaweedfs': 'chrislusf/seaweedfs:4.23@sha256:c6d6fb84b081f1f09bb089184ff4b45d2f163a1bfa8b354d04cf400c6e06f242',
 'web': 'docker.langfuse.com/langfuse/langfuse:4.77.0@sha256:2b47d0ae63ae737996a58cc03536a73230c809a2371c230c9bea4b7653a0b6a0',
 'worker': 'docker.langfuse.com/langfuse/langfuse-worker:4.77.0@sha256:1bc3597ff4c953e98ff9ee474a7d634e97664e4df298fdf20f13ecc834c89438'}
# Requests/limits match production. No lower limits to force request admission.
PLACEMENT = {'postgresql': ('k3s-01', 'arm64', 999, '250m', '512Mi', '1', '1Gi'),
 'clickhouse': ('k3s-04', 'arm64', 101, '500m', '2Gi', '2', '4Gi'),
 'valkey': ('k3s-01', 'arm64', 1000, '100m', '256Mi', '1', '768Mi'),
 'seaweedfs': ('k3s-01', 'arm64', 10000, '250m', '512Mi', '2', '2Gi'),
 'web': ('k3s-05', 'amd64', 1001, '250m', '1Gi', '2', '2Gi'),
 'worker': ('k3s-05', 'amd64', 1001, '250m', '1Gi', '2', '2Gi')}
SECRET_KEYS = {'langfuse-app-credentials': {'salt', 'encryption-key', 'nextauth-secret'},
 'langfuse-bootstrap': {'email', 'password'}, 'langfuse-clickhouse-auth': {'password'},
 'langfuse-postgresql-auth': {'POSTGRES_DB', 'POSTGRES_PASSWORD', 'POSTGRES_USER', 'USERDB_PASSWORD', 'USERDB_USER'},
 'langfuse-redis-auth': {'default'}, 'langfuse-s3-auth': {'accessKey', 'secretKey', 'seaweedfs_s3_config'}}


class Refused(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise Refused(reason)


def ref(name, secret, key):
    return {'name': name, 'valueFrom': {'secretKeyRef': {'name': secret, 'key': key}}}


def obj(kind, name, spec=None, **fields):
    result = {'apiVersion': 'networking.k8s.io/v1' if kind == 'NetworkPolicy' else 'v1',
              'kind': kind, 'metadata': {'name': name, 'namespace': NAMESPACE}, **fields}
    if spec is not None:
        result['spec'] = spec
    return result


# Scripts run only in the disposable target. Native diagnostics never reach logs.
# Held Pods have a separate staging deadline; store startup happens only after
# validated native inputs have been transported and target volume admission passes.
HOLD = '''set +x; set -eu; umask 077
exec >/dev/null 2>&1
for i in $(seq 1 1800); do
 if test -f /restore/start; then exec /bin/sh /scripts/run.sh; fi
 sleep 2
done
exit 1
'''
PG = r'''set +x; set -eu; umask 077
export PATH=/usr/lib/postgresql/18/bin:$PATH
export PGDATA=/data/pgdata
# Exclusive creation is intentional: a failed attempt is never reset/retried.
test ! -e "$PGDATA"; mkdir -m 700 "$PGDATA"
pg_restore --file=/dev/null /restore/database.dump
initdb -D "$PGDATA" --username=restore_admin --auth-local=trust --auth-host=scram-sha-256 --no-locale >/restore/init.private 2>&1
# Fixed web/worker node Pod CIDR, original role/DB and SCRAM only. The target
# namespace NetworkPolicy is a separate mandatory source-namespace restriction.
printf 'host langfuse langfuse 10.42.4.0/24 scram-sha-256\n' >> "$PGDATA/pg_hba.conf"
pg_ctl -D "$PGDATA" -l /restore/postgres.private -o "-k /restore -c listen_addresses=''" -w start
trap 'pg_ctl -D "$PGDATA" -m fast -w stop >/dev/null 2>&1 || true' EXIT
psql -X -h /restore -U restore_admin -d postgres -v ON_ERROR_STOP=1 -f /restore/globals.sql >/restore/globals.private 2>&1
pg_restore -h /restore -U restore_admin -d postgres --create --exit-on-error /restore/database.dump >/restore/restore.private 2>&1
# Globals intentionally omit role passwords. Restore original auth in-container,
# using psql variables, not literal passwords in argv/logs or a new identity.
psql -X -h /restore -U restore_admin -d postgres -v ON_ERROR_STOP=1 >/dev/null 2>&1 <<'SQL'
\getenv admin_password POSTGRES_PASSWORD
\getenv user_password USERDB_PASSWORD
ALTER ROLE postgres PASSWORD :'admin_password';
ALTER ROLE langfuse PASSWORD :'user_password';
SQL
pg_amcheck -h /restore -U restore_admin -d langfuse --install-missing >/restore/amcheck.private 2>&1
pg_ctl -D "$PGDATA" -m fast -w stop
trap - EXIT
touch /restore/native-restored
exec postgres -D "$PGDATA" -k /restore -c listen_addresses=0.0.0.0
'''
VK = r'''set +x; set -eu; umask 077
test ! -e /data/appendonlydir
# Input tar must first pass validate_valkey_archive. Extract only dependencies.
mkdir -m 700 /restore/unpacked
tar -xf /restore/checkpoint.tar -C /restore/unpacked
(cd /restore/unpacked; sha256sum -c SHA256SUMS >/dev/null)
valkey-check-aof /restore/unpacked/appendonlydir/appendonly.aof.manifest >/restore/check.private 2>&1
# Never --fix. No RDB-only fallback.
cp -R /restore/unpacked/appendonlydir /data/appendonlydir
# ACL input is constructed privately from original identity, never exposed.
password_hash=$(printf %s "$REDISCLI_AUTH" | sha256sum | cut -d ' ' -f 1)
printf 'user default on #%s ~* &* +@all\n' "$password_hash" > /restore/users.acl
printf 'dir /data\nappendonly yes\nappenddirname appendonlydir\nappendfilename appendonly.aof\nmaxmemory 384mb\nmaxmemory-policy noeviction\naclfile /restore/users.acl\nbind 0.0.0.0\n' > /restore/valkey.conf
touch /restore/native-restored
exec valkey-server /restore/valkey.conf
'''
CH = r'''set +x; set -eu; umask 077
test ! -e /var/lib/clickhouse/.first-restore-started
touch /var/lib/clickhouse/.first-restore-started
mkdir -p /var/lib/clickhouse/backups
cp /restore/native.tar /var/lib/clickhouse/backups/first.tar
# Original pinned entrypoint creates config-managed langfuse identity from env,
# not a new SQL user. No Langfuse app/migrations are running at this point.
unset CLICKHOUSE_DB
/entrypoint.sh >/restore/server.private 2>&1 & server=$!
trap 'kill -TERM "$server" 2>/dev/null || true; wait "$server" || true' EXIT
trap 'exit 0' TERM INT HUP
cli() { clickhouse client --host=127.0.0.1 --port=9000 --query "$1"; }
ready=0
for i in $(seq 1 150); do
 kill -0 "$server"
 if cli 'SELECT 1' >/dev/null 2>&1; then ready=1; break; fi
 sleep 2
done
test "$ready" = 1
test "$(cli 'SELECT version()')" = 26.8.36.3
count=$(cli "SELECT count() FROM system.tables WHERE database='default'")
test "$count" = 0
status=$(cli "RESTORE DATABASE default FROM File('first.tar')")
case "$status" in *"$(printf '\t')RESTORED") ;; *) exit 1;; esac
touch /restore/native-restored
wait "$server"
'''
SW = r'''set +x; set -eu; umask 077
cd /data
test ! -e /data/.first-restore-started; touch /data/.first-restore-started
# All exported native .dat/.idx/.vif files, including historical log volumes.
# Parent must first pass validate_seaweed_archive against coordinated admission.
mkdir -m 700 /restore/unpacked
tar -xf /restore/native.tar -C /restore/unpacked
for p in /restore/unpacked/volumes/*; do test -f "$p"; cp "$p" /data/; done
/usr/bin/weed -v=1 server -dir=/data -master -volume -ip="$POD_IP" -ip.bind=0.0.0.0 -master.port=9333 -master.defaultReplication=000 -master.volumeSizeLimitMB=1024 -volume.max=16 -volume.port=8080 -filer -filer.port=8888 -s3 -s3.port=8333 -s3.config=/etc/sw/s3/seaweedfs_s3_config >/restore/server.private 2>&1 & server=$!
trap 'kill -TERM "$server" 2>/dev/null || true; wait "$server" || true' EXIT
trap 'exit 0' TERM INT HUP
ready=0
for i in $(seq 1 150); do
 kill -0 "$server"
 if wget -q -T 2 --spider http://127.0.0.1:8888/; then ready=1; break; fi
 sleep 2
done
test "$ready" = 1
mkfifo -m 600 /restore/loader.in
exec 3<>/restore/loader.in
/usr/bin/weed shell -master=127.0.0.1:9333 -filer=127.0.0.1:8888 </restore/loader.in 3>&- >/restore/loader.private 2>&1 & loader=$!
printf '%s\n' "$loader" > /restore/loader.pid
printf 'fs.meta.load -v=false /restore/unpacked/filer-before.meta.gz\n' >&3
# External metadata/object verifier must observe THIS live loader, compare the
# complete exported application metadata and authenticated S3 bytes, then signal.
reconciled=0
for i in $(seq 1 150); do
 kill -0 "$server"; kill -0 "$loader"
 if test -f /restore/metadata-reconciled; then reconciled=1; break; fi
 sleep 2
done
test "$reconciled" = 1
# Close writer FD only after external reconciliation, then allow native EOF.
exec 3>&-
# FIFO fd opened read-write above requires closing the read end in shell too;
# loader has only its read fd, so it now sees EOF.
wait "$loader"
! grep -qi 'error:' /restore/loader.private
kill -TERM "$server"; wait "$server"
trap - EXIT
# A cold restart of the SAME isolated data, never reseed/reload the metadata.
touch /restore/native-restored
exec /usr/bin/weed -v=1 server -dir=/data -master -volume -ip="$POD_IP" -ip.bind=0.0.0.0 -master.port=9333 -master.defaultReplication=000 -master.volumeSizeLimitMB=1024 -volume.max=16 -volume.port=8080 -filer -filer.port=8888 -s3 -s3.port=8333 -s3.config=/etc/sw/s3/seaweedfs_s3_config
'''
APP = r'''set +x; set -eu; umask 077
# No init/bootstrap variables. No migration/cleanup entrypoint.
# Encode password safely without exposing it in a shell command argument.
exec node -e '
const {spawn}=require("child_process");
const e=process.env;
if(!e.RECOVERY_DB_PASSWORD||!e.REDIS_AUTH)process.exit(1);
e.DATABASE_URL=["postgresql:/","/langfuse:",encodeURIComponent(e.RECOVERY_DB_PASSWORD),"@recovery-postgresql:5432/langfuse"].join("");
e.DIRECT_URL=e.DATABASE_URL;
e.REDIS_CONNECTION_STRING=["redis:/","/default:",encodeURIComponent(e.REDIS_AUTH),"@recovery-valkey:6379/0"].join("");
const args=e.RECOVERY_COMPONENT==="web" ? ["./web/server.js","--keepAliveTimeout","110000"] : ["worker/dist/index.js"];
const p=spawn("node",args,{env:e,stdio:"inherit"});
for(const s of ["SIGTERM","SIGINT"])process.on(s,()=>p.kill(s));
p.on("exit",(c)=>process.exit(c===null?1:c));
'
'''
SCRIPTS = {'postgresql': PG, 'clickhouse': CH, 'valkey': VK, 'seaweedfs': SW, 'web': APP, 'worker': APP}


def identity_resources(snapshot):
    """PRIVATE in-memory adapter for the approved decrypted List, never a CLI.

    Caller must authenticate ciphertext/hash and source resourceVersions against
    the coordinated capture first. Returned objects contain original confidential
    data: pipe directly into namespace-scoped create; NEVER print/save/log them.
    Bootstrap credentials are retained for identity completeness but never used
    by any Pod; no reseeding variables or bootstrap Jobs exist.
    """
    try:
        need(snapshot.get('kind') == 'List' and snapshot.get('apiVersion') == 'v1', 'identity-list-schema')
        items = snapshot['items']; names = [s['metadata']['name'] for s in items]
        need(len(names) == 6 and set(names) == set(SECRET_KEYS), 'identity-name-set')
        result = []
        for source in items:
            name = source['metadata']['name']
            need(source['kind'] == 'Secret' and source['apiVersion'] == 'v1'
                 and source['metadata']['namespace'] == 'langfuse' and source['type'] == 'Opaque'
                 and set(source['data']) == SECRET_KEYS[name], 'identity-object-schema')
            for value in source['data'].values():
                need(isinstance(value,str) and len(base64.b64decode(value,validate=True)) > 0, 'identity-data-schema')
            result.append(obj('Secret',name,type='Opaque',data=dict(source['data'])))
        return result
    except Refused:
        raise
    except (KeyError,TypeError,ValueError,binascii.Error):
        raise Refused('identity-invalid') from None


def app_env(component):
    values = {'RECOVERY_COMPONENT': component, 'NODE_ENV': 'production', 'HOSTNAME': '0.0.0.0', 'PORT': '3000',
      'NEXTAUTH_URL': 'http://127.0.0.1:3300', 'TELEMETRY_ENABLED': 'false', 'AUTH_DISABLE_SIGNUP': 'true',
      'LANGFUSE_AUTO_POSTGRES_MIGRATION_DISABLED': 'true', 'LANGFUSE_AUTO_CLICKHOUSE_MIGRATION_DISABLED': 'true',
      'CLICKHOUSE_URL': 'http://recovery-clickhouse:8123', 'CLICKHOUSE_MIGRATION_URL': 'clickhouse://recovery-clickhouse:9000',
      'CLICKHOUSE_USER': 'langfuse', 'CLICKHOUSE_DB': 'default', 'CLICKHOUSE_CLUSTER_ENABLED': 'false',
      'REDIS_HOST': 'recovery-valkey', 'REDIS_PORT': '6379', 'REDIS_USERNAME': 'default',
      'LANGFUSE_S3_EVENT_UPLOAD_BUCKET': 'langfuse', 'LANGFUSE_S3_EVENT_UPLOAD_PREFIX': 'events/',
      'LANGFUSE_S3_EVENT_UPLOAD_REGION': 'auto', 'LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT': 'http://recovery-seaweedfs:8333',
      'LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE': 'true',
      'LANGFUSE_S3_MEDIA_UPLOAD_BUCKET': 'langfuse', 'LANGFUSE_S3_MEDIA_UPLOAD_REGION': 'auto',
      'LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT': 'http://recovery-seaweedfs:8333',
      'LANGFUSE_S3_MEDIA_UPLOAD_FORCE_PATH_STYLE': 'true', 'LANGFUSE_S3_BATCH_EXPORT_ENABLED': 'false'}
    env = [{'name': k, 'value': v} for k, v in values.items()]
    for name, secret, key in [('RECOVERY_DB_PASSWORD','langfuse-postgresql-auth','USERDB_PASSWORD'),
      ('SALT','langfuse-app-credentials','salt'), ('ENCRYPTION_KEY','langfuse-app-credentials','encryption-key'),
      ('NEXTAUTH_SECRET','langfuse-app-credentials','nextauth-secret'),
      ('CLICKHOUSE_PASSWORD','langfuse-clickhouse-auth','password'), ('REDIS_AUTH','langfuse-redis-auth','default')]:
        env.append(ref(name, secret, key))
    for scope in ('EVENT', 'MEDIA'):
        env += [ref('LANGFUSE_S3_'+scope+'_UPLOAD_ACCESS_KEY_ID','langfuse-s3-auth','accessKey'),
                ref('LANGFUSE_S3_'+scope+'_UPLOAD_SECRET_ACCESS_KEY','langfuse-s3-auth','secretKey')]
    return env


def resources():
    ns = obj('Namespace', NAMESPACE)
    ns['metadata'] = {'name': NAMESPACE, 'labels': {'pod-security.kubernetes.io/enforce': 'restricted'}}
    result = [ns, obj('NetworkPolicy', 'deny-all', {'podSelector': {}, 'policyTypes': ['Ingress','Egress']})]
    # Namespace AND Pod selectors in the same peer (not OR peers).
    peer = {'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': NAMESPACE}},
            'podSelector': {'matchLabels': {'recovery': 'first-20261120'}}}
    result += [obj('NetworkPolicy','target-only', {'podSelector': {'matchLabels': {'recovery': 'first-20261120'}},
        'policyTypes': ['Ingress','Egress'], 'ingress': [{'from': [peer]}], 'egress': [{'to': [peer]},
        {'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'kube-system'}},
                 'podSelector': {'matchLabels': {'k8s-app': 'kube-dns'}}}],
         'ports': [{'protocol': p, 'port': 53} for p in ('TCP','UDP')]}]})]
    for component, size in CLAIMS.items():
        result.append(obj('PersistentVolumeClaim','recovery-'+component, {'accessModes': ['ReadWriteOnce'],
          'storageClassName': 'longhorn', 'resources': {'requests': {'storage': size}}}))
    for component, script in SCRIPTS.items():
        result.append(obj('ConfigMap', 'recovery-'+component+'-scripts', data={'run.sh': script}))
        node, arch, uid, cpu, memory, cpu_limit, memory_limit = PLACEMENT[component]
        mount = {'postgresql':'/data', 'valkey':'/data', 'seaweedfs':'/data', 'clickhouse':'/var/lib/clickhouse'}
        volumes = [{'name': 'restore', 'emptyDir': {'sizeLimit': '4Gi'}},
          {'name': 'scripts', 'configMap': {'name': 'recovery-'+component+'-scripts'}}]
        mounts = [{'name':'restore','mountPath':'/restore'}, {'name':'scripts','mountPath':'/scripts','readOnly':True}]
        if component in CLAIMS:
            volumes.append({'name':'data','persistentVolumeClaim':{'claimName':'recovery-'+component}})
            mounts.append({'name':'data','mountPath':mount[component]})
        env = []
        if component in ('web','worker'):
            env = app_env(component)
        elif component == 'postgresql':
            env = [ref(k,'langfuse-postgresql-auth',k) for k in ('POSTGRES_PASSWORD','USERDB_PASSWORD')]
        elif component == 'valkey':
            env = [ref('REDISCLI_AUTH','langfuse-redis-auth','default')]
        elif component == 'clickhouse':
            env = [{'name':'CLICKHOUSE_USER','value':'langfuse'}, {'name':'CLICKHOUSE_DB','value':'default'},
              {'name':'CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT','value':'1'}, ref('CLICKHOUSE_PASSWORD','langfuse-clickhouse-auth','password')]
        elif component == 'seaweedfs':
            env = [{'name':'POD_IP','valueFrom':{'fieldRef':{'fieldPath':'status.podIP'}}}]
            volumes += [{'name':'config','configMap':{'name':'recovery-seaweedfs-config'}},
              {'name':'s3-auth','secret':{'secretName':'langfuse-s3-auth', 'items':[{'key':'seaweedfs_s3_config','path':'seaweedfs_s3_config'}]}}]
            mounts += [{'name':'config','mountPath':'/etc/seaweedfs','readOnly':True},
              {'name':'s3-auth','mountPath':'/etc/sw/s3','readOnly':True}]
        container = {'name':component,'image':IMAGES[component], 'imagePullPolicy':'IfNotPresent',
          'command':['/bin/sh','-ec',HOLD], 'env':env, 'volumeMounts':mounts,
          'securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}},
          'resources':{'requests':{'cpu':cpu,'memory':memory,'ephemeral-storage':'4Gi'},
                       'limits':{'cpu':cpu_limit,'memory':memory_limit,'ephemeral-storage':'5Gi'}}}
        if component in ('web','worker'):
            container['workingDir'] = '/app'
        result.append(obj('Pod','recovery-'+component, {'restartPolicy':'Never', 'enableServiceLinks':False,
          'automountServiceAccountToken':False, 'terminationGracePeriodSeconds':60,
          'nodeSelector':{'kubernetes.io/hostname':node,'kubernetes.io/arch':arch},
          'securityContext':{'runAsNonRoot':True,'runAsUser':uid,'runAsGroup':uid,'fsGroup':uid,
                             'seccompProfile':{'type':'RuntimeDefault'}}, 'volumes':volumes,'containers':[container]}))
        result[-1]['metadata']['labels'] = {'recovery':'first-20261120','component':component}
        ports = {'postgresql':[5432], 'clickhouse':[8123,9000], 'valkey':[6379],
                 'seaweedfs':[8333,9333,19333,8888,18888,8080], 'web':[3000], 'worker':[]}[component]
        if ports:
            result.append(obj('Service','recovery-'+component, {'type':'ClusterIP',
              'selector':{'recovery':'first-20261120','component':component},
              'ports':[{'name':'p'+str(p),'port':p,'targetPort':p} for p in ports]}))
    result.append(obj('ConfigMap','recovery-seaweedfs-config', data={'filer.toml':'[leveldb2]\nenabled = true\ndir = "/data/filerldb2"\n'}))
    return result


def target_exec(component, argv, stdin=False):
    need(component in SCRIPTS, 'component-not-fixed')
    return ['kubectl','--request-timeout=30s','-n',NAMESPACE,'exec'] + (['-i'] if stdin else []) + [
      'recovery-'+component,'-c',component,'--',*argv]


def commands():
    # argv arrays only: runner controls confidential stdin/stdout, never shell
    # interpolation, local plaintext paths, secret literals or production targets.
    output = {}
    paths = {'postgresql':['database.dump','globals.sql'],'clickhouse':['native.tar'],
             'valkey':['checkpoint.tar'],'seaweedfs':['native.tar']}
    for component in SCRIPTS:
        entries: dict[str, object] = {'start_after_admission': target_exec(component,['/bin/sh','-ec','test ! -e /restore/start; umask 077; touch /restore/start']),
                   'native_marker': target_exec(component,['test','-f','/restore/native-restored'])} if component in CLAIMS else {
                     'start_after_native_acceptance':target_exec(component,['/bin/sh','-ec','test ! -e /restore/start; umask 077; touch /restore/start'])}
        if component in paths:
            entries['receive_validated_private_streams'] = {path:target_exec(component,['/bin/sh','-ec',
              'set +x; set -eu; umask 077; set -C; cat > /restore/'+path],stdin=True) for path in paths[component]}
            entries['readback_stream_hashes'] = target_exec(component,['sha256sum',*['/restore/'+p for p in paths[component]]])
        output[component] = entries
    output['postgresql']['integrity'] = target_exec('postgresql',['/bin/sh','-ec',
      'set -eu; exec 2>/dev/null; pg_amcheck -h /restore -U restore_admin -d langfuse >/dev/null; printf "POSTGRES_INTEGRITY_OK\\n"'])
    output['postgresql']['migrations'] = target_exec('postgresql',['psql','-XAt','-h','/restore','-U','restore_admin','-d','langfuse',
      '-v','ON_ERROR_STOP=1','-c','SELECT count(*), count(*) FILTER (WHERE finished_at IS NULL AND rolled_back_at IS NULL) FROM public._prisma_migrations'])
    output['clickhouse']['migrations'] = target_exec('clickhouse',['clickhouse','client','--host=127.0.0.1','--readonly=1','--query',
      'SELECT version,dirty FROM default.schema_migrations ORDER BY sequence DESC LIMIT 1 FORMAT TSV'])
    output['valkey']['integrity'] = target_exec('valkey',['/bin/sh','-ec',
      'set -eu; exec 2>/dev/null; test "$(valkey-cli -e --raw -h 127.0.0.1 PING)" = PONG; valkey-cli -e --raw -h 127.0.0.1 INFO persistence | tr -d "\\r" | awk -F: \'$1=="loading" && $2==0 {a++} $1=="aof_enabled" && $2==1 {b++} $1=="aof_last_write_status" && $2=="ok" {c++} END {if(a!=1||b!=1||c!=1)exit 1; print "VALKEY_NATIVE_OK"}\''])
    output['seaweedfs'].update({'export_application_metadata':target_exec('seaweedfs',['/bin/sh','-ec',
      'set -eu; exec 2>/dev/null; umask 077; test ! -e /restore/readback.meta.gz; printf "fs.meta.save -o /restore/readback.meta.gz /\\n" | /usr/bin/weed shell -master=127.0.0.1:9333 -filer=127.0.0.1:8888 >/restore/export.private 2>&1; cat /restore/readback.meta.gz']),
      'export_cold_application_metadata':target_exec('seaweedfs',['/bin/sh','-ec',
      'set -eu; exec 2>/dev/null; umask 077; test -f /restore/native-restored; test ! -e /restore/cold-readback.meta.gz; printf "fs.meta.save -o /restore/cold-readback.meta.gz /\\n" | /usr/bin/weed shell -master=127.0.0.1:9333 -filer=127.0.0.1:8888 >/restore/cold-export.private 2>&1; cat /restore/cold-readback.meta.gz']),
      'loader_alive':target_exec('seaweedfs',['/bin/sh','-ec','test -p /restore/loader.in; kill -0 "$(cat /restore/loader.pid)"']),
      'release_loader_only_after_full_private_comparison':target_exec('seaweedfs',['/bin/sh','-ec',
        'test ! -e /restore/metadata-reconciled; umask 077; touch /restore/metadata-reconciled'])})
    output['private_owner_access'] = ['kubectl','-n',NAMESPACE,'port-forward','--address=127.0.0.1','pod/recovery-web','3300:3000']
    output['web']['health'] = target_exec('web',['node','-e',
      'fetch("http://127.0.0.1:3000/api/public/health").then(async r=>{const b=await r.json();if(!r.ok||b.status!=="OK"||b.version!=="4.77.0")process.exit(1);console.log("WEB_HEALTH_OK")}).catch(()=>process.exit(1))'])
    return output


def validate_valkey_archive(blob):
    """Strict actual first_valkey_capture tar schema; never extract on host."""
    try:
        need(len(blob) % 512 == 0, 'valkey-tar-length')
        files = {}; end = 0; seen = set()
        with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as archive:
            for member in archive:
                name = member.name.removeprefix('./').rstrip('/')
                need(name not in seen and not name.startswith('/') and '..' not in name.split('/'), 'valkey-tar-path')
                seen.add(name)
                need(member.isdir() or member.isfile(), 'valkey-tar-type')
                end = max(end, member.offset_data + ((member.size+511)//512)*512)
                if member.isdir():
                    need(name in ('','.', 'appendonlydir'), 'valkey-tar-directory')
                    continue
                stream = archive.extractfile(member)
                need(stream is not None, 'valkey-tar-stream')
                assert stream is not None
                body = stream.read()
                need(len(body) == member.size, 'valkey-tar-truncated')
                files[name] = body
        need(len(blob)-end >= 1024 and not any(blob[end:]), 'valkey-tar-tail')
        manifest = files['appendonlydir/appendonly.aof.manifest'].decode('ascii').splitlines()
        need(len(manifest) == 2, 'valkey-manifest-count')
        dependencies = []; base_sequence = None
        for index,line in enumerate(manifest):
            match = re.fullmatch(r'file (appendonly\.aof\.([1-9][0-9]*)\.(base\.(?:rdb|aof)|incr\.aof)) seq ([1-9][0-9]*) type ([bi])',line)
            need(match is not None, 'valkey-manifest-entry')
            assert match is not None
            name, seq, kind, declared, role = match.groups()
            need(seq == declared and role == ('b' if index == 0 else 'i') and
                 (kind.startswith('base.') if index == 0 else kind == 'incr.aof'), 'valkey-manifest-role')
            if index == 0:base_sequence=int(seq)
            else:
                assert base_sequence is not None
                need(int(seq)>=base_sequence,'valkey-manifest-sequence-regression')
            dependencies.append('appendonlydir/'+name)
        expected = {'SHA256SUMS','receipt.txt','server.identity','source-file-identities.private','rewrite-counter',
                    'monotonic-window','appendonlydir/appendonly.aof.manifest',*dependencies}
        need(set(files) == expected, 'valkey-archive-inventory')
        sums = {}
        for line in files['SHA256SUMS'].decode('ascii').splitlines():
            match = re.fullmatch(r'([0-9a-f]{64})  (appendonlydir/[a-z0-9.]+)',line)
            need(match is not None and match[2] not in sums, 'valkey-checksum-schema')
            assert match is not None
            sums[match[2]] = match[1]
        need(set(sums) == {'appendonlydir/appendonly.aof.manifest',*dependencies}, 'valkey-checksum-inventory')
        need(all(hashlib.sha256(files[n]).hexdigest() == h for n,h in sums.items()), 'valkey-checksum-mismatch')
        need(files['receipt.txt'] == b'native-live-checkpoint\nversion=8.0.12\nfreeze=CLIENT PAUSE 60000 WRITE\ncopy_deadline_seconds=45\n', 'valkey-receipt')
        return {'sha256':hashlib.sha256(blob).hexdigest(),'bytes':len(blob),'dependencies':len(dependencies)}
    except Refused:
        raise
    except Exception:
        raise Refused('valkey-archive-invalid') from None


def admit_target_storage(pvcs, pvs, volumes):
    """Readback admission BEFORE archive upload/start; never accept source PVCs."""
    need(len(pvcs) == len(pvs) == len(volumes) == 4, 'target-storage-count')
    handles = set(); uids = set()
    for component,size in CLAIMS.items():
        matches = [p for p in pvcs if p['metadata']['name'] == 'recovery-'+component]
        need(len(matches) == 1, 'target-claim-name')
        p = matches[0]; uid = p['metadata']['uid']
        need(p['metadata']['namespace'] == NAMESPACE and uid not in SOURCE_UIDS and uid not in uids
             and not p['metadata'].get('ownerReferences') and not p['metadata'].get('deletionTimestamp'), 'target-claim-identity')
        uids.add(uid)
        need(p['spec']['storageClassName'] == 'longhorn' and p['spec']['resources']['requests']['storage'] == size
             and p['status']['phase'] == 'Bound' and p['status']['capacity']['storage'] == size, 'target-claim-binding')
        need(not p['spec'].get('dataSource') and not p['spec'].get('dataSourceRef'), 'target-claim-source')
        candidates = [v for v in pvs if v['metadata']['name'] == p['spec']['volumeName']]
        need(len(candidates) == 1, 'target-pv-count'); v = candidates[0]
        csi = v['spec']['csi']; handle = csi['volumeHandle']
        need(csi['driver'] == 'driver.longhorn.io' and handle == 'pvc-'+uid == p['spec']['volumeName']
             and handle not in {'pvc-'+u for u in SOURCE_UIDS}
             and handle not in handles, 'target-csi-identity')
        handles.add(handle)
        claim = v['spec']['claimRef']
        need(claim['uid'] == uid and claim['name'] == 'recovery-'+component and claim['namespace'] == NAMESPACE
             and not v['metadata'].get('deletionTimestamp'), 'target-pv-claim-ref')
        matches = [x for x in volumes if x['metadata']['name'] == handle]
        need(len(matches) == 1 and matches[0]['spec']['numberOfReplicas'] == 2
             and not matches[0]['spec'].get('fromBackup')
             and matches[0]['status']['robustness'] == 'healthy', 'target-longhorn-replicas-health')
    return {'new_claims':4, 'distinct_new_handles':len(handles), 'two_replicas':True}


def read_metadata(kind, namespace=None):
    need(kind in ('namespaces','storageclasses','nodes','persistentvolumeclaims','persistentvolumes','volumes.longhorn.io'), 'metadata-kind-not-allowed')
    command = ['kubectl','--request-timeout=20s']
    if namespace:
        need(namespace in (NAMESPACE,'longhorn-system'), 'metadata-namespace-not-allowed')
        command += ['-n',namespace]
    result = subprocess.run(command+['get',kind,'-o','json'],stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=25,cwd=ROOT)
    need(result.returncode == 0 and len(result.stdout) < 8*1024*1024, 'metadata-read-failed')
    return json.loads(result.stdout)['items']


def admission():
    need(not any(n['metadata']['name'] == NAMESPACE for n in read_metadata('namespaces')), 'target-already-exists-do-not-adopt')
    classes = [s for s in read_metadata('storageclasses') if s['metadata']['name'] == 'longhorn']
    need(len(classes) == 1 and classes[0]['provisioner'] == 'driver.longhorn.io'
         and classes[0]['parameters']['numberOfReplicas'] == '2', 'longhorn-class-not-two-replicas')
    nodes = {n['metadata']['name']:n for n in read_metadata('nodes')}
    for node,arch,*_ in PLACEMENT.values():
        n = nodes[node]
        need(n['metadata']['labels']['kubernetes.io/arch'] == arch and not n['spec'].get('unschedulable')
             and any(c['type'] == 'Ready' and c['status'] == 'True' for c in n['status']['conditions']), 'target-node-not-ready-compatible')
    need(nodes['k3s-05']['spec']['podCIDR']=='10.42.4.0/24','fixed-postgres-client-cidr-drift')
    return {'fresh_namespace_absent':True,'storageclass_two_replicas':True,'placement_nodes_ready':True,
            'capacity_reserved':False,'request_and_runtime_headroom_checked':False,
            'runtime_and_replica_headroom_verified':False,'recovery_accepted':False}


def bundle():
    return {'scope':'fixed-first-restore-review-only','namespace':NAMESPACE,'identity_snapshot':IDENTITY,
      'helper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'dependencies_sha256':{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ('first_object_capture.py','fixture-seaweed.py','fixture-encryption.py','inspect-drain-queues.js','first_live_adapter.py')},
      'execution_ready':False,'runtime_and_replica_headroom_verified':False,
      'capacity_blocker':'Revised restore-only placement requires fresh runtime/staging headroom and actual two-replica bindings; sampled capacity is not reserved or a runtime peak guarantee.',
      'resources':resources(),'commands':commands(), 'required_private_identity_keys':{k:sorted(v) for k,v in SECRET_KEYS.items()},
      'required_gates':[
       'Authenticate the complete coordinated four-store capture receipt and exact archived stream identities.',
       'Original identity resourceVersions match the coordinated point; private six-Secret namespace-only reconstruction.',
       'Fresh node request/runtime memory, ephemeral staging and per-disk Longhorn replica scheduling capacity.',
       'New target claim UIDs/CSI handles admitted after binding, before upload/start; never source PVC mounts.',
       'FD-pinned complete decrypted archive validation, source size/hash and target receive readback equality.',
       'Postgres roles/globals plus custom dump fully restored; amcheck; table/schema/ownership/migration baseline equality.',
       'ClickHouse native RESTORED plus all table/schema/count/latest-migration equality; no SQL-managed access entities omitted.',
       'Valkey manifest/check-aof plus queue/scheduler/TTL-aware reconciliation from captured baseline, before worker startup.',
       'Seaweed complete application metadata and authenticated S3 object byte/metadata comparison while loader stdin held, again after cold restart.',
       'Both projects old trace/observation/parent/completion/privacy readback through target public API using privately supplied existing project keys.',
       'Existing owner login interactively at loopback port-forward (no password read/reset); approved loopback NEXTAUTH_URL.',
       'One new target-only metadata trace ingest/readback; no model/provider call or production client enrollment.',
       'CNI isolation enforcement evidence plus production health/storage/workload identity readback from separate approved observer.'],
      'recovery_accepted':False,'deployed':False}


def _module(name):
    spec=importlib.util.spec_from_file_location('first_restore_'+name.replace('-','_'),Path(__file__).with_name(name+'.py'))
    need(spec is not None and spec.loader is not None,'reviewed-module-unavailable')
    assert spec is not None and spec.loader is not None
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


def _target_identity(component,uid):
    need(component in SCRIPTS and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',uid or ''),'target-uid-required')
    command=['kubectl','--request-timeout=20s','-n',NAMESPACE,'get','pod','recovery-'+component,'-o',
      'jsonpath={.metadata.uid}|{.status.phase}|{.spec.containers[*].image}|{.status.containerStatuses[*].restartCount}|{.metadata.deletionTimestamp}|{.spec.volumes}|{.spec.hostNetwork}|{.spec.nodeName}']
    p=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=25)
    fields=p.stdout.decode().split('|')
    need(p.returncode==0 and len(fields)==8 and fields[:5]==[uid,'Running',IMAGES[component],'0','']
         and fields[6] in ('','false') and fields[7]==PLACEMENT[component][0],'target-identity-drift')
    volumes=json.loads(fields[5]);pvcs=[v['persistentVolumeClaim']['claimName'] for v in volumes if 'persistentVolumeClaim' in v]
    need(pvcs==(['recovery-'+component] if component in CLAIMS else [])
         and all(set(v)-{'name','emptyDir','configMap','secret','persistentVolumeClaim'}==set() for v in volumes),
         'target-volume-mount-drift')


def run_target(component,uid,args,*,data=None,timeout: float=30,limit=2*1024**2):
    """Fixed target exec with UID/image/restart continuity, no secret diagnostics.

    PRIVATE result: metadata exports can be confidential; never print this return.
    No arbitrary pod/namespace, production destination or unbounded CLI exists.
    """
    _target_identity(component,uid)
    p=subprocess.run(target_exec(component,args,stdin=data is not None),input=data,
      stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=timeout,close_fds=True)
    _target_identity(component,uid)
    need(p.returncode==0 and len(p.stdout)<=limit,'target-command-failed')
    return p.stdout


def _cipher_identity(fd,record):
    s=os.fstat(fd)
    def stable(t):
        return (t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns,t.st_ctime_ns,t.st_mode,t.st_uid,t.st_nlink)
    need(stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and stat.S_IMODE(s.st_mode)==0o600
         and s.st_nlink in (1,2) and s.st_size==record['ciphertext_bytes'],'ciphertext-fd-not-private')
    h=hashlib.sha256();offset=0
    while offset<s.st_size:
        block=os.pread(fd,min(1024**2,s.st_size-offset),offset)
        need(bool(block),'ciphertext-truncated');h.update(block);offset+=len(block)
    need(h.hexdigest()==record['ciphertext_sha256'] and stable(os.fstat(fd))==stable(s),'ciphertext-identity-drift')
    return stable(s)


def decrypt_archive(ciphertext_fd,record,identity_fd):
    """PRIVATE bounded RAM only. Age alone receives the privately provided key FD.

    No key bytes are read by Python, passed to kubectl, put in argv or logged.
    Uses the checksum-verified existing age fixture binary, not a new executable.
    This function is exercised ONLY with generated fixture identities locally.
    """
    need(record.get('status')=='COMPLETE' and type(record.get('plaintext_bytes')) is int
         and 0<record['plaintext_bytes']<=2*1024**3
         and re.fullmatch('[0-9a-f]{64}',record.get('plaintext_sha256','')),'complete-native-receipt-required')
    need(type(identity_fd) is int and identity_fd>=3,'private-identity-descriptor-required')
    before=_cipher_identity(ciphertext_fd,record)
    age=_module('fixture-encryption').tools()['age']
    os.lseek(ciphertext_fd,0,os.SEEK_SET)
    p=subprocess.Popen([str(age),'-d','-i','/proc/self/fd/'+str(identity_fd)],stdin=ciphertext_fd,
      stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,pass_fds=(identity_fd,),close_fds=True,start_new_session=True)
    assert p.stdout is not None
    data=bytearray();deadline=time.monotonic()+300
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout,selectors.EVENT_READ)
            while selector.get_map():
                need(time.monotonic()<deadline,'decrypt-deadline')
                for key,_ in selector.select(min(1,max(0,deadline-time.monotonic()))):
                    block=os.read(key.fd,65536)
                    if not block:selector.unregister(key.fileobj);continue
                    data.extend(block);need(len(data)<=record['plaintext_bytes'],'decrypt-size-limit')
        need(p.wait(timeout=max(.1,deadline-time.monotonic()))==0,'decrypt-authentication-failed')
        need(len(data)==record['plaintext_bytes'] and hashlib.sha256(data).hexdigest()==record['plaintext_sha256'],
             'native-plaintext-identity-mismatch')
        need(_cipher_identity(ciphertext_fd,record)==before,'ciphertext-changed-during-decrypt')
        return bytes(data)
    finally:
        if p.poll() is None:
            os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=10)
        if p.stdout:p.stdout.close()


def seaweed_expected(blob,validation):
    """PRIVATE expected S3 hashes derived independently from exported .idx/.dat.

    Reuses the reviewed complete protobuf/gzip parser. Reject unsupported chunk
    manifests/encryption/deletes, holes/overlaps, missing IDs or inconsistent sizes.
    Full filer metadata comparison separately preserves extended attrs and IAM.
    """
    fixture=_module('fixture-seaweed')
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:') as archive:
        files={}
        for member in archive:
            if not member.isfile():continue
            stream=archive.extractfile(member)
            need(stream is not None,'seaweed-native-member-stream')
            assert stream is not None
            files[member.name]=stream.read()
    objects=[]
    for path,raw in validation['application_metadata'].items():
        if path=='/':continue
        full=fixture.wire(raw,{1,2});entry=fixture.wire(fixture.single(full,2),{1,2,3,4,5,7,8,9,10,11,12})
        if fixture.single(entry,2,0):continue
        if not path.startswith('/buckets/'):
            continue # .etc/IAM is covered byte-exact by complete metadata comparison.
        need(path.startswith('/buckets/langfuse/'),'unexpected-restored-bucket')
        body=bytearray(fixture.single(entry,9,b''));chunks=entry.get(3,[])
        for value in chunks:
            chunk=fixture.wire(value,set(range(1,14)))
            fid=fixture.single(chunk,1).decode('ascii');vid,keycookie=fid.split(',')
            need(len(keycookie)>8 and not any(chunk.get(k) for k in (6,8,9,11,12,13)),'unsupported-s3-chunk')
            key,cookie=int(keycookie[:-8],16),int(keycookie[-8:],16)
            bases=[name[:-4] for name in files if name.startswith('volumes/') and name.endswith('.idx')
                   and re.fullmatch(r'(?:langfuse_)?'+re.escape(vid),name[8:-4])]
            need(len(bases)==1,'chunk-volume-not-unique');base=bases[0]
            idx=files[base+'.idx'];dat=files[base+'.dat'];found=[]
            for offset in range(0,len(idx),16):
                native_key,native_offset,size=struct.unpack('>QII',idx[offset:offset+16])
                if native_key==key:found.append((native_offset*8,size))
            need(len(found)==1,'chunk-index-not-unique');offset,size=found[0]
            native_cookie,native_key,native_size=struct.unpack('>IQI',dat[offset:offset+16])
            need((native_cookie,native_key,native_size)==(cookie,key,size),'chunk-native-identity')
            native=dat[offset+16:offset+16+size];length=struct.unpack('>I',native[:4])[0]
            need(4+length<len(native),'chunk-native-length')
            payload=native[4:4+length]
            if native[4+length]&1:payload=gzip.decompress(payload)
            need(fixture.single(chunk,2,0)==len(body) and fixture.single(chunk,3)==len(payload),'chunk-gap-size')
            body.extend(payload)
        attrs=fixture.wire(fixture.single(entry,4),{1,2,3,4,5,6,7,10,11,12,13,14,16,17,18,19,20,21})
        need(fixture.single(attrs,1,0)==len(body),'object-file-size')
        objects.append({'key':path[len('/buckets/langfuse/'):],'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()})
    return {'application_metadata':validation['application_metadata'],'objects':objects}


def archived_seaweed_metadata(blob):
    """PRIVATE archive-bound admission, not a reconstructed external live sample.

    Caller authenticates ciphertext/plaintext identities first. Extract only six
    bounded JSON members in RAM, then run the existing complete native validator.
    Never sample resumed production or extract confidential files on the host.
    Returns (before, after, full_validation).
    """
    need(isinstance(blob,bytes) and 0<len(blob)<=2*1024**3,'seaweed-archive-byte-bound')
    names={label+'-'+kind+'.json' for label in ('before','after') for kind in ('directory','master','local')}
    def pairs(items):
        result={}
        for key,value in items:
            need(key not in result,'seaweed-metadata-json-duplicate');result[key]=value
        return result
    try:
        metadata={};seen=set()
        with tarfile.open(fileobj=io.BytesIO(blob),mode='r:') as archive:
            for index,member in enumerate(archive):
                need(index<4096,'seaweed-archive-member-bound')
                name=member.name
                need(name not in seen and not name.startswith('/') and '..' not in name.split('/'),
                     'seaweed-metadata-member-path')
                seen.add(name)
                need(member.isfile() or member.isdir(),'seaweed-metadata-member-type')
                if name not in names:continue
                need(member.isfile() and 0<member.size<=1024**2,'seaweed-metadata-member-bound-or-type')
                stream=archive.extractfile(member);need(stream is not None,'seaweed-metadata-stream')
                assert stream is not None
                raw=stream.read(1024**2+1)
                need(len(raw)==member.size,'seaweed-metadata-truncated')
                value=json.loads(raw,object_pairs_hook=pairs)
                need(isinstance(value,dict),'seaweed-metadata-json-type');metadata[name]=value
        need(set(metadata)==names,'seaweed-metadata-six-members-required')
        objects=_module('first_object_capture');samples=[]
        for label in ('before','after'):
            directory,master,local=(metadata[label+'-'+kind+'.json'] for kind in ('directory','master','local'))
            node=directory['Topology']['DataCenters'][0]['Racks'][0]['DataNodes'][0]
            samples.append(objects.admit_seaweed(directory,master,local,node['Url'].removesuffix(':8080')))
        before,after=samples
        validation=objects.validate_seaweed_archive(blob,before=before,after=after)
        return before,after,validation
    except Refused:
        raise
    except Exception:
        raise Refused('archived-seaweed-metadata-invalid') from None


def stage_archives(capture_manifest,complete_receipts,ciphertext_fds,target_uids,identity_fd,*,seaweed_before=None,seaweed_after=None):
    """Actual target-only authenticated staging; NEVER invoked by standalone CLI.

    Pass actual capture marker, local .complete.json records and held ciphertext
    FDs obtained through the approved private NAS readback. Refuses incomplete or
    unbound sets. Returns (sanitized stage receipt, PRIVATE Seaweed expectations).
    No archive is uploaded before age authentication/native structural validation;
    no store is released here. Independently hash/size read back every received
    target stream and bracket each command with original target Pod UID checks.
    Omit both Seaweed admissions to derive archive-bound expectations privately;
    explicit admissions must be provided as a pair, never from resumed production.
    """
    need((seaweed_before is None)==(seaweed_after is None),'seaweed-admission-pair-required')
    components=('postgres-database','postgres-globals','clickhouse','seaweedfs','valkey')
    need(capture_manifest.get('scope')=='coordinated-native-encrypted-capture-not-restore'
         and capture_manifest.get('identity_bundle_ref')==IDENTITY,'coordinated-capture-marker-required')
    need(set(complete_receipts)==set(ciphertext_fds)==set(components),'complete-five-stream-set-required')
    publications=capture_manifest['components']
    need(tuple(p['component'] for p in publications)==components,'capture-component-order')
    pvcs=read_metadata('persistentvolumeclaims',NAMESPACE)
    pvs=[p for p in read_metadata('persistentvolumes') if p['metadata']['name'] in {x['spec'].get('volumeName') for x in pvcs}]
    handles={p['spec']['csi']['volumeHandle'] for p in pvs}
    volumes=[v for v in read_metadata('volumes.longhorn.io','longhorn-system') if v['metadata']['name'] in handles]
    admit_target_storage(pvcs,pvs,volumes)
    result={};private=None;objects=_module('first_object_capture')
    for publication in publications:
        component=publication['component'];record=complete_receipts[component]
        need(publication.get('exclusive') is True and publication.get('durable') is True
             and publication['bytes']==record['ciphertext_bytes'] and publication['sha256']==record['ciphertext_sha256'],
             'published-receipt-binding-mismatch')
        need(publication['name']==capture_manifest['operation_id']+'-'+component+'.age','capture-name-binding')
        blob=decrypt_archive(ciphertext_fds[component],record,identity_fd)
        target,path={'postgres-database':('postgresql','database.dump'),'postgres-globals':('postgresql','globals.sql'),
                     'clickhouse':('clickhouse','native.tar'),'seaweedfs':('seaweedfs','native.tar'),'valkey':('valkey','checkpoint.tar')}[component]
        if component=='clickhouse':objects.validate_clickhouse_archive(blob)
        elif component=='seaweedfs':
            if seaweed_before is None:
                _,_,validation=archived_seaweed_metadata(blob)
            else:
                validation=objects.validate_seaweed_archive(blob,before=seaweed_before,after=seaweed_after)
            private=seaweed_expected(blob,validation)
        elif component=='valkey':validate_valkey_archive(blob)
        elif component=='postgres-database':need(blob.startswith(b'PGDMP'),'postgres-custom-archive-required')
        else:need(blob and b'PASSWORD ' not in blob and b'CREATE ROLE ' in blob,'postgres-globals-without-passwords-required')
        run_target(target,target_uids[target],['/bin/sh','-ec',
          'set +x; set -eu; umask 077; set -C; cat > /restore/'+path],data=blob,timeout=300,limit=0)
        raw=run_target(target,target_uids[target],['/bin/sh','-ec',
          'set -eu; wc -c < /restore/'+path+'; sha256sum /restore/'+path])
        lines=raw.decode('ascii').splitlines()
        need(len(lines)==2 and lines[0].strip()==str(len(blob)) and lines[1].split()[0]==hashlib.sha256(blob).hexdigest(),
             'target-independent-stream-readback-mismatch')
        if component=='postgres-database':
            run_target(target,target_uids[target],['pg_restore','--file=/dev/null','/restore/database.dump'],timeout=300,limit=0)
        result[component]={'bytes':len(blob),'sha256':hashlib.sha256(blob).hexdigest(),'target_readback_verified':True}
    for component in components:_cipher_identity(ciphertext_fds[component],complete_receipts[component])
    return {'staged':result,'target_uids':dict(target_uids),'stores_started':False,'recovery_accepted':False},private


S3_COMPARE = r'''
const fs=require('fs'),crypto=require('crypto');
const {S3Client,GetObjectCommand}=require(require.resolve('@aws-sdk/client-s3',{paths:['/app/worker']}));
const expected=JSON.parse(fs.readFileSync(0,'utf8'));
const client=new S3Client({region:'auto',endpoint:'http://recovery-seaweedfs:8333',forcePathStyle:true,
 credentials:{accessKeyId:process.env.LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID,secretAccessKey:process.env.LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY}});
(async()=>{try{
 for(const item of expected){
  if(typeof item.key!=='string'||!Number.isSafeInteger(item.bytes)||item.bytes<0||!/^[0-9a-f]{64}$/.test(item.sha256))throw 0;
  const response=await client.send(new GetObjectCommand({Bucket:'langfuse',Key:item.key}));
  let n=0;const h=crypto.createHash('sha256');
  for await(const block of response.Body){n+=block.length;if(n>item.bytes)throw 0;h.update(block);}
  if(n!==item.bytes||h.digest('hex')!==item.sha256)throw 0;
 }
 process.stdout.write(JSON.stringify({authenticated_objects_verified:expected.length}));
}catch{process.exitCode=1;}finally{client.destroy();}})();
'''


def reconcile_seaweed(target_uids,expected,*,cold=False):
    """Reconcile real full metadata + authenticated S3 before EOF AND after cold restart."""
    fixture=_module('fixture-seaweed');uid=target_uids['seaweedfs']
    deadline=time.monotonic()+300
    for attempt in range(150):
        need(time.monotonic()<deadline,'seaweed-reconciliation-deadline')
        if cold:
            ready=run_target('seaweedfs',uid,['/bin/sh','-ec',
              'if wget -q -T 2 --spider http://127.0.0.1:8888/; then printf ready; else printf waiting; fi'])
            if ready!=b'ready':time.sleep(1);continue
        path='/restore/'+('cold-' if cold else 'live-')+'metadata-'+str(attempt)+'.gz'
        if not cold:
            run_target('seaweedfs',uid,['/bin/sh','-ec','kill -0 "$(cat /restore/loader.pid)"'])
        raw=run_target('seaweedfs',uid,['/bin/sh','-ec',
          'set -eu; umask 077; test ! -e '+path+'; printf %s '+shlex.quote('fs.meta.save -o '+path+' /\n')+
          ' | /usr/bin/weed shell -master=127.0.0.1:9333 -filer=127.0.0.1:8888 >/restore/export-'+str(attempt)+'.private 2>&1; cat '+path])
        if fixture.records(raw,application_state=True)==expected['application_metadata']:
            try:
                result=json.loads(run_target('worker',target_uids['worker'],['node','-e',S3_COMPARE],
                  data=json.dumps(expected['objects']).encode(),timeout=max(1,deadline-time.monotonic())))
            except Refused as error:
                # A cold filer may bind HTTP before the volume/master mapping is
                # readable. Retry only read-only acceptance, never load/reseed.
                if str(error)!='target-command-failed':raise
                time.sleep(1);continue
            need(result=={'authenticated_objects_verified':len(expected['objects'])},'s3-content-reconciliation')
            if not cold:
                run_target('seaweedfs',uid,['/bin/sh','-ec','kill -0 "$(cat /restore/loader.pid)"; test ! -e /restore/metadata-reconciled; umask 077; touch /restore/metadata-reconciled'])
            return {'complete_application_metadata_verified':True,**result,'cold':cold}
        time.sleep(1)
    raise Refused('complete-seaweed-reconciliation-deadline')


QUEUE_SCOPE = 'canonical delayed/repeat/failed/completed indexes, referenced jobs, scheduler metadata'
QUEUE_FIELDS = {'counts','registry_sha256','scheduled_sha1','fingerprint_scope'}
QUEUE_TREES = ['512594a1d7ecf650aa15b7364c41984ba05d99b3566d25207f30e421ac76272a',
               '4a1561fcdefc5dbd928535163416cb29fa64bb65b85bcbd2934857f1e6e02ca4',
               'd1529f2c9dc0d994a0899b3063bcd2102924fe0d30842f64136dfedf449cb13f']


def validate_queue_state(value):
    """Exact canonical capture schema; never fabricate old drain-probe fields."""
    states=_module('first_live_adapter').QUEUE_STATES
    need(isinstance(value,dict) and set(value)==QUEUE_FIELDS,'coordinated-queue-baseline-required')
    need(isinstance(value['counts'],dict) and set(value['counts'])==set(states)
         and all(type(n) is int and 0<=n<=9007199254740991 for n in value['counts'].values())
         and isinstance(value['registry_sha256'],str) and re.fullmatch('[0-9a-f]{64}',value['registry_sha256'])
         and isinstance(value['scheduled_sha1'],str) and re.fullmatch('[0-9a-f]{40}',value['scheduled_sha1'])
         and value['fingerprint_scope']==QUEUE_SCOPE,'canonical-queue-state-invalid')


def queue_probe_code():
    """Static target image registry + unchanged capture EVAL_RO; no app startup."""
    source=Path(__file__).with_name('inspect-drain-queues.js').read_bytes()
    need(hashlib.sha256(source).hexdigest()=='e321f7adf4df4592aee5664e93d45948acdc02712cd67083c943390ad8799fa6',
         'queue-probe-source-changed')
    lua=_module('first_live_adapter').QUEUE_LUA
    need(hashlib.sha256(lua.encode()).hexdigest()=='dda956242ceb79e9e1d8e1c2ca7729d1b09b37de82a09f1a40d30be9896e315e',
         'capture-queue-lua-changed')
    old='["langfuse-redis", "langfuse-redis.langfuse.svc", "langfuse-redis.langfuse.svc.cluster.local"]'
    code=source.decode();need(code.count(old)==1,'queue-endpoint-adapter-changed')
    code=code.replace(old,'["recovery-valkey"]')
    entry='if (require.main === module) main();'
    need(code.count(entry)==1,'queue-entrypoint-changed')
    code=code.replace(entry,'')
    return code+'\n'+r'''
async function restoreQueueProbe() {
 let client;
 const timer=setTimeout(()=>{if(client)client.disconnect();process.exit(1);},20000);
 try {
  const expected=JSON.parse(fs.readFileSync(0,'utf8'));
  const shared=sourceRoots();
  const names=registry(fs.readFileSync(path.join(shared,'server/queues.js'),'utf8'),process.env);
  if(digest(JSON.stringify(names))!==expected.registry_sha256)fail();
  if(typeof process.env.REDIS_AUTH!=='string'||!process.env.REDIS_AUTH)fail();
  process.env.REDIS_CONNECTION_STRING=['redis:/','/default:',encodeURIComponent(process.env.REDIS_AUTH),'@recovery-valkey:6379/0'].join('');
  const Redis=require(require.resolve('ioredis',{paths:['/app/worker']}));
  client=new Redis(options(process.env));client.on('error',()=>{});
  await client.connect();
  if(await client.ping()!=='PONG')fail();
  const values=await client.call('EVAL_RO',CAPTURE_LUA,0,...names);
  if(!Array.isArray(values)||values.length!==12||
     values.slice(0,11).some(n=>!Number.isSafeInteger(n)||n<0)||
     typeof values[11]!=='string'||! /^[0-9a-f]{40}$/.test(values[11]))fail();
  process.stdout.write(JSON.stringify({counts:Object.fromEntries(CAPTURE_STATES.map((s,i)=>[s,values[i]])),
   registry_sha256:digest(JSON.stringify(names)),scheduled_sha1:values[11],fingerprint_scope:CAPTURE_SCOPE,
   target_source_tree_sha256:TREES.map(t=>t[1])}));
 }catch{process.exitCode=1;}finally{if(client)client.disconnect();clearTimeout(timer);}
}
'''+ '\nconst CAPTURE_LUA='+json.dumps(lua)+';\nconst CAPTURE_STATES='+json.dumps(list(_module('first_live_adapter').QUEUE_STATES))+';\nconst CAPTURE_SCOPE='+json.dumps(QUEUE_SCOPE)+';\nrestoreQueueProbe();\n'


def reconcile_databases(target_uids,prepared_metadata,queue_baseline):
    """Actual native checks using migration proof and canonical captured queues.

    queue_baseline MUST be preserved_queue_state from the coordinated capture,
    not an old online drain preflight. Counts alone are
    not job-content proof; the exact full multipart AOF was independently restored.
    Refuse registry/count/TTL-driven drift, never clear/reschedule jobs to pass.
    """
    validate_queue_state(queue_baseline)
    proof=prepared_metadata['migration_proof'];uid=target_uids['postgresql']
    def pg(sql):
        return run_target('postgresql',uid,['psql','-XAt','-h','/restore','-U','restore_admin','-d','langfuse',
          '-v','ON_ERROR_STOP=1','-c',sql]).decode().strip()
    names=pg('SELECT migration_name FROM public._prisma_migrations WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL ORDER BY migration_name').splitlines()
    need(len(names)==proof['postgres_image_migrations'] and len(names)==len(set(names))
         and hashlib.sha256('\n'.join(names).encode()).hexdigest()==proof['postgres_applied_set_sha256'],
         'restored-postgres-migration-set-differs')
    need(pg('SELECT count(*) FROM public._prisma_migrations WHERE finished_at IS NULL AND rolled_back_at IS NULL')=='0',
         'restored-postgres-unfinished-migration')
    run_target('postgresql',uid,['pg_amcheck','-h','/restore','-U','restore_admin','-d','langfuse'],timeout=300,limit=0)
    def ch(sql):
        return run_target('clickhouse',target_uids['clickhouse'],['clickhouse','client','--host=127.0.0.1',
          '--max_execution_time=30','--max_threads=1','--query',sql]).decode().strip()
    need(ch('SELECT version()')=='26.8.36.3','restored-clickhouse-version')
    latest=ch('SELECT version,dirty FROM default.schema_migrations ORDER BY sequence DESC LIMIT 1 FORMAT TSV')
    need(latest==str(proof['clickhouse_latest_version'])+'\t0' and proof['clickhouse_latest_dirty'] is False,
         'restored-clickhouse-migration-state')
    tables=[json.loads(line) for line in ch("SELECT name,engine FROM system.tables WHERE database='default' ORDER BY name FORMAT JSONEachRow").splitlines()]
    checked=0
    for table in tables:
        if 'View' in table['engine']:continue
        name=table['name'];need(isinstance(name,str) and 0<len(name)<=256 and '\0' not in name,'clickhouse-table-identifier')
        # Pinned 26.8 defaults to per-part output: empty tables return no rows,
        # populated tables use is_passed. Require the explicit summary contract
        # instead of mistaking either default shape for corruption or success.
        rows=[json.loads(line) for line in ch('CHECK TABLE default.`'+name.replace('`','``')+
          '` SETTINGS check_query_single_value_result=1 FORMAT JSONEachRow').splitlines()]
        need(len(rows)==1 and set(rows[0])=={'result'} and type(rows[0]['result']) is int
             and rows[0]['result']==1,'clickhouse-native-table-integrity');checked+=1
    need(checked>0,'clickhouse-no-native-tables')
    actual=json.loads(run_target('worker',target_uids['worker'],['node','-e',queue_probe_code()],
      data=json.dumps(queue_baseline).encode(),timeout=30))
    need(isinstance(actual,dict) and set(actual)==QUEUE_FIELDS|{'target_source_tree_sha256'}
         and actual['target_source_tree_sha256']==QUEUE_TREES,'restored-queue-target-source-proof-invalid')
    target_trees=actual.pop('target_source_tree_sha256')
    validate_queue_state(actual)
    need(actual==queue_baseline,'restored-queue-scheduler-or-ttl-drift')
    return {'postgres_migration_set_verified':True,'postgres_amcheck':True,'clickhouse_tables_checked':checked,
            'clickhouse_migrations_verified':True,'queue_and_scheduler_counts_verified':True,
            'queue_canonical_fingerprint_verified':True,'target_queue_source_tree_sha256':target_trees,'recovery_accepted':False}


def restore_stores(target_uids,staging_receipt,prepared_metadata,queue_baseline,seaweed_private,capacity_receipt):
    """Fixed native target runtime integration, no create/deploy/cleanup or retry.

    Deliberately NOT a standalone execution CLI. Fixed placement requires fresh
    runtime and replica headroom evidence: callers MUST stop without that gate.
    Actual owner login/old trace/new trace/CNI/production acceptance stay separate.
    """
    need(capacity_receipt.get('runtime_and_replica_headroom_verified') is True,'runtime-and-storage-capacity-not-accepted')
    validate_queue_state(queue_baseline)
    need(staging_receipt.get('target_uids')==target_uids and set(staging_receipt['staged'])==
         {'postgres-database','postgres-globals','clickhouse','seaweedfs','valkey'}
         and all(x.get('target_readback_verified') is True for x in staging_receipt['staged'].values()),'complete-staging-required')
    for component in CLAIMS:
        run_target(component,target_uids[component],['/bin/sh','-ec','test ! -e /restore/start; umask 077; touch /restore/start'])
    deadline=time.monotonic()+600
    for component in CLAIMS:
        marker='/restore/loader.pid' if component=='seaweedfs' else '/restore/native-restored'
        while True:
            need(time.monotonic()<deadline,'native-restore-startup-deadline')
            ready=run_target(component,target_uids[component],['/bin/sh','-ec',
              'if test -f '+marker+'; then printf ready; else printf waiting; fi'])
            if ready==b'ready':break
            time.sleep(1)
    live=reconcile_seaweed(target_uids,seaweed_private)
    while run_target('seaweedfs',target_uids['seaweedfs'],['/bin/sh','-ec',
      'if test -f /restore/native-restored; then printf ready; else printf waiting; fi'])!=b'ready':
        need(time.monotonic()<deadline,'seaweed-cold-restart-deadline');time.sleep(1)
    cold=reconcile_seaweed(target_uids,seaweed_private,cold=True)
    native=reconcile_databases(target_uids,prepared_metadata,queue_baseline)
    return {'native':native,'seaweed_live':live,'seaweed_cold':cold,'applications_started':False,'recovery_accepted':False}


def start_applications(target_uids,native_receipt):
    need(native_receipt.get('native',{}).get('queue_and_scheduler_counts_verified') is True
         and native_receipt.get('seaweed_cold',{}).get('complete_application_metadata_verified') is True,
         'complete-native-acceptance-required')
    for component in ('web','worker'):
        run_target(component,target_uids[component],['/bin/sh','-ec','test ! -e /restore/start; umask 077; touch /restore/start'])
    # Only health is checked here. It is not owner login or trace API acceptance.
    for attempt in range(150):
        try:
            raw=run_target('web',target_uids['web'],commands()['web']['health'][commands()['web']['health'].index('--')+1:])
            need(raw==b'WEB_HEALTH_OK\n','target-web-health-schema')
            return {'applications_started':True,'web_health':True,'recovery_accepted':False}
        except Refused as error:
            if str(error)!='target-command-failed':raise
            time.sleep(2)
    raise Refused('target-web-health-deadline')


def publish(path, data):
    path = Path(path).absolute()
    need(path.parent == CACHE and path.name.startswith('first-restore-') and path.suffix == '.json', 'output-not-fixed-cache')
    for parent in [path.parent,*path.parents]:
        need(not parent.is_symlink(), 'output-symlink-parent')
    need(path.parent.is_dir() and path.parent.stat().st_uid == os.getuid()
         and path.parent.stat().st_mode & 0o077 == 0, 'output-parent-not-private')
    fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(data,stream,indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--render',metavar='IGNORED_CACHE_JSON')
    group.add_argument('--admit',action='store_true')
    args = parser.parse_args()
    try:
        if args.render:
            publish(args.render,bundle())
            print(json.dumps({'prepared':True,'deployed':False,'recovery_accepted':False}))
        else:
            print(json.dumps(admission()))
        return 0
    except Exception as error:
        print(str(error) if isinstance(error,Refused) else 'restore-preparation-refused',file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
