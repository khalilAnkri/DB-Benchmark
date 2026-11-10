# PostgreSQL vs ClickHouse — Effect of Dataset Size on Analytical Query Performance

INFO9016 Advanced Databases, University of Liège, 2026-2027 — Group 9

Benchmark harness for the M2 experiment: TPC-H Q1, Q6, Q12, Q14 at scale
factors 1, 2, 4 and 10, under a baseline (B) and a data-skipping (D) physical design.

## Layout
- `docker-compose.yml` — both engines with identical CPU and memory limits
- `config/`            — engine configuration (Table 5 of the report)
- `sql/`               — schemas and queries, one folder per engine
- `scripts/`           — loading, cache reset, measurement, analysis
- `results/`           — raw measurements (one CSV row per run)
- `env/`               — host description, image digests, settings dumps
- `data/`              — generated TPC-H files (not versioned)

See `IMPLEMENTATION_GUIDE.md` for the full procedure.
