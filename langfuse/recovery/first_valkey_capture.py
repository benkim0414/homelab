"""Fixed first-recovery Valkey fragment; NOT authorization to execute production.

API: shell_fragment() -> str. Parent supplies it on stdin to /bin/sh in the
reviewed pinned Valkey helper, captures stdout straight into the encrypted sink,
and accepts ONLY rc0 plus its own transport/encryption/restore checks. stderr is
an allowlisted failure marker, never native client output. No standalone runner.

Requires previously verified exclusion of application AND administrative writers,
no concurrent CLIENT PAUSE owner, matching mounted source identity, and a fresh
private /scratch/capture directory on fresh emptyDir (never a production path).
Helper UID/GID is explicitly 1000/1000, matching the inspected live source;
do not set fsGroup or change original PVC ownership. No root init is required.
/data is the original Valkey
PVC mounted READ ONLY. The fragment requests BGREWRITEAOF, then uses a finite
CLIENT PAUSE WRITE to freeze expiration/eviction during the dependency copy.
It DOES NOT stop Valkey or modify its config. Automatic/admin rewrites are NOT
paused: rewrite counter, manifest, dependency names/hashes/stats and directory
identity must remain unchanged or the attempt fails. Failure artifacts persist.

Native auth: REDISCLI_AUTH via SecretKeyRef langfuse-redis-auth/default only;
no credential arguments, config/ACL scraping, or secret readbacks. Image:
docker.io/valkey/valkey:8.0@sha256:04b9002ae24bbe66687fb025052ed9bcebb54f8da3937338eb718d98d362887f

Source review: Valkey 8.0.12 server.h PAUSE_ACTIONS_CLIENT_WRITE_SET;
networking.c pauseClientsByClient/updatePausedActions; expire.c activeExpireCycle;
db.c expireIfNeededWithDictIndex; evict.c isSafeToPerformEvictions;
server.c serverCron/beforeSleep/INFO; aof.c rewriteAppendOnlyFileBackground,
openNewIncrAofForAppend/flushAppendOnlyFile. A separate fresh-client WAITAOF
would only certify that client's offset, NOT all preceding writes; not used.
AOF buffer/pending fsync zero plus stable file/version evidence guards flushes.
TTL timestamps remain absolute: this preserves persistent queue state, not a
promise that TTL-expired data will remain visible at a later restore time.
"""


def shell_fragment():
    """Return the fixed reviewed shell stdin (stdout is confidential tar bytes)."""
    return FRAGMENT


FRAGMENT = r'''set -eu
umask 077
export LC_ALL=C
cli() { timeout 3 valkey-cli -e --raw -h langfuse-redis.langfuse.svc.cluster.local -p 6379 "$@"; }
fail() { printf 'VALKEY_CHECKPOINT_REFUSED\n' >&2; exit 1; }
# No set -x; raw native errors are retained only in owner-only scratch.
test -n "${REDISCLI_AUTH:-}" || fail
test ! -L /scratch/capture && test -d /scratch/capture || fail
test "$(stat -c %a /scratch/capture)" = 700 || fail
test "$(stat -c %u /scratch/capture)" = "$(id -u)" || fail
test -z "$(ls -A /scratch/capture)" || fail
cd /scratch/capture
exec 3>&2 2>native-errors.private
paused=0
finish() {
 rc=$?
 trap - EXIT HUP INT TERM
 if test "$paused" = 1; then cli CLIENT UNPAUSE >/dev/null 2>&1 || true; fi
 if test "$rc" != 0; then printf 'VALKEY_CHECKPOINT_REFUSED\n' >&3; fi
 exit "$rc"
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
get() {
 awk -F: -v k="$2" '$1==k {n++; v=$2} END {if(n!=1) exit 1; print v}' "$1"
}
info() {
 cli INFO "$1" > "$2.raw" || return 1
 tr -d '\r' < "$2.raw" > "$2" || return 1
}
identity() {
 info server "$1"
 test "$(get "$1" valkey_version)" = 8.0.12
 get "$1" run_id
 get "$1" process_id
 get "$1" valkey_version
}
state() {
 info persistence "$1" || return 1
 for k in loading aof_rewrite_in_progress aof_rewrite_scheduled rdb_bgsave_in_progress aof_buffer_length aof_pending_bio_fsync; do
  test "$(get "$1" "$k")" = 0 || return 1
 done
 test "$(get "$1" aof_enabled)" = 1 || return 1
 test "$(get "$1" aof_last_bgrewrite_status)" = ok || return 1
 test "$(get "$1" aof_last_write_status)" = ok || return 1
}
# Only layout and eviction config is queried. No ACL, requirepass, or CONFIG ALL.
cli CONFIG GET dir appendfilename appenddirname appendonly maxmemory-policy > config.private
test "$(cat config.private)" = "$(printf 'appendonly\nyes\nappendfilename\nappendonly.aof\nappenddirname\nappendonlydir\nmaxmemory-policy\nnoeviction\ndir\n/data')" || {
 # CONFIG GET ordering is not contractual: validate pairs independently.
 awk 'NR%2==1 {k=$0; next} {if(k=="dir" && $0=="/data") a++; else if(k=="appendfilename" && $0=="appendonly.aof") b++; else if(k=="appenddirname" && $0=="appendonlydir") c++; else if(k=="appendonly" && $0=="yes") d++; else if(k=="maxmemory-policy" && $0=="noeviction") e++; else exit 1} END {if(NR!=10 || a!=1 || b!=1 || c!=1 || d!=1 || e!=1) exit 1}' config.private
}
identity initial-server > initial.identity
info replication initial-replication
test "$(get initial-replication role)" = master
test "$(get initial-replication connected_slaves)" = 0
info cluster initial-cluster
test "$(get initial-cluster cluster_enabled)" = 0
test -z "$(cli MODULE LIST)"
state initial-persistence
before_rewrites=$(get initial-persistence aof_rewrites)
test "$(cli BGREWRITEAOF)" = 'Background append only file rewriting started'
i=0
while :; do
 info persistence rewrite-wait
 if test "$(get rewrite-wait aof_rewrite_in_progress)" = 0; then break; fi
 i=$((i+1)); test "$i" -lt 100; sleep 0.1
done
state rewritten-persistence
test "$(get rewritten-persistence aof_rewrites)" -eq "$((before_rewrites+1))"
# Start local monotonic deadline BEFORE sending PAUSE, never after its reply.
read started rest < /proc/uptime
cli TIME | awk 'NR==1 {s=$1} NR==2 {u=$1} END {if(NR!=2) exit 1; printf "%.0f\n", s*1000+int(u/1000)}' > wall.before
paused=1
test "$(cli CLIENT PAUSE 60000 WRITE)" = OK
# Separate round trips cross beforeSleep: all pre-pause buffered AOF must flush.
i=0
while ! (state frozen-persistence); do
 i=$((i+1)); test "$i" -lt 20; sleep 0.1
done
identity frozen-server > frozen.identity
cmp initial.identity frozen.identity
get frozen-persistence aof_rewrites > frozen.rewrites
# A fresh native rewrite must have produced precisely one base + one incremental.
# History/temporary/unlisted files, unsafe paths, duplicates, wrong sequence and
# missing dependencies are rejected, never silently omitted.
manifest=/data/appendonlydir/appendonly.aof.manifest
test ! -L /data && test ! -L /data/appendonlydir
test -f "$manifest" && test ! -L "$manifest"
cp "$manifest" manifest.before
awk '
 NF!=6 || $1!="file" || $3!="seq" || $5!="type" {exit 1}
 $2 !~ /^appendonly[.]aof[.][1-9][0-9]*[.](base[.](rdb|aof)|incr[.]aof)$/ {exit 1}
 $4 !~ /^[1-9][0-9]*$/ || seen[$2]++ {exit 1}
 {split($2, parts, "."); if(parts[3] != $4) exit 1}
 $6=="b" && NR==1 && $2 ~ /[.]base[.](rdb|aof)$/ {b++; base=$4; print $2; next}
 $6=="i" && NR==2 && $4>=base && $2 ~ /[.]incr[.]aof$/ {i++; print $2; next}
 {exit 1}
 END {if(NR!=2 || b!=1 || i!=1) exit 1}' manifest.before > dependencies
printf 'appendonly.aof.manifest\n' >> dependencies
snapshot() {
 stat -c '%d:%i:%s:%y:%z' /data/appendonlydir
 (cd /data/appendonlydir; ls -A | sort)
 while IFS= read -r f; do
  test -f "/data/appendonlydir/$f" && test ! -L "/data/appendonlydir/$f"
  test "$(stat -c %h "/data/appendonlydir/$f")" = 1
  stat -c '%n:%d:%i:%s:%y:%z' "/data/appendonlydir/$f"
  sha256sum "/data/appendonlydir/$f"
 done < dependencies
}
(cd /data/appendonlydir; ls -A | sort) > actual-files
sort dependencies > expected-files
cmp actual-files expected-files
snapshot > files.before
# Only new task-owned children may have inherited mode bits cleared. Never
# repair /scratch/capture, the read-only source, or an occupied failed stage.
for d in checkpoint checkpoint/appendonlydir; do
 test ! -e "$d" && test ! -L "$d"
 mkdir -m 700 "$d"
 # Explicit five-digit mode clears directory setgid, including GNU chmod.
 chmod 00700 "$d"
 test ! -L "$d" && test -d "$d"
 test "$(stat -c %u "$d")" = "$(id -u)"
 test "$(stat -c %a "$d")" = 700
done
while IFS= read -r f; do cp --no-clobber "/data/appendonlydir/$f" "checkpoint/appendonlydir/$f"; done < dependencies
snapshot > files.after
cmp files.before files.after
cmp manifest.before "$manifest"
while IFS= read -r f; do cmp "/data/appendonlydir/$f" "checkpoint/appendonlydir/$f"; done < dependencies
state final-persistence
identity final-server > final.identity
cmp frozen.identity final.identity
get final-persistence aof_rewrites > final.rewrites
cmp frozen.rewrites final.rewrites
get frozen-persistence aof_current_size > frozen.size
get final-persistence aof_current_size > final.size
cmp frozen.size final.size
# Fail closed even when an expired pause happened not to change any AOF bytes.
cli TIME | awk 'NR==1 {s=$1} NR==2 {u=$1} END {if(NR!=2) exit 1; printf "%.0f\n", s*1000+int(u/1000)}' > wall.after
awk -v s="$(cat wall.before)" -v e="$(cat wall.after)" 'BEGIN {if(e<s || e-s>=45000) exit 1}'
read ended rest < /proc/uptime
awk -v s="$started" -v e="$ended" 'BEGIN {if(e<s || e-s>=45) exit 1}'
test "$(cli CLIENT UNPAUSE)" = OK
paused=0
# Immutable private copy now detached from the source; native checker NEVER --fix.
timeout 10 valkey-check-aof checkpoint/appendonlydir/appendonly.aof.manifest > aof-check.private 2>&1
grep -q 'All AOF files and manifest are valid' aof-check.private
(cd checkpoint; sha256sum appendonlydir/*) > checkpoint/SHA256SUMS
printf 'native-live-checkpoint\nversion=8.0.12\nfreeze=CLIENT PAUSE 60000 WRITE\ncopy_deadline_seconds=45\n' > checkpoint/receipt.txt
cp initial.identity checkpoint/server.identity
cp files.before checkpoint/source-file-identities.private
cp frozen.rewrites checkpoint/rewrite-counter
printf '%s %s\n' "$started" "$ended" > checkpoint/monotonic-window
# Parent must enforce no-overwrite encrypted publication and verify full stream.
tar -C checkpoint -cf - .
'''
