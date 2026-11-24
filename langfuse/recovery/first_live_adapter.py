"""Fixed Langfuse first-capture IO adapter; importing performs no IO.

Only Replica CAS writes exist here. The watch is established BEFORE the first
pause, never reconnected, and fenced through an API RV barrier at completion.
Kubernetes cannot observe an administrator issuing SQL/exec in an existing Pod:
the bounded operator client/admin-idle authorization remains an explicit input.
Native idle/scheduler checks supplement that authorization, not replace it.
Publication safety correction: live pause admission is fail-closed. The existing
inputs do not attest shared Pod/Deployment storage revision ordering; numeric RV
syntax and generated tests cannot supply that missing server contract.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import threading
import time
import urllib.parse
from typing import Any


# READ ONLY, standalone DB0, source-verified BullMQ 5.76.3 layout. No getCounts,
# Queue/Worker import, job removal, schedule disabling or queue mutation exists.
# Values/job IDs never leave the server; only cardinalities and canonical hashes.
QUEUE_LUA = r'''
local names = {}; for _,n in ipairs(ARGV) do names[n]=true end
local states={'wait','active','delayed','prioritized','paused','waiting-children','repeat','stalled','failed','completed'}
local types={'list','list','zset','zset','list','zset','zset','set','zset','zset'}
local result={}; for i=1,11 do result[i]=0 end
local parts={}; local selected={}; local inspected=0; local bytes=0
local function token(v) return tostring(string.len(v))..':'..v end
local function keep(k,allow_missing)
  if selected[k] then return end
  selected[k]=true; inspected=inspected+1
  if inspected>32768 then error('bound') end
  local typ=redis.call('TYPE',k).ok
  local values={}
  if typ=='none' then
    if not allow_missing then error('missing') end
  elseif typ=='hash' then
    local flat=redis.call('HGETALL',k); local pairs={}
    for i=1,#flat,2 do pairs[#pairs+1]={flat[i],flat[i+1]} end
    table.sort(pairs,function(a,b) return a[1]<b[1] end)
    for _,pair in ipairs(pairs) do values[#values+1]=pair[1]; values[#values+1]=pair[2] end
  elseif typ=='zset' then values=redis.call('ZRANGE',k,0,-1,'WITHSCORES')
  elseif typ=='string' then values={redis.call('GET',k)}
  elseif typ=='list' then values=redis.call('LRANGE',k,0,-1)
  elseif typ=='set' then values=redis.call('SMEMBERS',k); table.sort(values)
  else error('scheduled-type') end
  if #values>65536 then error('bound') end
  local encoded={token(k),token(typ)}
  for _,v in ipairs(values) do
    bytes=bytes+string.len(v); if bytes>33554432 then error('byte-bound') end
    encoded[#encoded+1]=token(v)
  end
  -- Canonical semantic contents, not RDB/DUMP encoding/hash-table iteration:
  -- the same restored job/scheduler must fingerprint identically on a new server.
  parts[#parts+1]=token(k)..redis.sha1hex(table.concat(encoded))
end
for _,n in ipairs(ARGV) do
  local base='bull:'..n..':'
  for i,s in ipairs(states) do
    local k=base..s; local t=redis.call('TYPE',k).ok
    if t~='none' and t~=types[i] then error('type') end
    local cmd=types[i]=='list' and 'LLEN' or (types[i]=='set' and 'SCARD' or 'ZCARD')
    local count=redis.call(cmd,k); result[i]=result[i]+count
    if s=='delayed' or s=='repeat' or s=='failed' or s=='completed' then
      if count>32768 then error('bound') end
      if t~='none' then keep(k) end
      if s~='repeat' then
        for _,id in ipairs(redis.call('ZRANGE',k,0,-1)) do keep(base..id,s~='delayed') end
      end
    end
  end
  local meta=base..'meta'; local t=redis.call('TYPE',meta).ok
  if t~='none' and t~='hash' then error('meta') end
  result[11]=result[11]+redis.call('HEXISTS',meta,'paused')
end
local cursor='0'; local pages=0; local total=0
repeat
  local r=redis.call('SCAN',cursor,'MATCH','bull:*','COUNT',256); cursor=r[1]
  pages=pages+1; total=total+#r[2]; if pages>128 or total>32768 then error('bound') end
  for _,k in ipairs(r[2]) do
    local n=string.match(k,'^bull:([^:]+):')
    if not n or not names[n] then error('namespace') end
    if string.sub(k,1,#('bull:'..n..':repeat:'))=='bull:'..n..':repeat:' then keep(k) end
  end
until cursor=='0'
table.sort(parts); result[12]=redis.sha1hex(table.concat(parts,'\000'))
return result
'''
QUEUE_STATES = ('wait','active','delayed','prioritized','paused','waiting-children','repeat','stalled','failed','completed','paused_queues')
ACTIVE = ('wait','active','prioritized','paused','waiting-children','stalled','paused_queues')

READY_SHELL = r'''set +x; set -u
out=$(timeout 3 valkey-cli -e --raw -h langfuse-redis.langfuse.svc.cluster.local -p 6379 PING 2>&1); rc=$?
case "$out" in *WRONGPASS*|*NOAUTH*|*NOPERM*) printf AUTH_REFUSED;;
PONG) test "$rc" = 0 && printf READY || printf REFUSED;;
*'Connection refused'*|*'connection refused'*) printf CONNECTION_REFUSED;;
*) printf REFUSED;; esac
'''


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class PodWatch:
    """One bounded raw watch, no kubectl watch/reconnect machinery.

    A progress bookmark is the handshake; the watch resumes from the exact list
    RV (NOT a newer WatchList snapshot, which could omit a transient writer) and
    refuses 410/error/EOF/overflow. Only numeric RV syntax is supported here;
    that syntax alone does not establish the storage backend's ordering contract.
    Unsupported RVs are refused, never rewritten in CAS payloads.
    The CAS admission algorithm requires shared storage revision ordering across
    Pods and Deployments, NOT a portable Kubernetes RV guarantee. The live adapter
    refuses pause until that contract can be validated. A list/read or an empty
    local pipe alone never proves delivery.
    """
    def __init__(self, adapter, listed, deadline):
        self.api=adapter; self.deadline=deadline
        self.lock=threading.RLock(); self.changed=threading.Condition(self.lock)
        self.pods={p['metadata']['uid']:copy.deepcopy(p) for p in listed['items']}
        self.initial_expected=set(self.pods)
        self.initial=False; self.failed=False; self.closed=False
        self.last_rv=listed['metadata']['resourceVersion']; self.events=0; self.exits={}; self.gone=set()
        self.exit_after={}; self.history=[]
        self.process=None; self.thread=None

    @property
    def allowed_exit(self):
        # Inventory tolerance only; individual events must also cross the CAS RV.
        return set(self.exit_after)

    def start(self):
        self.api.validate_pods(list(self.pods.values()),initial=True)
        self.api.initial_writer_pods={p['metadata']['uid']:copy.deepcopy(p) for p in self.pods.values()
                                      if p['metadata']['uid'] in self.api.writer_uids}
        query=urllib.parse.urlencode({'watch':'true','resourceVersion':self.last_rv,
            'allowWatchBookmarks':'true','timeoutSeconds':max(1,math.ceil(self.deadline-time.monotonic()))})
        self.process=self.api.spawn_watch('/api/v1/namespaces/langfuse/pods?'+query,self.deadline)
        self.thread=threading.Thread(target=self._read,name='first-langfuse-pod-watch',daemon=True)
        self.thread.start()
        initial_deadline=min(self.deadline,time.monotonic()+75)
        with self.changed:
            while not self.initial and not self.failed:
                left=initial_deadline-time.monotonic()
                if left<=0: self.failed=True; break
                self.changed.wait(min(.1,left))
                if time.monotonic()>=self.deadline: self.failed=True
        self.healthy()

    def _read(self):
        pending=bytearray()
        try:
            assert self.process is not None and self.process.stdout is not None
            fd=self.process.stdout.fileno(); os.set_blocking(fd,False)
            with selectors.DefaultSelector() as select:
                select.register(fd,selectors.EVENT_READ)
                while not self.closed:
                    if time.monotonic()>=self.deadline: raise RuntimeError('deadline')
                    for _,_mask in select.select(.1):
                        chunk=os.read(fd,65536)
                        if not chunk: raise RuntimeError('disconnect')
                        pending.extend(chunk)
                        if len(pending)>2*1024*1024: raise RuntimeError('overflow')
                        while b'\n' in pending:
                            line,_,pending=pending.partition(b'\n')
                            if not line: continue
                            self.accept(json.loads(line))
        except BaseException:
            with self.changed:
                if not self.closed: self.failed=True
                self.changed.notify_all()

    def accept(self,event):
        with self.changed:
            try:
                self.events+=1
                if self.events>65536: raise RuntimeError('overflow')
                kind=event['type']; pod=event['object']; rv=pod['metadata']['resourceVersion']
                if not isinstance(rv,str) or not rv.isascii() or not rv.isdecimal(): raise RuntimeError('rv')
                if int(rv)<int(self.last_rv): raise RuntimeError('rv-regression')
                self.last_rv=rv
                if kind=='BOOKMARK':
                    self.initial=True
                else:
                    if kind not in ('ADDED','MODIFIED','DELETED'): raise RuntimeError('watch-error')
                    uid=pod['metadata']['uid']
                    if uid not in self.initial_expected: raise RuntimeError('unreviewed-pod')
                    original=self.pods.get(uid)
                    if kind=='ADDED': raise RuntimeError('unexpected-added')
                    if original is None: raise RuntimeError('reappeared')
                    if (pod['metadata']['name']!=original['metadata']['name'] or pod['spec']!=original['spec']
                            or pod['metadata'].get('ownerReferences')!=original['metadata'].get('ownerReferences')):
                        raise RuntimeError('pod-spec-changed')
                    if uid in self.api.writer_uids:
                        boundary=self.exit_after.get(uid)
                        authorized=boundary is not None and int(rv)>int(boundary)
                        statuses=pod.get('status',{}).get('containerStatuses',[])
                        if len(statuses)!=1 or statuses[0].get('restartCount',0)!=0: raise RuntimeError('writer-restart')
                        termination=statuses[0].get('state',{}).get('terminated')
                        if not authorized and not termination:
                            if (pod.get('status',{}).get('phase')!='Running' or statuses[0].get('ready') is not True
                                    or 'running' not in statuses[0].get('state',{})): raise RuntimeError('writer-not-clean')
                        if termination:
                            code=termination.get('exitCode'); signal_number=termination.get('signal',0)
                            if (not authorized or code not in (0,143) or signal_number not in (0,15)
                                    or termination.get('reason') in ('OOMKilled','ContainerCannotRun')):
                                raise RuntimeError('abnormal-writer-exit')
                            self.exits[uid]={'exitCode':code,'signal':signal_number,'rv':rv}
                        if pod['metadata'].get('deletionTimestamp') and not authorized:
                            raise RuntimeError('unrequested-writer-termination')
                        if kind=='DELETED':
                            if uid not in self.exits: raise RuntimeError('exit-not-observed')
                            if not authorized: raise RuntimeError('unrequested-writer-deletion')
                            self.gone.add(uid); del self.pods[uid]
                        else: self.pods[uid]=copy.deepcopy(pod)
                    else:
                        if kind=='DELETED': raise RuntimeError('source-or-diagnostic-deleted')
                        self.api.validate_pod(pod)
                        self.pods[uid]=copy.deepcopy(pod)
                    self.history.append({'type':kind,'uid':uid,'rv':rv})
                self.changed.notify_all()
            except BaseException:
                self.failed=True; self.changed.notify_all()

    def healthy(self):
        with self.lock:
            self.api.c.check(not self.failed and not self.closed and self.initial
                             and self.thread is not None and self.thread.is_alive(), 'pod-watch-lost')

    def barrier(self,listed,deadline):
        rv=listed['metadata']['resourceVersion']
        self.api.c.check(isinstance(rv,str) and rv.isascii() and rv.isdecimal(),'pod-watch-rv')
        end=min(deadline,time.monotonic()+75)
        with self.changed:
            while int(self.last_rv)<int(rv) and not self.failed:
                left=end-time.monotonic()
                if left<=0: self.failed=True; break
                self.changed.wait(min(.1,left))
            self.healthy()
            # The API list can be ahead OR behind the reader. Validate its
            # inventory at its own RV after the watch has caught up, not against
            # a racy current `gone` set. Later invalid events still fail forever.
            self.api.validate_pods(listed['items'],at_rv=rv)
            return self.last_rv

    def close(self):
        with self.changed:
            self.closed=True; self.changed.notify_all()
        if self.process is not None:
            try: os.killpg(self.process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            self.process.wait(timeout=3)
            for stream in (self.process.stdin,self.process.stdout,self.process.stderr):
                if stream is not None: stream.close()
        if self.thread is not None: self.thread.join(timeout=1)


class Fence:
    def __init__(self,adapter): self.api=adapter; self.finished=False
    def check(self,deadline):
        try:
            self.api.watch.healthy()
            self.api.c.check(self.api.watch.gone==self.api.writer_uids,'writers-not-gone')
            if time.monotonic()-self.api.last_frozen_check>=1:
                self.api.frozen_checks(deadline)
            return True
        except BaseException: return False
    def finish(self,deadline):
        if self.finished: return False
        try:
            self.api.frozen_checks(deadline)
            self.api.watch.barrier(self.api.get('pods','',deadline),deadline)
            self.api.watch.healthy()
            return True
        except BaseException: return False
        finally:
            self.finished=True; self.api.watch.close()


class Adapter:
    """Actual WriterGuard protocol; only low-level Kubernetes IO is replaceable.

    expected/prepared are private exact snapshots reviewed for this operation.
    The watch begins in start(), before WriterGuard.run and before any CAS.
    """
    def __init__(self,capture,prepared,helper,approval,directory,*,timeout=1800):
        capture.check(helper.get('uid') not in {v['pod_uid'] for v in capture.DIAGNOSTICS.values()},
                      'capture-helper-is-retained-terminal-artifact')
        self.c=capture; self.prepared=copy.deepcopy(prepared); self.helper=copy.deepcopy(helper)
        self.approval=approval; self.directory=Path(directory); self.timeout=timeout
        self.sources=copy.deepcopy(prepared['pods']); self.sources['capture-helper']=copy.deepcopy(helper)
        self.writer_uids={self.sources[n]['uid'] for n in capture.writer.TARGETS}
        self.expected={r['name']:capture.writer.Resource(r['name'],r['uid'],r['resourceVersion'],copy.deepcopy(r['spec']),
                                                       generation=r.get('generation'))
                       for r in prepared['workloads']}
        self.phase='NEW'; self.watch: Any=None; self.storage=None; self.application=None
        self.queue_names=None; self.scheduled=None; self.queue_initial=None; self.last_frozen_check=0
        self.migration=copy.deepcopy(prepared['migration_proof']); self.receipts=0
        self.resumed_names=set(); self.initial_writer_pods={}

    def get(self,kind,name,deadline,namespace: str | None='langfuse'):
        self.c.check(kind in ('pods','pod','deployment','replicaset','jobs','cronjobs','application','pvc','pv','statefulset','volumes.longhorn.io'),'adapter-get-scope')
        return self.c.get(kind,name,deadline,namespace)

    def execute(self,source,argv,deadline):
        return self.c.execute(source['name'],source['container'],list(argv),deadline).strip()

    def spawn_watch(self,path,deadline):
        return subprocess.Popen(['kubectl','--request-timeout='+str(max(1,math.ceil(deadline-time.monotonic())))+'s',
            'get','--raw',path],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            start_new_session=True,close_fds=True)

    def _source(self,pod):
        matches=[s for s in self.sources.values() if s['uid']==pod['metadata']['uid']]
        self.c.check(len(matches)==1,'unreviewed-pod')
        return matches[0]

    def validate_pod(self,pod):
        if self.c.diagnostic_pod(pod): return
        source=self._source(pod); metadata=pod['metadata']; spec=pod['spec']; status=pod.get('status',{})
        containers=spec.get('containers',[]); states=status.get('containerStatuses',[])
        if source is not self.sources.get('capture-helper'):
            self.c.check(source['container'] in self.c.preflight.IMAGE_DIGESTS and source['image'].endswith(
                '@sha256:'+self.c.preflight.IMAGE_DIGESTS[source['container']]),'source-pinned-image-required')
        self.c.check(metadata['name']==source['name'] and metadata.get('namespace')=='langfuse'
            and len(containers)==len(states)==1 and containers[0]['name']==source['container']
            and containers[0]['image']==source['image'] and not spec.get('ephemeralContainers')
            and status.get('phase')=='Running' and not metadata.get('deletionTimestamp')
            and states[0].get('ready') is True and states[0].get('restartCount')==0
            and 'running' in states[0].get('state',{}),'source-pod-not-clean')
        if source is self.sources.get('capture-helper'): self.admit_helper(pod)

    def validate_pods(self,pods,initial=False,at_rv=None):
        seen=set()
        resumed_counts={name:0 for name in self.resumed_names}
        for pod in pods:
            uid=pod['metadata']['uid']
            if self.phase=='RESUMING' and uid not in self.writer_uids:
                owners=pod['metadata'].get('ownerReferences',[])
                matched=False
                for name in self.resumed_names:
                    original=self.initial_writer_pods[self.sources[name]['uid']]
                    # nodeName is assigned by the scheduler, not a replica/spec
                    # mutation. A new Pending Pod need not already be scheduled.
                    wanted={k:v for k,v in original['spec'].items() if k!='nodeName'}
                    actual={k:v for k,v in pod['spec'].items() if k!='nodeName'}
                    if owners==original['metadata'].get('ownerReferences') and actual==wanted:
                        self.c.check(not pod['metadata'].get('deletionTimestamp'),'resumed-pod-deleting')
                        resumed_counts[name]+=1
                        self.c.check(resumed_counts[name]<=self.expected[name].spec['replicas'],'unexpected-resume-replicas')
                        matched=True; break
                if matched: continue
            self.c.check(uid not in seen,'duplicate-pod'); seen.add(uid)
            if uid in self.writer_uids and not initial:
                source=self._source(pod)
                if uid in (self.watch.allowed_exit if self.watch else set()):
                    # A metadata list need not have caught up with the reader.
                    # Termination/normal-exit history is validated by the watch.
                    original=self.initial_writer_pods[uid]
                    self.c.check(pod['metadata']['name']==source['name'] and pod['spec']==original['spec']
                        and pod['metadata'].get('ownerReferences')==original['metadata'].get('ownerReferences'),'writer-identity')
                    continue
            self.validate_pod(pod)
        expected={s['uid'] for s in self.sources.values()}|{v['pod_uid'] for v in self.c.DIAGNOSTICS.values()}
        if self.watch and at_rv is not None:
            gone={event['uid'] for event in self.watch.history
                  if event['type']=='DELETED' and int(event['rv'])<=int(at_rv)}
            expected-=gone
            self.c.check(seen==expected,'pod-inventory-changed')
        elif self.watch and not initial:
            # Before a barrier, absence of an intentionally stopping writer is
            # provisional only. stopped()/fence() require caught-up normal exits.
            self.c.check(expected-self.watch.allowed_exit<=seen<=expected,'pod-inventory-changed')
        else:
            self.c.check(seen==expected,'pod-inventory-changed')

    def admit_helper(self,pod):
        spec=pod['spec']; security=spec.get('securityContext',{}); container=spec['containers'][0]
        self.c.check(security.get('runAsUser')==1000 and security.get('runAsGroup')==1000
            and 'fsGroup' not in security and spec.get('automountServiceAccountToken') is False,
            'helper-security-identity')
        child=container.get('securityContext',{})
        self.c.check(child.get('runAsUser',1000)==1000 and child.get('runAsGroup',1000)==1000
            and child.get('allowPrivilegeEscalation') is False and child.get('readOnlyRootFilesystem') is True
            and child.get('privileged',False) is False and child.get('capabilities',{}).get('drop')==['ALL']
            and not child.get('capabilities',{}).get('add') and not spec.get('initContainers')
            and not any(spec.get(k,False) for k in ('hostNetwork','hostPID','hostIPC')),'helper-container-security')
        expected={'name':'REDISCLI_AUTH','valueFrom':{'secretKeyRef':{'name':'langfuse-redis-auth','key':'default'}}}
        self.c.check(container.get('env')==[expected] and not container.get('envFrom'),'helper-native-auth-reference')
        volumes={v['name']:v for v in spec.get('volumes',[])}
        mounts={m['mountPath']:m for m in container.get('volumeMounts',[])}
        data=mounts.get('/data',{}); scratch=mounts.get('/scratch',{})
        self.c.check(set(mounts)=={'/data','/scratch'} and set(volumes)=={data.get('name'),scratch.get('name')}
            and data.get('readOnly') is True and volumes.get(data.get('name'),{}).get('persistentVolumeClaim')==
            {'claimName':'langfuse-redis','readOnly':True} and
            'emptyDir' in volumes.get(scratch.get('name'),{}),'helper-original-readonly-pvc')
        owners=pod['metadata'].get('ownerReferences',[])
        self.c.check(len(owners)==1 and owners[0].get('kind')=='Job'
            and owners[0].get('uid')==self.helper['job_uid'] and owners[0].get('name')==self.helper['job_name'],
            'helper-job-identity')

    def policies(self,deadline,initial=False):
        app=self.get('application','langfuse',deadline,'argocd')
        self.c.check('automated' not in app['spec'].get('syncPolicy',{}) and not app.get('operation')
            and app.get('status',{}).get('operationState',{}).get('phase') not in ('Running','Terminating'),
            'manual-application-required')
        if initial:
            self.c.check(app['status']['sync']['status']=='Synced' and app['status']['health']['status']=='Healthy',
                         'initial-application-not-healthy-synced')
            self.application=copy.deepcopy(app['spec'])
        self.c.check(app['spec']==self.application,'application-spec-changed')
        self.c.check(not self.get('cronjobs','',deadline)['items'],'unreviewed-cronjob')
        jobs=self.get('jobs','',deadline)['items']
        active=[j for j in jobs if j['metadata']['uid']==self.helper['job_uid']]
        retained=[j for j in jobs if j['metadata']['uid']!=self.helper['job_uid']]
        self.c.check(len(active)==1 and active[0]['metadata']['name']==self.helper['job_name']
                     and not active[0]['metadata'].get('deletionTimestamp'),'helper-job-changed')
        self.c.validate_diagnostic_jobs(retained)

    def volume_proofs(self,deadline):
        result={}; pods=self.get('pods','',deadline)['items']
        self.validate_pods(pods)
        store_names={'postgres-data-langfuse-postgresql-0':'postgresql','langfuse-clickhouse-data':'clickhouse',
                     'langfuse-redis':'valkey','langfuse-s3-data':'seaweedfs'}
        for name,(uid,size) in self.c.preflight.CLAIMS.items():
            pvc=self.get('pvc',name,deadline); pv=self.get('pv','pvc-'+uid,deadline,None)
            m=pvc['metadata']; s=pvc['spec']; v=pv['spec']; pm=pv['metadata']
            self.c.check(m['uid']==uid and not m.get('ownerReferences') and not m.get('deletionTimestamp')
                and s['volumeName']=='pvc-'+uid and s['storageClassName']=='longhorn'
                and s['resources']['requests']['storage']==size and pvc['status']['phase']=='Bound'
                and pvc['status']['capacity']['storage']==size,'original-claim-changed')
            self.c.check(v['claimRef']['uid']==uid and v['claimRef']['name']==name and v['claimRef']['namespace']=='langfuse'
                and v['csi']['driver']=='driver.longhorn.io' and v['csi']['volumeHandle']=='pvc-'+uid
                and v['persistentVolumeReclaimPolicy']=='Delete' and not pm.get('deletionTimestamp'), 'original-pv-changed')
            volume=self.get('volumes.longhorn.io','pvc-'+uid,deadline,'longhorn-system')
            self.c.check(volume['spec']['numberOfReplicas']==2 and volume['status']['state']=='attached'
                         and volume['status']['robustness']=='healthy','original-volume-unhealthy')
            retention={'reclaim':'Delete','claimOwners':m.get('ownerReferences',[]),'pvOwners':pm.get('ownerReferences',[])}
            component=store_names[name]
            if component in ('postgresql','clickhouse'):
                controller=self.get('statefulset','langfuse-'+component,deadline)
                policy=controller['spec'].get('persistentVolumeClaimRetentionPolicy')
                self.c.check(policy=={'whenDeleted':'Retain','whenScaled':'Retain'},'statefulset-retention-changed')
                retention['statefulset']=policy
            consumers=[]
            for pod in pods:
                # Retained terminal artifacts keep PVC references in Pod.spec;
                # they are not current source consumers. Exclude only exact
                # UID/Job/outcome-validated diagnostics, never arbitrary Pods.
                if self.c.diagnostic_pod(pod): continue
                for vol in pod['spec'].get('volumes',[]):
                    claim=vol.get('persistentVolumeClaim',{})
                    if claim.get('claimName')==name:
                        source=self._source(pod)
                        expected=self.helper['uid'] if source is self.sources.get('capture-helper') else self.sources[
                            'langfuse-redis' if component=='valkey' else component]['uid']
                        self.c.check(pod['metadata']['uid']==expected,'unreviewed-volume-consumer')
                        consumers.append({'uid':expected,'readOnly':claim.get('readOnly',False)})
            result[component]={'pvc':{'uid':m['uid'],'resourceVersion':m['resourceVersion'],'spec':s},
                'pv':{'uid':pm['uid'],'resourceVersion':pm['resourceVersion'],'spec':v},
                'volume_handle':'pvc-'+uid,'consumers':sorted(consumers,key=lambda x:x['uid']),
                'retention':retention,'health_ref':'attached-healthy-two-original-replicas'}
            expected_count=2 if component=='valkey' else 1
            self.c.check(len(consumers)==expected_count,'original-consumer-missing')
        if self.storage is None: self.storage=copy.deepcopy(result)
        self.c.check(result==self.storage,'original-volume-proof-changed')
        return result

    def registry(self,deadline):
        script=(self.c.HERE/'inspect-drain-queues.js').read_text()
        script=script.replace('if (require.main === module) main();','')
        script+='\nprocess.stdout.write(JSON.stringify(registry(fs.readFileSync(path.join(sourceRoots(),"server/queues.js"),"utf8"),process.env)));'
        names=json.loads(self.execute(self.sources['langfuse-worker'],['node','-e',script],deadline))
        import re
        self.c.check(isinstance(names,list) and 46<=len(names)<=512 and len(set(names))==len(names)
                     and all(isinstance(n,str) and re.fullmatch('[a-z0-9-]+',n) for n in names),'queue-registry-invalid')
        self.queue_names=names

    def queue_sample(self,deadline):
        assert self.queue_names is not None
        raw=self.execute(self.helper,['valkey-cli','-e','--json','-h',
            'langfuse-redis.langfuse.svc.cluster.local','-p','6379','EVAL_RO',QUEUE_LUA,'0',*self.queue_names],deadline)
        values=json.loads(raw)
        self.c.check(isinstance(values,list) and len(values)==12 and
            all(type(v) is int and 0<=v<=9007199254740991 for v in values[:11]) and
            isinstance(values[11],str) and len(values[11])==40 and all(ch in '0123456789abcdef' for ch in values[11]),
            'queue-sample-invalid')
        return {'counts':dict(zip(QUEUE_STATES,values[:11])),'scheduled_sha1':values[11],
                'registry_sha256':fingerprint(self.queue_names),
                'fingerprint_scope':'canonical delayed/repeat/failed/completed indexes, referenced jobs, scheduler metadata'}

    def database_idle(self,deadline):
        pg=self.execute(self.sources['postgresql'],['/bin/sh','-ec',self.c.native.PG_SHELL,'first-live-idle',self.c.drain.PG_IDLE_SQL],deadline)
        pg_idle=self.c.drain.parse_pg(pg)['sampled_no_inflight_work']
        # No unfinished async mutations or inserts/queries in the application DB.
        query="SELECT (SELECT count() FROM system.processes WHERE is_initial_query AND query_id!=currentQueryID())+(SELECT count() FROM system.mutations WHERE database='default' AND NOT is_done) FORMAT TSV"
        ch=self.execute(self.sources['clickhouse'],self.c.native.CH_OPTIONS+[query],deadline)
        self.c.check(ch.isascii() and ch.isdecimal() and len(ch)<=15,'clickhouse-idle-format')
        return pg_idle and ch=='0'

    def clean_migrations(self,deadline):
        pg=self.sources['postgresql']; native=self.c.native
        query='SELECT migration_name FROM public._prisma_migrations WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL ORDER BY migration_name'
        names=self.execute(pg,['/bin/sh','-ec',native.PG_SHELL,'first-live-migrations',query],deadline).splitlines()
        self.c.check(len(names)==self.migration['postgres_image_migrations'] and
            hashlib.sha256('\n'.join(names).encode()).hexdigest()==self.migration['postgres_applied_set_sha256'], 'postgres-migration-set-changed')
        status=native.parse_pg_migrations(self.execute(pg,['/bin/sh','-ec',native.PG_SHELL,'first-live-migrations',native.PG_MIGRATION_SQL],deadline))
        cleanup=','.join("'"+n+"'" for n in sorted(self.c.EXPECTED_CLEANUP))
        rows=self.execute(pg,['/bin/sh','-ec',native.PG_SHELL,'first-live-migrations',
            'SELECT count(*) FROM public._prisma_migrations WHERE migration_name IN ('+cleanup+')'],deadline)
        ch=native.parse_ch_migration(self.execute(self.sources['clickhouse'],native.CH_OPTIONS+[native.CH_MIGRATION_SQL],deadline))
        self.c.check(status['migrations_clean'] and rows=='0' and ch['migrations_clean'] and
            ch['latest_migration_version']==self.migration['clickhouse_latest_version'],'migration-safety-changed')
        return fingerprint(self.migration)

    def ready(self,deadline):
        end=min(deadline,time.monotonic()+15)
        while True:
            self.watch.healthy()
            result=self.execute(self.helper,['/bin/sh','-c',READY_SHELL],min(end,deadline))
            if result=='READY': return
            self.c.check(result=='CONNECTION_REFUSED' and time.monotonic()+3<end,'helper-readiness-refused')
            time.sleep(3)

    def start(self,deadline):
        self.approval.validate(time.monotonic())
        listed=self.get('pods','',deadline)
        self.watch=PodWatch(self,listed,deadline)
        try:
            self.watch.start()
            self.policies(deadline,initial=True)
            self.volume_proofs(deadline)
            self.ready(deadline)
            self.registry(deadline)
            self.queue_initial=self.queue_sample(deadline)
            self.database_idle(deadline)  # Admit the read-only idle interfaces before any CAS; drain may still be pending.
            for name in self.c.writer.TARGETS:
                pod=self.initial_writer_pods[self.sources[name]['uid']]
                owners=pod['metadata'].get('ownerReferences',[])
                self.c.check(len(owners)==1 and owners[0].get('kind')=='ReplicaSet','writer-owner-kind')
                rs=self.get('replicaset',owners[0]['name'],deadline)
                parents=rs['metadata'].get('ownerReferences',[])
                self.c.check(rs['metadata']['uid']==owners[0]['uid'] and len(parents)==1
                    and parents[0].get('kind')=='Deployment' and parents[0].get('uid')==self.expected[name].uid
                    and parents[0].get('name')==name,'writer-controller-identity')
            actual=self.c.migration_proof(self.sources,deadline)
            self.c.check(actual==self.migration,'prepared-image-migrations-changed')
            self.phase='READY'
        except BaseException:
            self.close(); raise

    def read(self,name,deadline):
        self.c.check(name in self.c.writer.TARGETS,'deployment-scope')
        doc=self.get('deployment',name,deadline)
        self.c.check(not doc['metadata'].get('deletionTimestamp'),'deployment-deleting')
        return self.c.writer.Resource(doc['metadata']['name'],doc['metadata']['uid'],doc['metadata']['resourceVersion'],doc['spec'],
                                      namespace=doc['metadata']['namespace'],kind=doc['kind'],
                                      generation=doc['metadata'].get('generation'))

    def evidence(self,approval,resources,phase,challenge,deadline):
        self.c.check(approval==self.approval and tuple(r.name for r in resources)==self.c.writer.TARGETS,
                     'approval-operation-binding')
        approval.validate(time.monotonic())
        if phase=='resume':
            for resource in resources:
                if resource.spec['replicas']==0 and self.expected[resource.name].spec['replicas']>0:
                    uid=self.sources[resource.name]['uid']
                    self.c.check(uid in self.watch.gone and uid in self.watch.exits,'resume-original-exit-unverified')
            self.phase='RESUMING'
            # Capture has ended (possibly failed); no journal replay or retry.
            self.close()
        else:
            self.c.check(self.phase in ('READY','PAUSING','FROZEN'),'adapter-not-started')
            self.watch.healthy()
        self.policies(deadline)
        storage=self.volume_proofs(deadline)
        migration=self.clean_migrations(deadline)
        if phase=='pause':
            # WriterGuard journals mutation_intent only after evidence returns.
            # Wait for the existing ordered reader to process through this fresh
            # server list RV. healthy() (or draining a local buffer) is not that
            # proof. A transient failure delivered before the boundary is sticky.
            self.watch.barrier(self.get('pods','',deadline),deadline)
            self._require_pause_ordering()
        self.receipts+=1
        path=self.directory/('safety-'+str(self.receipts)+'.json')
        proof={'phase':phase,'challenge':challenge,'migration_sha256':migration,
            'queue_preservation':self.scheduled,'initial_queue_state':self.queue_initial,'watch_rv':self.watch.last_rv,
            'normal_writer_exits':copy.deepcopy(self.watch.exits),'watch_history':copy.deepcopy(self.watch.history)}
        self.c.save(path,proof)
        return self.c.writer.Evidence(approval.operation_id,copy.deepcopy(resources),copy.deepcopy(storage),
            approval.client_idle_ref,str(path),time.monotonic(),tuple((r.name,r.images()) for r in resources),
            True,True,True,str(path),challenge)

    def _require_pause_ordering(self):
        # No operator boolean, numeric-RV test or current list is a backend
        # ordering attestation. This publication carries no validated binding to
        # a shared Pod/Deployment revision domain. Refuse before journal intent
        # (and again for callers invoking scale directly), rather than guessing.
        # Generated IO fixtures model the contract explicitly; they are not
        # production admission evidence. No operational bypass is exposed here.
        self.c.check(False,'pause-watch-ordering-unproven')

    def scale(self,before,replicas,deadline):
        self.c.check(before.name in self.expected and replicas in (0,self.expected[before.name].spec['replicas']), 'replica-scope')
        current=self.read(before.name,deadline)
        self.c.check(before.same_revision(current),'deployment-cas-precheck')
        if replicas==0: self._require_pause_ordering()
        # One fresh precheck, not a retry: patch exactly the newer GET snapshot.
        # A status write after this GET still conflicts atomically and stops.
        before=current
        if replicas>0: self.c.check(self.phase=='RESUMING','explicit-resume-required')
        patch=[{'op':'test','path':'/metadata/uid','value':before.uid},
               {'op':'test','path':'/metadata/resourceVersion','value':before.version},
               {'op':'test','path':'/spec','value':before.spec},
               {'op':'replace','path':'/spec/replicas','value':replicas}]
        # Serialize decoding with CAS acknowledgement, not just intent. The
        # existing pipe/reader retains events while this bounded IO is in flight;
        # events already produced by a fast controller are checked after release.
        # They cannot be authorized by decode time: only RV > committed CAS RV
        # admits shutdown, conservatively rejecting events in the pre-CAS gap.
        with self.watch.lock:
            if replicas==0: self.watch.healthy()
            try:
                raw=self.c.run(['kubectl','--request-timeout=20s','-n','langfuse','patch','deployment',before.name,
                    '--type=json','--patch',json.dumps(patch),'-o','json'],deadline)
                doc=json.loads(raw)
                if replicas==0:
                    m=doc['metadata']; rv=m['resourceVersion']
                    self.c.check(isinstance(rv,str) and rv.isascii() and rv.isdecimal()
                        and int(rv)>max(int(before.version),int(self.watch.last_rv))
                        and m['uid']==before.uid and m['name']==before.name
                        and m['namespace']==before.namespace and doc['kind']==before.kind
                        and type(m.get('generation')) is int and m['generation']==before.generation+1
                        and doc['spec']==before.scaled(0).spec,'pause-cas-boundary-unverified')
                    uid=self.sources[before.name]['uid']
                    self.c.check(uid not in self.watch.exit_after,'duplicate-pause')
                    self.watch.exit_after[uid]=rv
                    self.phase='PAUSING'
            except BaseException:
                if replicas==0:
                    # Unknown write/response outcome cannot grant shutdown rights.
                    self.watch.failed=True; self.watch.changed.notify_all()
                raise
        if replicas>0: self.resumed_names.add(before.name)
        return self.c.writer.Resource(doc['metadata']['name'],doc['metadata']['uid'],doc['metadata']['resourceVersion'],doc['spec'],
                                      namespace=doc['metadata']['namespace'],kind=doc['kind'],
                                      generation=doc['metadata'].get('generation'))

    def stopped(self,name,deadline):
        self.watch.healthy(); uid=self.sources[name]['uid']
        listed=self.get('pods','',deadline)
        self.watch.barrier(listed,deadline)
        if uid not in self.watch.gone: return False
        self.c.check(uid in self.watch.exits,'normal-exit-evidence-required')
        if name=='langfuse-worker':
            self.phase='FROZEN'; self.frozen_checks(deadline)
        return True

    def drained(self,deadline):
        self.watch.healthy()
        if not self.database_idle(deadline): return False
        sample=self.queue_sample(deadline)
        if any(sample['counts'][k] for k in ACTIVE): return False
        self.scheduled=sample
        return True

    def frozen_checks(self,deadline):
        self.watch.healthy()
        self.c.check(self.watch.gone==self.writer_uids,'writers-not-gone')
        self.policies(deadline); self.volume_proofs(deadline)
        self.c.check(self.database_idle(deadline),'native-db-not-idle')
        sample=self.queue_sample(deadline)
        self.c.check(not any(sample['counts'][k] for k in ACTIVE) and self.scheduled is not None
            and sample['registry_sha256']==self.scheduled['registry_sha256']
            and sample['scheduled_sha1']==self.scheduled['scheduled_sha1']
            and all(sample['counts'][k]==self.scheduled['counts'][k] for k in ('delayed','repeat','failed','completed')),
            'scheduled-state-changed')
        self.last_frozen_check=time.monotonic()

    def fence(self,deadline):
        self.watch.barrier(self.get('pods','',deadline),deadline)
        self.frozen_checks(deadline)
        return Fence(self)

    def close(self):
        if self.watch is not None and not self.watch.closed: self.watch.close()
