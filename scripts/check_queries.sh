#!/bin/bash
# Runs the 4 queries on both engines (design B) and prints them next to the TPC-H answers.
cd "$(dirname "$0")/.."
docker compose up -d postgres clickhouse >/dev/null
until docker exec pg pg_isready -U postgres -q; do sleep 1; done
until docker exec ch clickhouse-client --password bench -q "SELECT 1" >/dev/null 2>&1; do sleep 1; done
for q in q1 q6 q12 q14; do
  echo "################ $q ################"
  echo "--- TPC-H reference (SF 1)";  cat sql/answers/$q.out
  echo "--- PostgreSQL"
  docker exec -i -e PGOPTIONS='-c search_path=b' pg psql -U postgres -q < sql/postgres/$q.sql
  echo "--- ClickHouse"
  docker exec -i ch clickhouse-client --password bench --database b \
    --format PrettyCompact --multiquery < sql/clickhouse/$q.sql
done
docker compose stop >/dev/null
