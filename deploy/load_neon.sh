#!/usr/bin/env bash
# Copies the local TenderLens database (the docker-compose Postgres) into an EMPTY hosted
# Postgres, such as the Neon database connected to the Vercel project, then stores the
# connection as the GitHub secret the crawl workflow uses. Raw pages are copied only where
# a tender or quarantine row points at them (the RAW_DETAIL_RETENTION_DAYS rule), which
# keeps the copy around 85 MB. The local database is only read.
#
#   bash deploy/load_neon.sh
#
# It asks for the connection string: Vercel > Storage > your Neon database > Quickstart >
# .env.local > Show secret > the DATABASE_URL_UNPOOLED value (without the quotes).
set -euo pipefail
C=${POSTGRES_CONTAINER:-tenderlens-postgres-1}
REPO=${GITHUB_REPO:-devreddy1015/tenderlens}

if [ -z "${TARGET_DATABASE_URL:-}" ]; then
  read -rsp "Paste DATABASE_URL_UNPOOLED (input is hidden): " TARGET_DATABASE_URL
  echo
fi
TARGET_DATABASE_URL=${TARGET_DATABASE_URL//\"/}
case "$TARGET_DATABASE_URL" in
  postgres://* | postgresql://*) ;;
  *) echo "That does not look like a postgresql:// URL."; exit 1 ;;
esac
if [[ "$TARGET_DATABASE_URL" == *-pooler.* ]]; then
  echo "That is the pooled URL. Use DATABASE_URL_UNPOOLED (host without '-pooler')."
  exit 1
fi

local_db() { docker exec "$C" sh -c "$1"; }
target() { docker exec -e U="$TARGET_DATABASE_URL" "$C" sh -c "$1"; }
trap 'local_db "rm -f /tmp/tl.dump /tmp/tl_raw_page.copy /tmp/tl_restore.list"' EXIT

echo "1/7 Checking the target database is empty"
tables=$(target 'psql "$U" -Atc "select count(*) from pg_tables where schemaname = '\''public'\''"')
if [ "$tables" != 0 ]; then
  echo "It already has $tables tables. Stopping so nothing is overwritten."
  exit 1
fi

echo "2/7 Exporting the local database"
# --no-toast-compression: the target may not support lz4 (raw_page.body uses it locally).
local_db 'pg_dump -U tenderlens -d tenderlens -Fc --no-owner --no-privileges --no-toast-compression --exclude-table-data=raw_page -f /tmp/tl.dump'
local_db 'psql -U tenderlens -d tenderlens -q -v ON_ERROR_STOP=1 -c "\copy (select * from raw_page where id in (select raw_page_id from tender where raw_page_id is not null union select raw_page_id from quarantine where raw_page_id is not null)) to /tmp/tl_raw_page.copy"'
# Managed Postgres does not let a normal role comment on extensions; skip that one entry.
local_db 'pg_restore -l /tmp/tl.dump | grep -v "COMMENT - EXTENSION" > /tmp/tl_restore.list'

echo "3/7 Creating tables"
target 'pg_restore -d "$U" -L /tmp/tl_restore.list --no-owner --no-privileges --exit-on-error --section=pre-data /tmp/tl.dump'

echo "4/7 Copying data (the raw pages are about 265 MB to upload; this takes a few minutes)"
target 'pg_restore -d "$U" -L /tmp/tl_restore.list --no-owner --no-privileges --exit-on-error --section=data /tmp/tl.dump'
target 'psql "$U" -q -v ON_ERROR_STOP=1 -c "\copy raw_page from /tmp/tl_raw_page.copy"'
# Crawl outcomes may point at raw pages that were not copied (ON DELETE SET NULL semantics).
target 'psql "$U" -q -v ON_ERROR_STOP=1 -c "update crawl_item set raw_page_id = null where raw_page_id is not null and raw_page_id not in (select id from raw_page)"'

echo "5/7 Building indexes and constraints"
target 'pg_restore -d "$U" -L /tmp/tl_restore.list --no-owner --no-privileges --exit-on-error --section=post-data /tmp/tl.dump'
target 'psql "$U" -q -v ON_ERROR_STOP=1 -c "analyze"'

echo "6/7 Saving the connection as the GitHub secret DATABASE_URL (for the crawler)"
printf %s "$TARGET_DATABASE_URL" | gh secret set DATABASE_URL --repo "$REPO"

echo "7/7 Checking"
target 'psql "$U" -Atc "select '\''tenders: '\'' || count(*) from tender" -c "select '\''size: '\'' || pg_size_pretty(pg_database_size(current_database()))"'
echo "Done. Tell Claude: loaded"
