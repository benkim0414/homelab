"""Check a quarantined standalone restore. Do not import or start Hermes."""
import json
import os
from pathlib import Path
import sqlite3
import stat


# These paths were reviewed in public source of the pinned image.
# This is not a general credential scrubber or permission to inspect credentials.
REMOVE = ('auth.json', '.env', 'auth.json.corrupt')


def inspect(root):
    root = Path(root)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            os.stat('profiles', dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError('unsupported-layout')
        entry = os.stat('state.db', dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(entry.st_mode):
            raise ValueError('unsupported-database')
        removed = 0
        for name in REMOVE:
            try:
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not (stat.S_ISREG(entry.st_mode) or stat.S_ISLNK(entry.st_mode)):
                raise ValueError('unsupported-credential-entry')
            os.unlink(name, dir_fd=descriptor)
            removed += 1
        # The clone has no concurrent writers. Read no session/message rows.
        connection = sqlite3.connect((root / 'state.db').as_uri() + '?mode=ro', uri=True)
        try:
            connection.execute('PRAGMA query_only=ON')
            if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('integrity-failed')
        finally:
            connection.close()
        return {'sqlite_integrity': 'ok', 'credential_files_removed': removed,
                'hermes_started': False}
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    try:
        result = inspect('/restore')
    except Exception:
        print(json.dumps({'inspection': 'failed'}), flush=True)
        raise SystemExit(1) from None
    print(json.dumps(result), flush=True)
