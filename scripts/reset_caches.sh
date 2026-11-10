#!/bin/bash
# Resets all caches for one engine (report Section 5.4, step 2).
# Usage: scripts/reset_caches.sh pg   |   scripts/reset_caches.sh ch
# Stopping the container empties the engine's own caches (PostgreSQL shared
# buffers; ClickHouse mark cache, query condition cache, ...). Dropping the
# kernel page cache empties the operating-system cache. run.py waits until the
# engine accepts connections again and then runs SELECT 1.
set -e
C="$1"
if [ "$C" != "pg" ] && [ "$C" != "ch" ]; then
  echo "usage: $0 pg|ch" >&2
  exit 1
fi

# ClickHouse writes its query log in batches: flush it so no run is lost.
if [ "$C" = "ch" ]; then
  docker exec ch clickhouse-client --password bench -q "SYSTEM FLUSH LOGS" >/dev/null 2>&1 || true
fi

docker stop "$C" >/dev/null
sync
echo 3 | sudo -n tee /proc/sys/vm/drop_caches >/dev/null
docker start "$C" >/dev/null