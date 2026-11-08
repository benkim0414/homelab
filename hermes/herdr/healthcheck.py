import os
from pathlib import Path
import socket
import subprocess

for pid in Path("/run/herdr-processes").read_text().split():
    os.kill(int(pid), 0)
with socket.create_connection(("127.0.0.1", 2222), timeout=2) as connection:
    assert connection.recv(256).startswith(b"SSH-2.0-")
if os.getuid() == 0:
    os.setgroups([])
    os.setgid(10000)
    os.setuid(10000)
subprocess.run(["/usr/local/bin/herdr", "status", "server"], check=True,
               stdout=subprocess.DEVNULL, timeout=5)
