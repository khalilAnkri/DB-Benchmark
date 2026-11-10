#!/bin/bash
# Records storage size per table in both engines, and checks that design D is
# physically sorted on l_shipdate in PostgreSQL.
# Usage: scripts/sizes.sh 1      (the scale factor currently loaded)
# Output: results/sizes_sf<SF>.txt
set -e
SF=${1:?usage: scripts/sizes.sh <scale factor>}
cd "$(dirname "$0")/.."
OUT=results/sizes_sf$SF.txt

{
echo "=== Scale factor $SF, $(date -Iseconds) ==="

docker compose stop clickhouse >/dev/null 2>&1 || true
docker compose up -d postgres >/dev/null
until docker exec pg pg_isready -U postgres -q; do sleep 1; done

echo "--- PostgreSQL: physical order of l_shipdate (correlation, 1 = sorted)"
docker exec pg psql -U postgres -c "
  SELECT schemaname AS design, round(correlation::numeric, 3) AS correlation
  FROM pg_stats WHERE tablename = 'lineitem' AND attname = 'l_shipdate'
  ORDER BY schemaname;"

echo "--- PostgreSQL: size per table (heap = table only, total = with indexes)"
docker exec pg psql -U postgres -c "
  SELECT n.nspname || '.' || c.relname AS tbl,
         pg_relation_size(c.oid)                         AS heap_bytes,
         pg_size_pretty(pg_relation_size(c.oid))         AS heap,
         pg_total_relation_size(c.oid)                   AS total_bytes,
         pg_size_pretty(pg_total_relation_size(c.oid))   AS total
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname IN ('b', 'd') AND c.relkind = 'r'
  ORDER BY 1;"
docker compose stop postgres >/dev/null

docker compose up -d clickhouse >/dev/null
until docker exec ch clickhouse-client --password bench -q "SELECT 1" >/dev/null 2>&1; do sleep 1; done

echo "--- ClickHouse: size per table"
docker exec ch clickhouse-client --password bench -q "
  SELECT database || '.' || table AS tbl,
         sum(data_compressed_bytes)                      AS compressed_bytes,
         formatReadableSize(sum(data_compressed_bytes))  AS compressed,
         sum(data_uncompressed_bytes)                    AS uncompressed_bytes,
         formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed,
         count()                                         AS parts
  FROM system.parts WHERE active AND database IN ('b', 'd')
  GROUP BY database, table ORDER BY tbl FORMAT PrettyCompactNoEscapes"

echo "--- ClickHouse: LINEITEM columns used by the queries (compressed)"
docker exec ch clickhouse-client --password bench -q "
  SELECT name, formatReadableSize(data_compressed_bytes) AS compressed,
         formatReadableSize(data_uncompressed_bytes) AS uncompressed
  FROM system.columns WHERE database = 'b' AND table = 'lineitem'
  ORDER BY data_compressed_bytes DESC FORMAT PrettyCompactNoEscapes"
docker compose stop clickhouse >/dev/null
} | tee "$OUT"

echo "Saved to $OUT"