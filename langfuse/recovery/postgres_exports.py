"""Fixed PostgreSQL stream producers for the guarded recovery runner.

Command construction only: importing/building never executes kubectl or exports
anything. The runner must establish one writer-excluded point, identity custody,
a recipient, bounded encrypted stream handling and complete restore acceptance.
Never invoke these commands directly against production as a preflight check.
The full application DB contains confidential authentication/project records;
omitting datastore role passwords does not make any exported stream nonsecret.
"""
from dataclasses import dataclass
import re
from typing import Mapping

IMAGE = 'postgres:18@sha256:2ea8630df176ad090ec92136dee850397c5af8781e4bcf2e4162593691c61bbc'
POD = 'langfuse-postgresql-0'
CONTAINER = 'postgresql'

# Password values stay in the existing container's configured native interface;
# no passwords in argv, host env, receipts or logs. Do not enable shell tracing.
_PREAMBLE = ('set +x; set -eu; '
             'test "${POSTGRES_DB:-}" = langfuse; test -n "${POSTGRES_PASSWORD:-}"; '
             'export PGPASSWORD="$POSTGRES_PASSWORD"; '
             'export PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=600000 -c lock_timeout=5000"; ')
DUMP_SHELL = _PREAMBLE + ('exec pg_dump --host=127.0.0.1 --username=postgres '
                         '--dbname="$POSTGRES_DB" --no-password --format=custom '
                         '--create --lock-wait-timeout=5s')
GLOBALS_SHELL = _PREAMBLE + ('exec pg_dumpall --host=127.0.0.1 --username=postgres '
                            '--database="$POSTGRES_DB" --no-password '
                            '--globals-only --no-role-passwords')


@dataclass(frozen=True)
class Export:
    component: str
    format: str
    source_uid: str
    source_image: str
    container_argv: tuple[str, ...]
    kubectl_argv: tuple[str, ...]
    complete_archive_validator: tuple[str, ...] | None
    includes_datastore_role_passwords: bool = False


def build(source: Mapping[str, str]) -> tuple[Export, Export]:
    """Bind fixed commands to one pinned, Ready, non-deleting workload snapshot.

    UID metadata is for the runner's optimistic pre/post checks; kubectl exec has
    no UID precondition. A builder result alone never establishes writer safety.
    """
    if (source.get('name') != POD or source.get('container') != CONTAINER
            or source.get('image') not in (IMAGE, 'docker.io/' + IMAGE) or source.get('ready') != 'true'
            or source.get('phase') != 'Running' or source.get('deleting') != '<none>'
            or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', source.get('uid', ''))):
        raise ValueError('PostgreSQL source snapshot is not admitted')
    prefix = ('kubectl', '--request-timeout=30s', '-n', 'langfuse', 'exec', POD, '-c', CONTAINER, '--')
    exports = []
    for component, format_name, shell, validator in [
        ('postgres-database', 'postgres-custom', DUMP_SHELL,
         ('pg_restore', '--file=/dev/null')),
        ('postgres-globals', 'postgres-globals-without-role-passwords', GLOBALS_SHELL, None),
    ]:
        argv = ('/bin/sh', '-ec', shell)
        exports.append(Export(component, format_name, source['uid'], source['image'], argv,
                              prefix + argv, validator))
    return exports[0], exports[1]
