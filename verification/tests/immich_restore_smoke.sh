#!/usr/bin/env bash
# Run ONLY in a disposable PG16 container, with no network or real data mounted.
set -euo pipefail
export POSTGRES_USER=immich POSTGRES_DB=immich POSTGRES_HOST_AUTH_METHOD=trust
export PGUSER=immich PGDATABASE=immich PGHOST=immich-postgres16
export RESTORE_CONFIRM=immich-postgres16-empty
/usr/local/bin/immich-docker-entrypoint.sh postgres -c config_file=/etc/postgresql/postgresql.conf >/tmp/postgres.log 2>&1 &
database_pid=$!
trap 'kill "$database_pid" 2>/dev/null || true' EXIT
for attempt in {1..60}; do
  if pg_isready -q && psql -X -At -c 'SELECT 1' >/dev/null 2>&1; then break; fi
  sleep 1
done
psql -X -At -c 'SELECT 1' >/dev/null
createdb fixture
psql -X -v ON_ERROR_STOP=1 -d fixture <<'SQL'
CREATE EXTENSION vector;
CREATE EXTENSION vchord CASCADE;
CREATE TABLE fixture (id int PRIMARY KEY, label text);
INSERT INTO fixture VALUES (1, 'synthetic'), (2, 'restore');
SQL
mkdir -p /backups/migrations
export RESTORE_FILE=/backups/migrations/fixture.dump
pg_dump -Fc -d fixture -f "$RESTORE_FILE"
RESTORE_SHA256=$(sha256sum "$RESTORE_FILE" | cut -d ' ' -f 1)
export RESTORE_SHA256

expect_failure() {
  if bash /migration/restore.sh > /tmp/result.log 2>&1; then
    echo 'Expected restore refusal, got success' >&2
    exit 1
  fi
}
original_hash=$RESTORE_SHA256
export RESTORE_SHA256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
expect_failure
export RESTORE_SHA256=$original_hash
bash /migration/restore.sh
[[ $(psql -X -At -c 'SELECT count(*) FROM fixture') == 2 ]]
expect_failure
[[ $(psql -X -At -c 'SELECT count(*) FROM fixture') == 2 ]]

# Non-public objects must also trigger refusal.
createdb occupied
export PGDATABASE=occupied
psql -X -v ON_ERROR_STOP=1 -c 'CREATE SCHEMA app; CREATE TABLE app.existing (id int)'
expect_failure
[[ $(psql -X -At -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'") == 0 ]]

# A failed pg_restore subprocess must propagate to the Job, not become a
# successful psql exit. Only list mode uses the real binary in this scenario.
createdb failure
export PGDATABASE=failure
mkdir /tmp/test-bin
real_restore=$(command -v pg_restore)
printf '#!/bin/bash\nif [[ $1 == --list ]]; then exec %q "$@"; fi\nexit 42\n' "$real_restore" > /tmp/test-bin/pg_restore
chmod +x /tmp/test-bin/pg_restore
export PATH=/tmp/test-bin:$PATH
expect_failure
[[ $(psql -X -At -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'") == 0 ]]
echo 'PASS: checksum refusal, synthetic vector restore, populated-target refusal, subprocess failure'
