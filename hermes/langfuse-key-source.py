#!/usr/bin/env python3
"""Emit the fixed Langfuse key pair for Hermes command-secret provider IPC.

Stdout is a credential channel, not a diagnostic stream. Only the two projected
Secret files are read; Kubernetes' normal projected-volume symlinks are followed.
No command-line options or environment-based overrides are supported.
"""

from pathlib import Path
import sys


SECRET_ROOT = Path("/var/run/hermes-langfuse")
MAX_KEY_BYTES = 512
ERROR_MESSAGE = "Langfuse credentials unavailable.\n"
SCOPED_SETTINGS = {
    "HERMES_LANGFUSE_BASE_URL": "http://langfuse-web.langfuse.svc.cluster.local:3000",
    "HERMES_LANGFUSE_CAPTURE": "metadata",
    "HERMES_LANGFUSE_ENV": "homelab-cluster",
    "HERMES_LANGFUSE_SAMPLE_RATE": "1",
}


def _read_key(path: Path, prefix: bytes) -> str:
    """Read at most the limit plus one sentinel byte and validate without trimming."""
    with path.open("rb") as stream:
        value = stream.read(MAX_KEY_BYTES + 1)
    if (
        len(value) > MAX_KEY_BYTES
        or not value.startswith(prefix)
        or len(value) <= len(prefix)
        or any(byte < 0x21 or byte > 0x7E for byte in value)
    ):
        raise ValueError("Invalid credential")
    return value.decode("ascii")


def render_credentials(root: Path = SECRET_ROOT) -> str:
    """Return complete scoped IPC only after both keys pass validation.

    ``root`` exists solely for offline fake-fixture tests; the CLI always uses
    SECRET_ROOT. Read/validation errors propagate to the sanitizing CLI boundary.
    Printable non-whitespace ASCII excludes CR, LF, NUL and other controls.
    """
    public = _read_key(root / "public-key", b"pk-lf-")
    secret = _read_key(root / "secret-key", b"sk-lf-")
    return (
        f"HERMES_LANGFUSE_PUBLIC_KEY={public}\n"
        f"HERMES_LANGFUSE_SECRET_KEY={secret}\n"
    ) + "".join(f"{name}={value}\n" for name, value in SCOPED_SETTINGS.items())


def main(argv: list[str] | None = None) -> int:
    """Reject arguments without echo; sanitize failures before emitting any IPC."""
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        sys.stderr.write(ERROR_MESSAGE)
        return 1
    try:
        credentials = render_credentials()
    except Exception:
        # Never expose values, paths or exception messages at the IPC boundary.
        sys.stderr.write(ERROR_MESSAGE)
        return 1
    sys.stdout.write(credentials)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
