#!/usr/bin/env bash
# Mounted by the manually created restore Job; never an ArgoCD hook.
set -euo pipefail
umask 077

fail() { echo "$1" >&2; exit 1; }
[[ ${PGHOST:-} == immich-postgres16 ]] || fail 'Refusing unexpected restore host'
[[ ${RESTORE_CONFIRM:-} == immich-postgres16-empty ]] || fail 'Restore confirmation missing'
[[ ${RESTORE_FILE:-} == /backups/migrations/*.dump ]] || fail 'Archive must be in migration backups'
[[ $RESTORE_FILE != *'/../'* && $RESTORE_FILE != *'/./'* ]] || fail 'Invalid archive path'
[[ ${RESTORE_SHA256:-} =~ ^[a-f0-9]{64}$ ]] || fail 'Expected SHA256 is required'
test -s "$RESTORE_FILE" || fail 'Archive is missing or empty'
printf '%s  %s\n' "$RESTORE_SHA256" "$RESTORE_FILE" | sha256sum --check --status
pg_restore --list "$RESTORE_FILE" >/dev/null

version=$(psql -X -At -v ON_ERROR_STOP=1 -c 'SHOW server_version_num')
[[ $version =~ ^16[0-9]{4}$ ]] || fail 'Destination must be PostgreSQL 16'
# Serialize this helper and inspect every non-system schema, not only public.
# The operator must also keep the application stopped / disconnected from target.
psql -X -v ON_ERROR_STOP=1 <<'SQL'
SELECT pg_advisory_lock(164375, 16);
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname NOT LIKE 'pg_toast%'
      AND n.nspname NOT LIKE 'pg_temp_%'
  ) OR EXISTS (SELECT 1 FROM pg_largeobject_metadata)
    OR EXISTS (SELECT 1 FROM pg_extension WHERE extname <> 'plpgsql')
    OR EXISTS (SELECT 1 FROM pg_namespace WHERE nspname NOT IN
      ('pg_catalog', 'information_schema', 'public') AND nspname NOT LIKE 'pg_toast%'
      AND nspname NOT LIKE 'pg_temp_%')
    OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
      WHERE n.nspname = 'public')
    OR EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
      WHERE n.nspname = 'public') THEN
    RAISE EXCEPTION 'Destination is not empty; refusing restore';
  END IF;
END $$;
\! pg_restore --exit-on-error --single-transaction --no-owner --no-privileges --dbname="$PGDATABASE" "$RESTORE_FILE" > /tmp/restore.log 2>&1
\if :SHELL_ERROR
  \echo 'Restore failed. SQL diagnostics withheld; inspect privately after authorization.'
  DO $$ BEGIN RAISE EXCEPTION 'Restore command failed'; END $$;
\endif
SQL
# Do not emit dump SQL or source rows to logs.
psql -X -v ON_ERROR_STOP=1 -c 'ANALYZE' >/dev/null
echo 'Restore completed; validate extensions, indexes and application data before cutover.'
