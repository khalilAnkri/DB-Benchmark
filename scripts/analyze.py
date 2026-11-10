#!/usr/bin/env python3
"""Analysis of results/runs.csv (report Section 5.5).

For one campaign tag it computes, per engine, design, scale factor, query and
cache state: the median time, the relative IQR and the median bytes read from
storage. It then computes the speedup S = median_PG / median_CH with a 95%
bootstrap confidence interval, the change r_i between consecutive scale
factors, and applies the decision rules of Table 6 to whatever scale factors
are present. Warm-up runs are never used.

Usage:  python scripts/analyze.py --tag pilot
Output: results/summary_<tag>.csv, results/speedups_<tag>.csv,
        results/decisions_<tag>.csv, results/speedup_<tag>.png
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
QUERY_ORDER = ["q1", "q6", "q12", "q14"]
PLANNED_SF = [1, 2, 4, 10]
BAND = (0.9, 1.1)


def boot_median(x, rng, b):
    x = np.asarray(x, dtype=float)
    idx = rng.integers(0, len(x), size=(b, len(x)))
    return np.median(x[idx], axis=1)


def ci(values):
    lo, hi = np.percentile(values, [2.5, 97.5])
    return lo, hi


def summarize(df):
    g = df.groupby(["engine", "design", "sf", "query", "cache"])
    out = g.agg(n=("seconds", "size"),
                median_s=("seconds", "median"),
                q1_s=("seconds", lambda s: s.quantile(0.25)),
                q3_s=("seconds", lambda s: s.quantile(0.75)),
                median_io_read_bytes=("io_read_bytes", "median")).reset_index()
    out["rel_iqr"] = (out.q3_s - out.q1_s) / out.median_s
    return out


def speedups(df, rng, b):
    rows, boots = [], {}
    for (design, sf, query, cache), grp in df.groupby(["design", "sf", "query", "cache"]):
        pg = grp[grp.engine == "pg"].seconds.values
        ch = grp[grp.engine == "ch"].seconds.values
        if len(pg) == 0 or len(ch) == 0:
            continue
        s = np.median(pg) / np.median(ch)
        sb = boot_median(pg, rng, b) / boot_median(ch, rng, b)
        boots[(design, sf, query, cache)] = sb
        lo, hi = ci(sb)
        rows.append(dict(design=design, sf=sf, query=query, cache=cache,
                         S=s, S_ci_low=lo, S_ci_high=hi, n_pg=len(pg), n_ch=len(ch)))
    sp = pd.DataFrame(rows)

    # r_i between consecutive scale factors present in the data
    rrows = []
    for (design, query, cache), grp in sp.groupby(["design", "query", "cache"]):
        sfs = sorted(grp.sf.unique())
        for a, c in zip(sfs, sfs[1:]):
            rb = boots[(design, c, query, cache)] / boots[(design, a, query, cache)]
            r = float(grp[grp.sf == c].S.iloc[0] / grp[grp.sf == a].S.iloc[0])
            lo, hi = ci(rb)
            per_doubling = r ** (1 / np.log2(c / a))
            rrows.append(dict(design=design, query=query, cache=cache, sf_from=a, sf_to=c,
                              r=r, r_ci_low=lo, r_ci_high=hi, r_per_doubling=per_doubling))
    return sp, pd.DataFrame(rrows)


def decide(sp, rr):
    """Table 6 of the report, design B, warm runs, per query."""
    rows = []
    warm = sp[(sp.design == "B") & (sp.cache == "warm")]
    present = sorted(warm.sf.unique())
    missing = [s for s in PLANNED_SF if s not in present]
    for q in QUERY_ORDER:
        w = warm[warm["query"] == q]
        if w.empty:
            continue
        # H1: CI of S above 1 at all sizes
        if (w.S_ci_high < 1).any():
            h1 = "not supported"
        elif (w.S_ci_low > 1).all():
            h1 = "supported" if not missing else "supported so far (partial)"
        else:
            h1 = "inconclusive"
        # H2a: r between SF1-2 and SF2-4 inside the band
        r = rr[(rr.design == "B") & (rr.cache == "warm") & (rr["query"] == q)] if not rr.empty else rr
        pairs = [(1, 2), (2, 4)]
        sub = [r[(r.sf_from == a) & (r.sf_to == c)] for a, c in pairs] if not r.empty else []
        if not r.empty and all(len(s) for s in sub):
            inside = all(s.r_ci_low.iloc[0] >= BAND[0] and s.r_ci_high.iloc[0] <= BAND[1] for s in sub)
            outside = any(s.r_ci_high.iloc[0] < BAND[0] or s.r_ci_low.iloc[0] > BAND[1] for s in sub)
            h2a = "supported" if inside else "not supported" if outside else "inconclusive"
        else:
            h2a = "not testable yet (needs SF 1, 2, 4)"
        # H2b: r between SF4-10 above the band (memory regimes checked separately)
        s3 = r[(r.sf_from == 4) & (r.sf_to == 10)] if not r.empty else r
        if not r.empty and len(s3):
            if s3.r_ci_low.iloc[0] > BAND[1]:
                h2b = "supported if PG is out of memory and CH in memory at SF 10 (check io)"
            elif s3.r_ci_high.iloc[0] < BAND[1]:
                h2b = "not supported if the memory regimes are as expected (check io)"
            else:
                h2b = "inconclusive"
        else:
            h2b = "not testable yet (needs SF 4 and 10)"
        rows.append(dict(query=q, H1=h1, H2a=h2a, H2b=h2b,
                         sizes_tested=",".join(str(s) for s in present)))
    return pd.DataFrame(rows)


def plot(sp, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    queries = [q for q in QUERY_ORDER if q in set(sp["query"])]
    fig, axes = plt.subplots(1, len(queries), figsize=(3.4 * len(queries), 3.2), sharey=True)
    axes = np.atleast_1d(axes)
    styles = {("B", "warm"): ("o-", "B warm"), ("B", "cold"): ("s--", "B cold"),
              ("D", "warm"): ("^:", "D warm")}
    for ax, q in zip(axes, queries):
        for (design, cache), (style, label) in styles.items():
            d = sp[(sp["query"] == q) & (sp.design == design) & (sp.cache == cache)].sort_values("sf")
            if d.empty:
                continue
            yerr = [(d.S - d.S_ci_low).to_numpy(), (d.S_ci_high - d.S).to_numpy()]
            ax.errorbar(d.sf.to_numpy(), d.S.to_numpy(), yerr=yerr, fmt=style, capsize=3, label=label)
        ax.axhline(1, color="grey", lw=0.8)
        ax.set_xscale("log")
        ax.set_xticks(PLANNED_SF)
        ax.set_xticklabels(PLANNED_SF)
        ax.set_title(q.upper())
        ax.set_xlabel("scale factor")
    axes[0].set_ylabel("speedup S = t_PG / t_CH")
    axes[-1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--boot", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    df = pd.read_csv(RESULTS / "runs.csv")
    df = df[(df.tag == args.tag) & (df.cache.isin(["warm", "cold"]))].copy()
    if df.empty:
        raise SystemExit(f"No warm or cold runs with tag '{args.tag}' in results/runs.csv")
    df["io_read_bytes"] = pd.to_numeric(df.io_read_bytes, errors="coerce")
    rng = np.random.default_rng(args.seed)

    summ = summarize(df)
    sp, rr = speedups(df, rng, args.boot)
    dec = decide(sp, rr)

    summ.to_csv(RESULTS / f"summary_{args.tag}.csv", index=False)
    sp.to_csv(RESULTS / f"speedups_{args.tag}.csv", index=False)
    if not rr.empty:
        rr.to_csv(RESULTS / f"ratios_{args.tag}.csv", index=False)
    dec.to_csv(RESULTS / f"decisions_{args.tag}.csv", index=False)
    plot(sp, RESULTS / f"speedup_{args.tag}.png")

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print("\n=== Medians (seconds), relative IQR, median bytes read from storage ===")
    print(summ.round(4).to_string(index=False))
    print("\n=== Speedup S = median_PG / median_CH with 95% bootstrap CI ===")
    print(sp.round(3).to_string(index=False))
    if not rr.empty:
        print("\n=== Change of S between scale factors ===")
        print(rr.round(3).to_string(index=False))
    print("\n=== Decision table (design B, warm runs) ===")
    print(dec.to_string(index=False))
    print(f"\nFiles written to {RESULTS}")


if __name__ == "__main__":
    main()