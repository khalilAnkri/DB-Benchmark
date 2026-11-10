#!/usr/bin/env python3
"""Measurement runner for the PostgreSQL vs ClickHouse experiment.

Implements the procedure of report Section 5.4 for one scale factor:
  cold runs (design B only) -> reset caches -> warm-up (discarded) ->
  warm runs in round-robin order -> instrumented run (plans saved, not timed).

One engine runs at a time. Every timed run becomes one row in results/runs.csv:
wall-clock time from submission until the full result is received, and the
bytes read from storage by the container during that run (cgroup io.stat).

Usage examples (from the project root, with the virtual environment active):
  python scripts/run.py --sf 1 --tag pilot --cold 3 --rounds 3
  python scripts/run.py --sf 1 --tag final
  python scripts/run.py --sf 4 --tag memcheck --designs B --mem-limit-gb 4 \
      --compose-file docker-compose.yml --compose-file docker-compose.mem4g.yml
"""
import argparse
import csv
import datetime as dt
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
import logging; logging.getLogger("clickhouse_connect").setLevel(logging.CRITICAL)

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
PLANS = RESULTS / "plans"
ENV = ROOT / "env"

PASSWORD = "bench"
CONTAINER = {"pg": "pg", "ch": "ch"}
SERVICE = {"pg": "postgres", "ch": "clickhouse"}
SQL_DIR = {"pg": "postgres", "ch": "clickhouse"}
LINEITEM_ROWS_SF1 = 6_001_215

RUN_FIELDS = ["timestamp", "tag", "engine", "design", "sf", "mem_limit_gb", "query",
              "cache", "run_no", "seconds", "io_read_bytes", "rows_returned", "query_id"]
RES_FIELDS = ["timestamp", "tag", "engine", "sf", "cpu_usage_usec", "memory_current_bytes"]
CHLOG_FIELDS = ["query_id", "read_rows", "read_bytes", "query_duration_ms", "memory_usage"]


# --------------------------------------------------------------------------- helpers

def now():
    return dt.datetime.now().isoformat(timespec="milliseconds")


def sh(cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def compose(args, files):
    cmd = ["docker", "compose"]
    for f in files:
        cmd += ["-f", f]
    res = sh(cmd + args, check=False)
    if res.returncode != 0:
        sys.exit(f"docker compose {' '.join(args)} failed:\n{res.stderr}")


def cgroup_dir(container):
    cid = sh(["docker", "inspect", "-f", "{{.Id}}", container]).stdout.strip()
    path = Path(f"/sys/fs/cgroup/system.slice/docker-{cid}.scope")
    if not path.exists():
        sys.exit(f"cgroup directory not found: {path}\n"
                 "Check that Docker uses cgroup v2 with the systemd driver.")
    return path


def read_rbytes(cg):
    """Total bytes read from storage by the container since it started."""
    total = 0
    try:
        for line in (cg / "io.stat").read_text().splitlines():
            for field in line.split()[1:]:
                key, _, value = field.partition("=")
                if key == "rbytes":
                    total += int(value)
    except (FileNotFoundError, OSError):
        return None
    return total


def load_sql(engine, query):
    text = (ROOT / "sql" / SQL_DIR[engine] / f"{query}.sql").read_text().strip()
    return text.rstrip(";").strip()


def append_csv(path, fields, row):
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


# --------------------------------------------------------------------------- engines

class PG:
    def __init__(self, design):
        import psycopg
        search_path = "b" if design == "B" else "d,b"
        # prepare_threshold=None: no automatic prepared statements, so every run is planned
        # the same way as in psql.
        self.conn = psycopg.connect(host="localhost", port=5432, user="postgres",
                                    password=PASSWORD, dbname="postgres", autocommit=True,
                                    prepare_threshold=None,
                                    options=f"-c search_path={search_path}")

    def run(self, sql, query_id=None):
        with self.conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall() if cur.description else []

    def close(self):
        self.conn.close()


class CH:
    def __init__(self, design):
        import clickhouse_connect
        self.client = clickhouse_connect.get_client(
            host="localhost", port=8123, username="default", password=PASSWORD,
            database="b" if design == "B" else "d", compress=False)

    def run(self, sql, query_id=None):
        settings = {"query_id": query_id} if query_id else None
        return self.client.query(sql, settings=settings).result_rows

    def close(self):
        self.client.close()


def connect(engine, design, timeout=180):
    """Open a new connection and run SELECT 1, retrying until the engine accepts queries."""
    start = time.time()
    while True:
        try:
            conn = PG(design) if engine == "pg" else CH(design)
            conn.run("SELECT 1")
            return conn
        except Exception as exc:  # engine still starting
            if time.time() - start > timeout:
                sys.exit(f"{engine} did not accept connections within {timeout}s: {exc}")
            time.sleep(1)


def reset_caches(engine):
    res = sh(["bash", str(ROOT / "scripts" / "reset_caches.sh"), CONTAINER[engine]], check=False)
    if res.returncode != 0:
        sys.exit(f"Cache reset failed:\n{res.stderr}\n"
                 "Did you install the sudoers rule for drop_caches? (see the guide)")


# --------------------------------------------------------------------------- measurement

class Sampler(threading.Thread):
    """Samples CPU and memory of the container every second (secondary metrics)."""

    def __init__(self, cg, tag, engine, sf):
        super().__init__(daemon=True)
        self.cg, self.label = cg, {"tag": tag, "engine": engine, "sf": sf}
        self.stop_event = threading.Event()

    def run(self):
        path = RESULTS / "resources.csv"
        while not self.stop_event.is_set():
            try:
                cpu = next(int(l.split()[1]) for l in (self.cg / "cpu.stat").read_text().splitlines()
                           if l.startswith("usage_usec"))
                mem = int((self.cg / "memory.current").read_text())
                append_csv(path, RES_FIELDS, {"timestamp": now(), **self.label,
                                              "cpu_usage_usec": cpu, "memory_current_bytes": mem})
            except (FileNotFoundError, OSError, StopIteration, ValueError):
                pass  # container restarting during a cache reset
            self.stop_event.wait(1.0)


def timed_run(conn, sql, cg, query_id):
    before = read_rbytes(cg)
    t0 = time.perf_counter()
    rows = conn.run(sql, query_id)
    seconds = time.perf_counter() - t0
    after = read_rbytes(cg)
    io = after - before if before is not None and after is not None else ""
    return seconds, io, len(rows)


def record(args, engine, design, query, cache, run_no, seconds, io, nrows, query_id):
    append_csv(RESULTS / "runs.csv", RUN_FIELDS, {
        "timestamp": now(), "tag": args.tag, "engine": engine, "design": design, "sf": args.sf,
        "mem_limit_gb": args.mem_limit_gb, "query": query, "cache": cache, "run_no": run_no,
        "seconds": f"{seconds:.6f}", "io_read_bytes": io, "rows_returned": nrows,
        "query_id": query_id})


def make_qid(args, engine, design, query, cache, run_no):
    return f"{args.tag}_{engine}_{design}_sf{args.sf}_{query}_{cache}_{run_no}_{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- checks and dumps

def preflight(engine, conn, cg, args):
    """Abort if the loaded data or the memory limit do not match the requested run."""
    if engine == "pg":
        count = conn.run("SELECT count(*) FROM b.lineitem")[0][0]
    else:
        count = conn.run("SELECT count() FROM b.lineitem")[0][0]
    expected = LINEITEM_ROWS_SF1 * args.sf
    if abs(count - expected) / expected > 0.01:
        sys.exit(f"{engine}: b.lineitem has {count:,} rows, but SF {args.sf} needs about "
                 f"{expected:,}. Load the right scale factor first.")
    limit = (cg / "memory.max").read_text().strip()
    if limit != str(int(args.mem_limit_gb * 1024 ** 3)):
        sys.exit(f"{engine}: container memory limit is {limit} bytes, "
                 f"but --mem-limit-gb is {args.mem_limit_gb}.")
    print(f"  preflight ok: {count:,} LINEITEM rows, memory limit {args.mem_limit_gb} GB")


def dump_settings(engine, conn, args):
    path = ENV / f"settings_{args.tag}_{engine}_sf{args.sf}.txt"
    if engine == "pg":
        rows = conn.run("SELECT version()") + conn.run("SHOW ALL")
    else:
        rows = conn.run("SELECT version()") + conn.run(
            "SELECT name, value FROM system.settings WHERE changed ORDER BY name")
    path.write_text("\n".join(" | ".join(str(v) for v in r) for r in rows) + "\n")


def instrumented(engine, conn, design, args):
    PLANS.mkdir(parents=True, exist_ok=True)
    for q in args.queries:
        sql = load_sql(engine, q)
        if engine == "pg":
            rows = conn.run("EXPLAIN (ANALYZE, BUFFERS, SETTINGS) " + sql)
        else:
            rows = conn.run("EXPLAIN indexes = 1 " + sql)
        out = PLANS / f"{args.tag}_{engine}_{design}_sf{args.sf}_{q}.txt"
        out.write_text("\n".join(str(r[0]) for r in rows) + "\n")


def collect_ch_log(qids):
    """Fetch data read per run from ClickHouse's query log (data scanned, uncompressed)."""
    conn = connect("ch", "B")
    conn.run("SYSTEM FLUSH LOGS")
    for i in range(0, len(qids), 200):
        ids = ",".join(f"'{q}'" for q in qids[i:i + 200])
        rows = conn.run(
            "SELECT query_id, read_rows, read_bytes, query_duration_ms, memory_usage "
            f"FROM system.query_log WHERE type = 'QueryFinish' AND query_id IN ({ids})")
        for r in rows:
            append_csv(RESULTS / "ch_query_log.csv", CHLOG_FIELDS, dict(zip(CHLOG_FIELDS, r)))
    conn.close()


# --------------------------------------------------------------------------- main loop

def run_engine(engine, args):
    other = "ch" if engine == "pg" else "pg"
    sh(["docker", "stop", CONTAINER[other]], check=False)   # only one engine runs at a time
    compose(["up", "-d", SERVICE[engine]], args.compose_file)

    conn = connect(engine, "B")
    cg = cgroup_dir(CONTAINER[engine])
    preflight(engine, conn, cg, args)
    dump_settings(engine, conn, args)
    conn.close()

    sampler = Sampler(cg, args.tag, engine, args.sf)
    sampler.start()
    ch_qids = []
    queries = args.queries

    for design in args.designs:
        # Cold runs: reset caches before every single run (design B only).
        if design == "B" and args.cold > 0:
            for rep in range(args.cold):
                k = rep % len(queries)
                for q in queries[k:] + queries[:k]:          # rotated order
                    reset_caches(engine)
                    conn = connect(engine, design)          # new connection + SELECT 1
                    qid = make_qid(args, engine, design, q, "cold", rep + 1)
                    s, io, n = timed_run(conn, load_sql(engine, q), cg, qid)
                    record(args, engine, design, q, "cold", rep + 1, s, io, n, qid)
                    ch_qids.append(qid)
                    conn.close()
                print(f"  {engine} {design} cold repetition {rep + 1}/{args.cold} done")

        # Warm block: reset once, warm up, then round-robin.
        reset_caches(engine)
        conn = connect(engine, design)
        for w in range(args.warmup):
            for q in queries:
                qid = make_qid(args, engine, design, q, "warmup", w + 1)
                s, io, n = timed_run(conn, load_sql(engine, q), cg, qid)
                record(args, engine, design, q, "warmup", w + 1, s, io, n, qid)
                ch_qids.append(qid)
        for r in range(args.rounds):
            for q in queries:
                qid = make_qid(args, engine, design, q, "warm", r + 1)
                s, io, n = timed_run(conn, load_sql(engine, q), cg, qid)
                record(args, engine, design, q, "warm", r + 1, s, io, n, qid)
                ch_qids.append(qid)
        print(f"  {engine} {design} warm runs done")

        instrumented(engine, conn, design, args)
        conn.close()

    sampler.stop_event.set()
    sampler.join()
    if engine == "ch":
        collect_ch_log(ch_qids)
    compose(["stop", SERVICE[engine]], args.compose_file)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf", type=int, required=True, help="scale factor currently loaded")
    ap.add_argument("--tag", default="pilot", help="label for this campaign, e.g. pilot or final")
    ap.add_argument("--engines", nargs="+", default=["pg", "ch"], choices=["pg", "ch"])
    ap.add_argument("--designs", nargs="+", default=["B", "D"], choices=["B", "D"])
    ap.add_argument("--queries", nargs="+", default=["q1", "q6", "q12", "q14"])
    ap.add_argument("--cold", type=int, default=5, help="cold repetitions per query (design B)")
    ap.add_argument("--warmup", type=int, default=3, help="discarded warm-up runs per query")
    ap.add_argument("--rounds", type=int, default=10, help="warm round-robin rounds")
    ap.add_argument("--mem-limit-gb", type=float, default=8, help="expected container limit")
    ap.add_argument("--compose-file", action="append", default=None,
                    help="compose file(s); repeat for overrides (default docker-compose.yml)")
    args = ap.parse_args()
    args.compose_file = args.compose_file or ["docker-compose.yml"]

    RESULTS.mkdir(exist_ok=True)
    ENV.mkdir(exist_ok=True)
    started = time.time()
    print(f"Run '{args.tag}', SF {args.sf}, engines {args.engines}, designs {args.designs}")
    for engine in args.engines:
        print(f"== {engine} ==")
        run_engine(engine, args)
    print(f"Done in {(time.time() - started) / 60:.1f} min. Rows appended to results/runs.csv")


if __name__ == "__main__":
    main()