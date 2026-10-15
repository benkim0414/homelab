#!/usr/bin/python3
"""Keep seven daily snapshots of the NAS dataset backing K3s media/backups."""
import fcntl
import re
import subprocess
from datetime import datetime, timezone

DATASET = "storage/k3s"
PREFIX = "homelab-daily-"
KEEP = 7
ZFS = "/usr/bin/zfs"


def zfs(*args):
    return subprocess.check_output([ZFS, *args], text=True).strip()


def snapshot():
    # Fail before creating or pruning anything if the expected mount changed.
    mount = zfs("get", "-H", "-o", "value", "mountpoint", DATASET)
    if mount != "/storage/k3s":
        raise RuntimeError(f"Unexpected mountpoint: {mount}")
    name = DATASET + "@" + PREFIX + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zfs("snapshot", name)
    print(f"Created {name}", flush=True)
    names = zfs("list", "-H", "-t", "snapshot", "-o", "name", "-r", DATASET).splitlines()
    pattern = re.compile(re.escape(DATASET + "@" + PREFIX) + r"\d{8}T\d{6}Z")
    managed = sorted(n for n in names if pattern.fullmatch(n))
    for old in managed[:-KEEP]:
        # No recursive or forced deletion; held snapshots fail visibly.
        zfs("destroy", old)
        print(f"Pruned {old}", flush=True)


if __name__ == "__main__":
    with open("/run/lock/homelab-k3s-snapshots.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        snapshot()
