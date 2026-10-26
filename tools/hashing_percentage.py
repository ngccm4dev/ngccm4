#!/usr/bin/env python3
"""Hashing share of every benchmarked operation: hash_cycles / operation cycles.

Input: one or more CSV files written by benchmark_schemes.py --apps hashing (rows with app=hashing:
<op>_hash_cycles is the time spent in the HASHING_PROFILE-instrumented hash functions, <op>_cycles the
whole operation measured in the same run). Later files override earlier ones per (implementation,
metric) unless the earlier row was averaged over more iterations.

Outputs:
  --merged-csv  the merged raw measurements in benchmark_schemes.py CSV format (the canonical
                Out/benchmark_hashing_<platform>.csv read by tools/make_site_data.py)
  --csv         one row per implementation and operation with hash cycles, operation cycles and the
                percentage, plus an "all" row per implementation (sum over the measured operations)
  --md          the same as Markdown tables per family, with --title / --note lines on top

    python3 tools/hashing_percentage.py Out/benchmark_hashing_iter10.csv Out/benchmark_hashing_iter3.csv \\
        Out/benchmark_hashing_iter1.csv --merged-csv Out/benchmark_hashing_nucleo-l4r5zi.csv \\
        --csv Out/benchmark_hashing_percent_nucleo-l4r5zi.csv --md Out/benchmark_hashing_nucleo-l4r5zi.md \\
        --note "Measured 2026-10-20 ..."

Importable: load_hashing(paths) -> {stem: {op: {"hash": {avg,median,min,max,count}, "total": {...}, "pct": float}}}
and aggregate(ops) for the per-implementation total.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import benchmark_schemes as bs  # noqa: E402

FIELDS = ["platform", "family", "scheme", "implementation", "app", "metric", "count", "average", "median", "min", "max"]


def to_int(text: str) -> int:
    return int(str(text).replace(",", "").strip())


def read_rows(paths: list[Path]) -> "OrderedDict[tuple, dict]":
    """Merged raw rows keyed by (platform, family, scheme, implementation, metric); app=hashing only."""
    rows: "OrderedDict[tuple, dict]" = OrderedDict()
    for path in paths:
        with path.open(newline="", encoding="utf-8") as fh:
            for rec in csv.DictReader(fh):
                if rec["app"] != "hashing":
                    continue
                key = (rec["platform"], rec["family"], rec["scheme"], rec["implementation"], rec["metric"])
                old = rows.get(key)
                if old is not None and to_int(old["count"]) > to_int(rec["count"]):
                    continue
                rows[key] = rec
    return rows


def stats(rec: dict) -> dict:
    return {"avg": to_int(rec["average"]), "median": to_int(rec["median"]), "min": to_int(rec["min"]),
            "max": to_int(rec["max"]), "count": to_int(rec["count"])}


def percentages(rows: "OrderedDict[tuple, dict]") -> "OrderedDict[str, dict]":
    """{stem: {"platform", "family", "scheme", "impl", "ops": {op: {"hash", "total", "pct"}}}} in CSV order."""
    out: "OrderedDict[str, dict]" = OrderedDict()
    for (platform, family, scheme, impl, metric), rec in rows.items():
        if not metric.endswith("_hash_cycles"):
            continue
        op = metric[: -len("_hash_cycles")]
        total = rows.get((platform, family, scheme, impl, f"{op}_cycles"))
        if total is None:
            continue
        stem = f"{family}_{scheme}_{impl}"
        entry = out.setdefault(stem, {"platform": platform, "family": family, "scheme": scheme, "impl": impl, "ops": OrderedDict()})
        h, t = stats(rec), stats(total)
        # a hash count above the operation's own cycle count is impossible: the implementation
        # overwrote the counter (seen with DTRU-Light m4); keep the row but give it no share
        invalid = h["avg"] > t["avg"] or h["max"] > t["max"]
        entry["ops"][op] = {"hash": h, "total": t, "pct": (100.0 * h["avg"] / t["avg"]) if (t["avg"] and not invalid) else None,
                            "invalid": invalid}
    for entry in out.values():
        entry["ops"] = OrderedDict(sorted(entry["ops"].items(), key=lambda kv: bs.metric_order(kv[0] + "_cycles")))
        entry["all"] = aggregate(entry["ops"])
    return out


def aggregate(ops: dict) -> dict:
    valid = {op: v for op, v in ops.items() if not v.get("invalid")}
    hash_sum = sum(v["hash"]["avg"] for v in valid.values())
    total_sum = sum(v["total"]["avg"] for v in valid.values())
    return {"hash_avg": hash_sum, "total_avg": total_sum,
            "pct": (100.0 * hash_sum / total_sum) if (total_sum and len(valid) == len(ops)) else None,
            "count": min((v["total"]["count"] for v in ops.values()), default=0), "ops": list(ops),
            "invalid_ops": [op for op, v in ops.items() if v.get("invalid")]}


def load_hashing(paths: list[Path]) -> "OrderedDict[str, dict]":
    return percentages(read_rows(paths))


def write_merged_csv(path: Path, rows: "OrderedDict[tuple, dict]") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r["platform"], r["family"], r["scheme"], r["implementation"],
                                                    bs.metric_order(r["metric"]), r["metric"].endswith("_hash_cycles"), r["metric"]))
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in ordered:
            w.writerow(r)


def fmt_pct(p: float | None) -> str:
    return "" if p is None else f"{p:.2f}"


def write_percent_csv(path: Path, data: "OrderedDict[str, dict]") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["platform", "family", "scheme", "implementation", "operation", "count", "hash_cycles_avg", "operation_cycles_avg", "hash_percent"])
        for e in data.values():
            for op, v in e["ops"].items():
                w.writerow([e["platform"], e["family"], e["scheme"], e["impl"], op, v["total"]["count"], v["hash"]["avg"], v["total"]["avg"], fmt_pct(v["pct"])])
            a = e["all"]
            w.writerow([e["platform"], e["family"], e["scheme"], e["impl"], "all", a["count"], a["hash_avg"], a["total_avg"], fmt_pct(a["pct"])])


def write_md(path: Path, data: "OrderedDict[str, dict]", title: str, notes: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    for note in notes:
        lines.append(note)
    if notes:
        lines.append("")
    families = sorted({e["family"] for e in data.values()})
    for family in families:
        entries = [e for e in data.values() if e["family"] == family]
        lines.append(f"## {family}")
        lines.append("")
        lines.append("**hashing share per implementation (all measured operations)**")
        lines.append("")
        lines.append("| scheme | implementation | operations | count | hash cycles | operation cycles | hashing % |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: |")
        for e in sorted(entries, key=lambda e: -(e["all"]["pct"] or 0)):
            a = e["all"]
            lines.append(f"| {e['scheme']} | {e['impl']} | {'/'.join(a['ops'])} | {a['count']:,} | {a['hash_avg']:,} | {a['total_avg']:,} | {fmt_pct(a['pct'])} |")
        lines.append("")
        lines.append("**hashing share per operation**")
        lines.append("")
        lines.append("| scheme | implementation | operation | count | hash cycles (avg) | operation cycles (avg) | hashing % |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: |")
        for e in sorted(entries, key=lambda e: (e["scheme"], e["impl"])):
            for op, v in e["ops"].items():
                lines.append(f"| {e['scheme']} | {e['impl']} | {op} | {v['total']['count']:,} | {v['hash']['avg']:,} | {v['total']['avg']:,} | {fmt_pct(v['pct']) if not v.get('invalid') else 'invalid (counter overwritten)'} |")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path, help="benchmark_schemes.py CSV files of hashing runs (later files win)")
    ap.add_argument("--merged-csv", type=Path, help="write the merged raw measurements (benchmark_schemes.py format)")
    ap.add_argument("--csv", type=Path, help="write the percentage table as CSV")
    ap.add_argument("--md", type=Path, help="write the percentage tables as Markdown")
    ap.add_argument("--title", default="NGCC hashing share on Nucleo-L4R5ZI (STM32L4R5ZI, Cortex-M4)")
    ap.add_argument("--note", action="append", default=[], help="line for the Markdown header (repeatable)")
    args = ap.parse_args(argv)

    for p in args.inputs:
        if not p.is_file():
            raise SystemExit(f"missing input: {p}")
    rows = read_rows(args.inputs)
    data = percentages(rows)
    if args.merged_csv:
        write_merged_csv(args.merged_csv, rows)
    if args.csv:
        write_percent_csv(args.csv, data)
    if args.md:
        write_md(args.md, data, args.title, args.note)
    print(f"{len(data)} implementations, {sum(len(e['ops']) for e in data.values())} operations")
    if not (args.merged_csv or args.csv or args.md):
        for e in data.values():
            a = e["all"]
            print(f"{e['family']}/{e['scheme']}/{e['impl']}: {fmt_pct(a['pct'])}%  " + "  ".join(f"{op}={fmt_pct(v['pct'])}%" for op, v in e["ops"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
