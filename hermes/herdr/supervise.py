"""Supervise SSH and the unprivileged Herdr server; stop both if either exits."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

UID = GID = 10000


def user_identity():
    os.setgroups([])
    os.setgid(GID)
    os.setuid(UID)


def main():
    os.umask(0o077)
    for directory in ("/data/home", "/data/home/.config", "/data/home/.config/herdr", "/run/herdr"):
        path = Path(directory)
        path.mkdir(exist_ok=True, parents=True)
        os.chown(path, UID, GID)
        path.chmod(0o700)
    keys = Path("/data/ssh")
    keys.mkdir(exist_ok=True)
    keys.chmod(0o700)
    os.chown(keys, 0, 0)
    host_key = keys / "ssh_host_ed25519_key"
    if not host_key.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key)], check=True)
    config = Path("/data/home/.config/herdr/config.toml")
    if not config.exists():
        shutil.copyfile("/etc/herdr-default.toml", config)
        os.chown(config, UID, GID)
        config.chmod(0o600)
    Path("/run/sshd").mkdir(exist_ok=True, mode=0o755)
    Path("/run/sshd").chmod(0o755)
    subprocess.run(["/usr/sbin/sshd", "-t"], check=True)
    children = [subprocess.Popen(["/usr/local/bin/herdr", "server"],
                                 cwd="/data/home", preexec_fn=user_identity,
                                 start_new_session=True),
                subprocess.Popen(["/usr/sbin/sshd", "-D", "-e"], start_new_session=True)]
    Path("/run/herdr-processes").write_text(" ".join(str(c.pid) for c in children))
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping and all(c.poll() is None for c in children):
            time.sleep(0.2)
    finally:
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 15
        for child in children:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
    return 0 if stopping else 1


if __name__ == "__main__":
    raise SystemExit(main())
