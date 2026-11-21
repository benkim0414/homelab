"""Expose image-managed binaries at the paths used by SSH/mobile clients.

Run as the unprivileged herdr user before opening SSH. Preserve replaced public
binaries as local backups; never alter configuration, keys, layout or Core data.
"""
import os
from pathlib import Path
import shutil
import stat
import uuid

TARGETS = {
    "herdr": "/usr/local/bin/herdr",
    "herdr-core": "/usr/local/libexec/herdr-core",
    "hc": "/usr/local/libexec/herdr-core",
}


def preserve_binary(path, metadata):
    # Never hardlink the source: interruption must leave it eligible for retry.
    temporary = path.parent / f".{path.name}.backup-{uuid.uuid4().hex}"
    backup = path.parent / f"{path.name}.before-image-{uuid.uuid4().hex}"
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as incoming:
            actual = os.fstat(incoming.fileno())
            if (actual.st_dev, actual.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise ValueError("Binary changed before backup")
            with temporary.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
                outgoing.flush()
                os.fchmod(outgoing.fileno(), stat.S_IMODE(metadata.st_mode) & 0o777)
                os.fsync(outgoing.fileno())
            current = os.fstat(incoming.fileno())
            if (current.st_size, current.st_mtime_ns) != (metadata.st_size, metadata.st_mtime_ns):
                raise ValueError("Binary changed during backup")
        temporary.replace(backup)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def reconcile(home):
    if os.geteuid() == 0:
        raise ValueError("Managed client paths must be reconciled as the herdr user")
    home = Path(home)
    for directory in (home / ".local", home / ".local/bin"):
        if directory.is_symlink():
            raise ValueError("Managed binary directories must not be symlinks")
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.stat().st_uid != os.geteuid():
            raise ValueError("Managed binary directory has unexpected ownership")
    directory = home / ".local/bin"
    for name, target in TARGETS.items():
        path = directory / name
        if path.is_symlink() and os.readlink(path) == target:
            continue
        if path.exists() and not path.is_symlink():
            metadata = path.lstat()
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
                    or metadata.st_nlink != 1):
                raise ValueError("Refusing to replace an unexpected binary entry")
            preserve_binary(path, metadata)
        temporary = directory / f".{name}.image-{uuid.uuid4().hex}"
        try:
            temporary.symlink_to(target)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    reconcile(Path.home())
