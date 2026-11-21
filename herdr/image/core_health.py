"""Read-only Core socket/process health; never invoke the auto-starting CLI."""
import os
from pathlib import Path
import socket
import struct


def check_core(home=Path("/data/home"), executable=Path("/usr/local/libexec/herdr-core")):
    # Confirm the live listener belongs to this UID and the immutable image binary.
    # SO_PEERCRED also permits a legitimate Core-only restart without stale PID files.
    endpoint = Path(home) / ".local/state/herdr-core/default/default.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(str(endpoint))
        pid, uid, gid = struct.unpack("3i", connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        if pid <= 1 or uid != os.geteuid() or gid != os.getegid():
            raise ValueError("Unexpected Core listener identity")
        actual = Path(f"/proc/{pid}/exe").stat()
        expected = Path(executable).stat()
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError("Core listener does not use the image-managed binary")
