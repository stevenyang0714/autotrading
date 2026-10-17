#!/usr/bin/env bash
# Restore check (OD-8, ADR-034): restore the latest backup into a throwaway database
# (autotrading_restore_check), compare every table's row count and the alembic version with the
# backup's manifest, and the object archive's entry count with the manifest; the throwaway
# database is dropped on exit, even after a failure. The application database is never touched.
#
#   make db-restore-check     # or: BACKUP=~/autotrading-backups/20261018T010203Z make db-restore-check
set -euo pipefail

COMPOSE=(docker compose -f infra/docker-compose.yml --project-directory .)
BACKUP_DIR="${BACKUP_DIR:-$HOME/autotrading-backups}"
BACKUP="${BACKUP:-$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)}"
CHECK_DB=autotrading_restore_check

if [ -z "$BACKUP" ] || [ ! -f "$BACKUP/db.dump" ]; then
  echo "no backup found in $BACKUP_DIR (run make db-backup first)" >&2
  exit 1
fi
echo "Checking $BACKUP"

RESTORED="$(mktemp)"
drop_check_db() {
  "${COMPOSE[@]}" exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -q -c 'DROP DATABASE IF EXISTS $CHECK_DB'" || true
  rm -f "$RESTORED"
}
trap drop_check_db EXIT

"${COMPOSE[@]}" exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -q -c 'DROP DATABASE IF EXISTS $CHECK_DB' -c 'CREATE DATABASE $CHECK_DB'"
# TimescaleDB hypertables restore between timescaledb_pre_restore() and _post_restore().
"${COMPOSE[@]}" exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d $CHECK_DB -q -c 'CREATE EXTENSION IF NOT EXISTS timescaledb' -c 'SELECT timescaledb_pre_restore()'" > /dev/null
"${COMPOSE[@]}" exec -T db sh -c "pg_restore -U \"\$POSTGRES_USER\" -d $CHECK_DB --no-owner --exit-on-error" < "$BACKUP/db.dump"
"${COMPOSE[@]}" exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d $CHECK_DB -q -c 'SELECT timescaledb_post_restore()'" > /dev/null
"${COMPOSE[@]}" exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d $CHECK_DB -At -F '	'" \
  < infra/table_counts.sql > "$RESTORED"
ALEMBIC="$("${COMPOSE[@]}" exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d $CHECK_DB -At -c 'SELECT version_num FROM alembic_version'")"
status=0
if diff -u "$BACKUP/table_counts.tsv" "$RESTORED"; then
  echo "Row counts: $(wc -l < "$RESTORED" | tr -d ' ') tables identical"
else
  echo "Row counts differ" >&2
  status=1
fi
EXPECTED_ALEMBIC="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["alembic_version"])' "$BACKUP/manifest.json")"
if [ "$ALEMBIC" = "$EXPECTED_ALEMBIC" ]; then
  echo "Alembic version: $ALEMBIC"
else
  echo "Alembic version differs: $ALEMBIC, manifest $EXPECTED_ALEMBIC" >&2
  status=1
fi
ENTRIES="$(tar -tzf "$BACKUP/objects.tar.gz" | wc -l | tr -d ' ')"
EXPECTED_OBJECTS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["objects"]["objects"])' "$BACKUP/manifest.json")"
if [ "$ENTRIES" = "$EXPECTED_OBJECTS" ]; then
  echo "Objects: $ENTRIES archived, as the manifest"
else
  echo "Objects differ: $ENTRIES archived, manifest $EXPECTED_OBJECTS" >&2
  status=1
fi
exit $status
