#!/bin/bash
# Runs the 4 queries on each engine (design B), one engine at a time.
# Usage: scripts/check_queries.sh 10      (scale factor loaded; default 1)
# At SF 1 the TPC-H reference answers are printed too.
SF=${1:-1}
cd "$(dirname "$0")/.."
docker inspect pg ch --format '{{.Name}} OOMKilled={{.State.OOMKilled}}' 2>/dev/null
docker compose stop >/dev/null 2>&1

if [ "$SF" = "1" ]; then
  echo "################ TPC-H reference answers (SF 1) ################"
  for q in q1 q6 q12 q14; do echo "--- $q"; cat sql/answers/$q.out; done
fi

echo "################ PostgreSQL ################"
docker compose up -d postgres >/dev/null
until docker exec pg pg_isready -U postgres -q; do sleep 1; done
for q in q1 q6 q12 q14; do
  echo "--- $q"
  docker exec -i -e PGOPTIONS='-c search_path=b' pg psql -U postgres -q < sql/postgres/$q.sql
done
docker compose stop postgres >/dev/null

echo "################ ClickHouse ################"
docker compose up -d clickhouse >/dev/null
until docker exec ch clickhouse-client --password bench -q "SELECT 1" >/dev/null 2>&1; do sleep 1; done
for q in q1 q6 q12 q14; do
  echo "--- $q"
  docker exec -i ch clickhouse-client --password bench --database b \
    --format PrettyCompact --multiquery < sql/clickhouse/$q.sql
done
docker compose stop clickhouse >/dev/null
