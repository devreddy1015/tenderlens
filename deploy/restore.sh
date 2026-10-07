#!/usr/bin/env bash
# Restore a backup made by deploy/backup.sh. Two modes:
#
#   ./deploy/restore.sh check backups/tenderlens-20261007-031500.dump
#       Restore drill (make restore-check): restores into a scratch database next to the
#       live one, prints row counts, drops the scratch database. Touches nothing else.
#       Run it monthly, and after any change to the backup setup.
#
#   ./deploy/restore.sh live backups/tenderlens-20261007-031500.dump [media-....tar.gz] --yes
#       Disaster recovery: stops the app containers, restores into a new database, swaps it
#       in by renaming (the old one is kept as tenderlens_before_<stamp> until you drop it),
#       unpacks the media archive, starts the app again.
#
# A dump fetched from off-site first: docker run --rm -v "$PWD/backups:/backups" --env-file
# <(grep ^RCLONE_ .env) rclone/rclone:1.71 copy "$BACKUP_REMOTE/<stamp>" /backups
# COMPOSE and PG_CONTAINER work as in backup.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-}" DUMP="${2:-}"
[[ "$MODE" =~ ^(check|live)$ && -f "$DUMP" ]] || {
  sed -n '2,15p' "$0"; exit 2; }
shift 2
MEDIA="" YES=""
for a in "$@"; do case "$a" in --yes) YES=1 ;; *) MEDIA="$a" ;; esac; done

ENV_FILE="${ENV_FILE:-.env}"
COMPOSE="${COMPOSE:-docker compose -f deploy/compose.prod.yml --env-file $ENV_FILE}"
PGUSER=tenderlens PGDB="${PGDB:-tenderlens}"
STAMP=$(date +%Y%m%d%H%M%S)
pg() {
  if [ -n "${PG_CONTAINER:-}" ]; then docker exec -i "$PG_CONTAINER" "$@"
  else $COMPOSE exec -T postgres "$@"; fi
}
psql_() { pg psql -U "$PGUSER" -d "${DB:-postgres}" -v ON_ERROR_STOP=1 -qAt "$@"; }
log() { echo "$(date -Iseconds) $*"; }

# Checksums written by backup.sh, when present next to the dump.
SUMS="${DUMP%.dump}.sha256"
if [ -f "$SUMS" ]; then
  (cd "$(dirname "$DUMP")" && sha256sum --check --ignore-missing --quiet "$(basename "$SUMS")")
  log "checksums ok"
fi

restore_into() {  # $1 = new database name
  psql_ -c "CREATE DATABASE \"$1\" OWNER $PGUSER"
  # pg_restore runs with an empty search_path, so a materialized view whose query names a
  # table without its schema (tender_word) cannot be refreshed during the restore. Restore
  # everything except materialized-view data, then refresh those views normally.
  pg pg_restore --list < "$DUMP" | grep -v 'MATERIALIZED VIEW DATA' \
    | pg sh -c "cat > /tmp/restore-$1.list"
  # --no-owner: objects belong to the connecting role. The dump creates the extensions
  # (vector, pg_trgm) itself.
  pg pg_restore -U "$PGUSER" -d "$1" --no-owner --exit-on-error -L "/tmp/restore-$1.list" < "$DUMP"
  pg rm -f "/tmp/restore-$1.list"
  DB="$1" psql_ -c "DO \$\$ DECLARE r record; BEGIN
      FOR r IN SELECT schemaname, matviewname FROM pg_matviews LOOP
        EXECUTE format('REFRESH MATERIALIZED VIEW %I.%I', r.schemaname, r.matviewname);
      END LOOP; END \$\$"
}
counts() {
  DB="$1" psql_ -F ' ' -c "
    SELECT 'tenders', count(*) FROM tender UNION ALL
    SELECT 'users', count(*) FROM auth_user UNION ALL
    SELECT 'organizations', count(*) FROM organization UNION ALL
    SELECT 'copilot_chunks', count(*) FROM copilot_chunk UNION ALL
    SELECT 'migrations', count(*) FROM django_migrations"
}

if [ "$MODE" = check ]; then
  SCRATCH="restore_check_$STAMP"
  trap 'psql_ -c "DROP DATABASE IF EXISTS \"$SCRATCH\"" >/dev/null 2>&1 || true' EXIT
  log "restoring $DUMP into scratch database $SCRATCH"
  restore_into "$SCRATCH"
  counts "$SCRATCH" | sed 's/^/  restored: /'
  [ "$(counts "$SCRATCH" | awk '$1=="tenders"{print $2}')" -gt 0 ] || { log "no tenders restored"; exit 1; }
  log "restore check ok (scratch database dropped)"
  exit 0
fi

[ -n "$YES" ] || { echo "live restore replaces the production database; add --yes" >&2; exit 2; }
APP="web worker worker-crawl beat"
log "stopping $APP"
$COMPOSE stop $APP
NEW="${PGDB}_restore_$STAMP" OLD="${PGDB}_before_$STAMP"
restore_into "$NEW"
counts "$NEW" | sed 's/^/  restored: /'
psql_ -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$PGDB' AND pid <> pg_backend_pid()" >/dev/null
psql_ -c "ALTER DATABASE \"$PGDB\" RENAME TO \"$OLD\""
psql_ -c "ALTER DATABASE \"$NEW\" RENAME TO \"$PGDB\""
log "database swapped; the previous one is kept as $OLD (DROP DATABASE it once you are happy)"
if [ -n "$MEDIA" ]; then
  $COMPOSE run --rm --no-deps -T --entrypoint tar web -C /app/media -xzf - < "$MEDIA"
  log "media restored from $MEDIA"
fi
$COMPOSE up -d --wait
log "live restore done"
