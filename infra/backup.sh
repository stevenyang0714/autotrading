#!/usr/bin/env bash
# Local backup (OD-8, ADR-034): the Postgres database and the raw-payload object store, with a
# manifest, into $BACKUP_DIR/<UTC time>/ (default ~/autotrading-backups, outside the repo).
# Read-only against the running stack. Never copies .env or any credential.
#
#   make db-backup            # or: BACKUP_DIR=/Volumes/Backup/autotrading make db-backup
set -euo pipefail

COMPOSE=(docker compose -f infra/docker-compose.yml --project-directory .)
BACKUP_DIR="${BACKUP_DIR:-$HOME/autotrading-backups}"
KEEP_HINT="${KEEP_HINT:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$BACKUP_DIR/$STAMP"

case "$TARGET" in
  "$(pwd)"/*) echo "refusing to back up inside the repository: $TARGET" >&2; exit 1 ;;
esac
mkdir -p "$TARGET"

echo "Backing up the database to $TARGET/db.dump"
"${COMPOSE[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$TARGET/db.dump"

echo "Counting every table's rows for the manifest"
"${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "	"' \
  < infra/table_counts.sql > "$TARGET/table_counts.tsv"

echo "Archiving the raw-payload object store to $TARGET/objects.tar.gz"
"${COMPOSE[@]}" exec -T api python -m autotrading.jobs.backup_objects --archive > "$TARGET/objects.tar.gz"
OBJECTS="$("${COMPOSE[@]}" exec -T api python -m autotrading.jobs.backup_objects --count)"

ALEMBIC="$("${COMPOSE[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "SELECT version_num FROM alembic_version"')"
COMMIT="$(git rev-parse --short HEAD)"
DB_BYTES="$(wc -c < "$TARGET/db.dump" | tr -d ' ')"
ARCHIVE_BYTES="$(wc -c < "$TARGET/objects.tar.gz" | tr -d ' ')"
cat > "$TARGET/manifest.json" <<JSON
{
  "created_at": "$STAMP",
  "git_commit": "$COMMIT",
  "alembic_version": "$ALEMBIC",
  "db_dump_bytes": $DB_BYTES,
  "objects": $OBJECTS,
  "objects_archive_bytes": $ARCHIVE_BYTES,
  "table_counts": "table_counts.tsv"
}
JSON

COUNT="$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
echo "Done: $TARGET ($DB_BYTES bytes of database, $ARCHIVE_BYTES of objects)."
if [ "$COUNT" -gt "$KEEP_HINT" ]; then
  echo "Note: $COUNT backups in $BACKUP_DIR; consider removing the oldest by hand."
fi
