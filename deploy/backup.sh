#!/usr/bin/env bash
# Nightly backup: Postgres dump + uploaded documents, verified, then copied off-site.
#
#   ./deploy/backup.sh              (make prod-backup; cron: see docs/DEPLOY.md "Backups")
#
# 1. pg_dump -Fc of the whole database (tenders, users, workspaces, Copilot chunks + vectors)
# 2. tar.gz of the media volume (uploaded tender PDFs)
# 3. verify: pg_restore --list must read the dump and list the core tables; tar must list
#    the archive; sha256 sums written next to both
# 4. off-site copy with rclone (in its own container: nothing to install on the host) to
#    BACKUP_REMOTE, configured by RCLONE_CONFIG_<NAME>_* variables in .env (S3, R2, B2, ...)
# 5. retention: KEEP_DAYS locally, REMOTE_KEEP_DAYS off-site
# 6. optional BACKUP_PING_URL (e.g. healthchecks.io) is pinged on success, so a backup that
#    silently stops running raises an alert.
#
# Settings come from the environment or .env: BACKUP_DIR (backups), KEEP_DAYS (7),
# BACKUP_REMOTE (empty: local only), REMOTE_KEEP_DAYS (30), BACKUP_PING_URL.
# COMPOSE overrides how the stack is reached (default: the production compose file);
# PG_CONTAINER=<name> talks to a plain `docker run` Postgres instead.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
envval() {  # read one variable: environment first, then .env
  local v="${!1:-}"
  if [ -z "$v" ] && [ -f "$ENV_FILE" ]; then
    v=$(grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//')
  fi
  printf '%s' "${v:-${2:-}}"
}

COMPOSE="${COMPOSE:-docker compose -f deploy/compose.prod.yml --env-file $ENV_FILE}"
DIR="$(envval BACKUP_DIR backups)"
KEEP_DAYS="$(envval KEEP_DAYS 7)"
REMOTE="$(envval BACKUP_REMOTE)"
REMOTE_KEEP_DAYS="$(envval REMOTE_KEEP_DAYS 30)"
PING_URL="$(envval BACKUP_PING_URL)"
RCLONE_IMAGE="${RCLONE_IMAGE:-rclone/rclone:1.71}"
PGUSER=tenderlens PGDB="${PGDB:-tenderlens}"

pg() {  # run a command in the Postgres container, stdin attached
  if [ -n "${PG_CONTAINER:-}" ]; then docker exec -i "$PG_CONTAINER" "$@"
  else $COMPOSE exec -T postgres "$@"; fi
}
log() { echo "$(date -Iseconds) $*"; }
fail() { log "BACKUP FAILED: $*" >&2; [ -n "$PING_URL" ] && curl -fsS -m 10 "$PING_URL/fail" >/dev/null || true; exit 1; }
trap 'fail "line $LINENO"' ERR

mkdir -p "$DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
DUMP="$DIR/tenderlens-$STAMP.dump"
MEDIA="$DIR/media-$STAMP.tar.gz"

# 1. Database. A half-written file never gets the final name.
pg pg_dump -U "$PGUSER" -d "$PGDB" -Fc -Z 6 > "$DUMP.partial"
mv "$DUMP.partial" "$DUMP"

# 3a. The dump must be readable and contain the tables that matter.
TOC=$(pg pg_restore --list < "$DUMP") || fail "pg_restore cannot read $DUMP"
for table in tender auth_user organization django_migrations; do
  grep -q "TABLE DATA public $table " <<<"$TOC" || fail "$DUMP has no data for $table"
done

# 2. Uploaded documents (skipped with PG_CONTAINER, i.e. outside the compose stack).
if [ -z "${PG_CONTAINER:-}" ]; then
  $COMPOSE exec -T web tar -C /app/media -czf - . > "$MEDIA.partial"
  mv "$MEDIA.partial" "$MEDIA"
  tar -tzf "$MEDIA" > /dev/null || fail "$MEDIA is not a readable archive"
else
  MEDIA=""
fi

# 3b. Checksums, checked again by restore.sh before it touches anything.
(cd "$DIR" && sha256sum "$(basename "$DUMP")" ${MEDIA:+"$(basename "$MEDIA")"} > "tenderlens-$STAMP.sha256")
log "backup ok: $DUMP ($(du -h "$DUMP" | cut -f1))${MEDIA:+, $MEDIA ($(du -h "$MEDIA" | cut -f1))}"

# 4. Off-site. Only the RCLONE_* lines of .env reach the rclone container.
if [ -n "$REMOTE" ]; then
  RCLONE_ENV=$(mktemp)
  trap 'rm -f "$RCLONE_ENV"' EXIT
  chmod 600 "$RCLONE_ENV"
  { env | grep -E '^RCLONE_' || true; [ -f "$ENV_FILE" ] && grep -E '^RCLONE_' "$ENV_FILE" || true; } > "$RCLONE_ENV"
  rclone() {
    docker run --rm -u "$(id -u):$(id -g)" --env-file "$RCLONE_ENV" -v "$(realpath "$DIR")":/backups:ro \
      ${RCLONE_EXTRA_MOUNT:+-v "$RCLONE_EXTRA_MOUNT"} "$RCLONE_IMAGE" "$@"
  }
  FILES=("$(basename "$DUMP")" "tenderlens-$STAMP.sha256")
  [ -n "$MEDIA" ] && FILES+=("$(basename "$MEDIA")")
  INCLUDES=()
  for f in "${FILES[@]}"; do INCLUDES+=(--include "$f"); done
  rclone copy /backups "$REMOTE/$STAMP" "${INCLUDES[@]}" --retries 5
  # Re-read what landed off-site (size + hash where the backend has one).
  rclone check /backups "$REMOTE/$STAMP" "${INCLUDES[@]}" --one-way
  rclone delete "$REMOTE" --min-age "${REMOTE_KEEP_DAYS}d"
  rclone rmdirs "$REMOTE" --leave-root
  log "off-site ok: $REMOTE/$STAMP"
fi

# 5. Local retention.
find "$DIR" -maxdepth 1 \( -name 'tenderlens-*' -o -name 'media-*' \) -mtime +"$KEEP_DAYS" -delete

[ -n "$PING_URL" ] && curl -fsS -m 10 "$PING_URL" >/dev/null || true
