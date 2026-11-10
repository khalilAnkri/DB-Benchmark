#!/bin/bash
# Manual load test: loads one scale factor into both engines and prints checks.
# Usage: scripts/load_test.sh 1
set -e
SF=${1:-1}
cd "$(dirname "$0")/.."

echo "=== Fresh containers ==="
docker rm -f pg ch >/dev/null 2>&1 || true

echo "=== PostgreSQL, SF $SF ==="
docker compose up -d postgres
until docker exec pg pg_isready -U postgres -q; do sleep 1; done
docker inspect pg --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
PG="docker exec -i pg psql -U postgres -v ON_ERROR_STOP=1 -q"

$PG < sql/postgres/schema.sql
echo "--- COPY";          time $PG \
  -c "COPY b.lineitem FROM '/data/sf$SF/lineitem.tbl' WITH (DELIMITER '|')" \
  -c "COPY b.orders   FROM '/data/sf$SF/orders.tbl'   WITH (DELIMITER '|')" \
  -c "COPY b.part     FROM '/data/sf$SF/part.tbl'     WITH (DELIMITER '|')"
echo "--- keys + VACUUM"; time $PG < sql/postgres/post_load.sql
echo "--- design D";      time $PG < sql/postgres/design_D.sql

$PG -c "SELECT 'b.lineitem' AS t, count(*), sum(l_quantity), sum(l_extendedprice) FROM b.lineitem
        UNION ALL
        SELECT 'd.lineitem', count(*), sum(l_quantity), sum(l_extendedprice) FROM d.lineitem
        UNION ALL
        SELECT 'b.orders', count(*), NULL, NULL FROM b.orders
        UNION ALL
        SELECT 'b.part',   count(*), NULL, NULL FROM b.part"
docker compose stop postgres

echo "=== ClickHouse, SF $SF ==="
docker compose up -d clickhouse
until docker exec ch clickhouse-client --password bench -q "SELECT 1" >/dev/null 2>&1; do sleep 1; done
docker inspect ch --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
CH="docker exec -i ch clickhouse-client --password bench"

$CH --multiquery < sql/clickhouse/schema.sql
echo "--- INSERT"; time (for t in lineitem orders part; do
  $CH --format_csv_delimiter='|' --input_format_csv_trim_whitespaces=0 \
      --query "INSERT INTO b.$t FORMAT CSV" < data/sf$SF/$t.tbl
done)
echo "--- OPTIMIZE"; time $CH --multiquery -q \
  "OPTIMIZE TABLE b.lineitem FINAL; OPTIMIZE TABLE b.orders FINAL; OPTIMIZE TABLE b.part FINAL"
echo "--- design D"; time $CH --multiquery < sql/clickhouse/design_D.sql

$CH -q "SELECT 'b.lineitem' AS t, count(), sum(l_quantity), sum(l_extendedprice) FROM b.lineitem
        UNION ALL
        SELECT 'd.lineitem', count(), sum(l_quantity), sum(l_extendedprice) FROM d.lineitem
        FORMAT PrettyCompact"
$CH -q "SELECT 'b.orders' AS t, count() FROM b.orders
        UNION ALL
        SELECT 'b.part', count() FROM b.part FORMAT PrettyCompact"
docker compose stop clickhouse
echo "=== Done ==="
