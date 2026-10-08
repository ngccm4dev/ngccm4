#!/usr/bin/env python3
"""Merge benchmark_schemes.py runs into the platform's canonical speed report.

    python3 tools/merge_benchmark.py --base Out/benchmark_speed_nucleo-l4r5zi \\
        --add Out/benchmark_speed_sign_iter100_partial.csv \\
        --add Out/benchmark_speed_sign_iter10.csv:Out/benchmark_speed_sign_iter10.md:Out/benchmark_sign_iter10.log \\
        --note "Signatures re-measured 2026-10-07 ..." [--out PREFIX] [--dry-run]

Each --add is CSV[:MD[:LOG]] of one benchmark_schemes.py run (later runs win):
  * CSV rows replace base rows with the same (family, scheme, implementation, app, metric), unless the
    base row was measured over more iterations (its "count" is higher): that row is kept;
  * every target the run attempted (from its LOG "==> target run" lines, else from its CSV/MD)
    loses its old status line, unless the run merely timed out without measuring anything the
    base did not already have (a shorter capture cap adds no information: the base rows and
    status line are kept); a new status line is written when the run did not measure every
    operation: link overflow / build failure from the LOG, HardFault / timeout from the raw file
    and the run's MD status table, always ending in "completed <ops>" so make_site_data.py can
    classify it (FAILURE_KINDS) and list the operations that did complete;
  * code-size rows (MD "**code size (speed)**" tables) replace base rows per scheme/implementation.
The base MD header (everything before "## target status") is kept, with --note lines appended;
the cycle/stack/code tables are regenerated from the merged data in benchmark_schemes.py's format.
The previous base files are kept as <prefix>.csv.bak / .md.bak.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import benchmark_schemes as bs  # noqa: E402

FAMILY_OPS = {"crypto_kem": ["keypair", "encaps", "decaps"], "crypto_sign": ["keypair", "sign", "verify"]}
STATUS_ROW = re.compile(r"^\| ((?:crypto_(?:kem|kex|sign))_.+?_(?:ref|m4)_(?:speed|stack|hashing|test|testvectors)) \| (.*) \|$")
CODE_ROW = re.compile(r"^\| ([^|]+) \| (ref|m4) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \|$")
TARGET_LINE = re.compile(r"^==> (crypto_\S+?_(?:speed|stack|hashing|test|testvectors)) run \d+/\d+")


def to_int(text: str) -> int:
    return int(text.replace(",", "").strip())


def read_csv(path: Path) -> "OrderedDict[tuple, dict]":
    out: "OrderedDict[tuple, dict]" = OrderedDict()
    with path.open(newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            key = (rec["platform"], rec["family"], rec["scheme"], rec["implementation"], rec["app"], rec["metric"])
            out[key] = rec
    return out


def read_md(path: Path | None) -> tuple[list[str], dict[str, str], dict[tuple, dict]]:
    """header lines (before '## target status' / first '## ' family), statuses, code sizes keyed by (family, scheme, impl)."""
    header: list[str] = []
    statuses: dict[str, str] = {}
    code: dict[tuple, dict] = {}
    if path is None or not path.is_file():
        return header, statuses, code
    section = None
    in_code = False
    in_header = True
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## target status"):
            section, in_header = "status", False
            continue
        if line.startswith("## "):
            section, in_code, in_header = line[3:].strip(), False, False
            continue
        if in_header:
            header.append(line)
            continue
        if section == "status":
            m = STATUS_ROW.match(line)
            if m:
                statuses[m.group(1)] = m.group(2).strip()
            continue
        if line.startswith("**"):
            in_code = line.startswith("**code size")
            continue
        if in_code and section:
            m = CODE_ROW.match(line)
            if m:
                code[(section, m.group(1).strip(), m.group(2))] = {
                    "text": to_int(m.group(3)), "data": to_int(m.group(4)), "bss": to_int(m.group(5)), "total": to_int(m.group(6))}
    while header and not header[-1].strip():
        header.pop()
    return header, statuses, code


def attempted_targets(log: Path | None, rows: "OrderedDict[tuple, dict]", statuses: dict[str, str]) -> list[str]:
    targets: list[str] = []
    if log is not None and log.is_file():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            m = TARGET_LINE.match(line)
            if m and m.group(1) not in targets:
                targets.append(m.group(1))
    for key in rows:
        t = f"{key[1]}_{key[2]}_{key[3]}_{key[4]}"
        if t not in targets:
            targets.append(t)
    for t in statuses:
        if t not in targets:
            targets.append(t)
    return targets


def log_blocks(log: Path | None) -> dict[str, str]:
    """Driver log text per target (from its '==> target run' line to the next one)."""
    blocks: dict[str, str] = {}
    if log is None or not log.is_file():
        return blocks
    current = None
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = TARGET_LINE.match(line)
        if m:
            current = m.group(1)
            blocks[current] = ""
        elif current:
            blocks[current] += line + "\n"
    return blocks


def failure_text(target: str, run_status: str | None, block: str, raw_dir: Path, measured_ops: list[str], family: str) -> str | None:
    """Status line for a target that did not measure every operation, or None when it is complete."""
    expected = FAMILY_OPS.get(family)
    raw = raw_dir / f"{target}.run1.txt"
    raw_text = raw.read_text(encoding="utf-8", errors="replace") if raw.is_file() else ""
    # The HardFault handler prints the done marker, so the driver reports such a target as "ok".
    faulted = "hardfault" in raw_text.lower()
    complete = run_status in (None, "ok") and expected is not None and all(op in measured_ops for op in expected)
    if expected is None:  # kex: variable pass count, trust the driver status
        complete = run_status in (None, "ok") and bool(measured_ops)
    if complete and not faulted:
        return None
    done = ", ".join(op for op in (expected or measured_ops) if op in measured_ops) or "none"
    m = re.search(r"region `?ram'? overflowed by ([\d,]+) bytes", block)
    if m:
        return f"link failed: image does not fit the 640 KB SRAM (RAM overflowed by {int(m.group(1).replace(',', '')):,} bytes); completed none"
    if "will not fit in region" in block or "cannot move location counter" in block:
        return "link failed: image does not fit the 640 KB SRAM; completed none"
    if "collect2: error" in block or re.search(r"make.*Error \d", block):
        return "build failed on the board toolchain (see the run log); completed none"
    if faulted:
        return f"HardFault on the board (heap or stack beyond the 640 KB SRAM); completed {done}"
    if run_status == "timeout" or "timed out waiting" in raw_text:
        return f"timeout: no '#' within the capture limit; completed {done}"
    if run_status in (None, "ok") and not expected:
        return None
    return f"{run_status or 'incomplete'} on the board; completed {done}"


def measured_ops(rows: "OrderedDict[tuple, dict]", family: str, scheme: str, impl: str, app: str) -> list[str]:
    """Operations with a cycle (speed) or stack (stack) row for this target."""
    suffix = "_stack_bytes" if app == "stack" else "_cycles"
    return [k[5][:-len(suffix)] for k in rows if k[1:5] == (family, scheme, impl, app) and k[5].endswith(suffix)]


def metric_sort_key(key: tuple) -> tuple:
    return (key[1], key[2].lower(), key[3], bs.DEFAULT_APPS.index(key[4]) if key[4] in bs.DEFAULT_APPS else 9, bs.metric_order(key[5]), key[5])


def write_report(path: Path, header: list[str], notes: list[str], statuses: dict[str, str], rows: "OrderedDict[tuple, dict]", code: dict[tuple, dict]) -> None:
    lines = list(header)
    if notes:
        lines.extend(notes)
    lines.append("")
    failed = {t: s for t, s in statuses.items() if s and s != "ok"}
    bs.write_status_table(lines, failed)
    families = sorted({k[1] for k in rows} | {k[0] for k in code})
    for family in families:
        lines.append(f"## {family}")
        fam_rows = [r for k, r in rows.items() if k[1] == family]
        for app in [a for a in bs.DEFAULT_APPS if any(r["app"] == a for r in fam_rows)]:
            app_rows = [r for r in fam_rows if r["app"] == app and (r["metric"].endswith("_cycles") or r["metric"].endswith("_stack_bytes"))]
            if not app_rows:
                continue
            app_rows.sort(key=lambda r: (r["scheme"], r["implementation"], bs.metric_order(r["metric"]), r["metric"]))
            lines.append(f"**{app}**")
            lines.append("")
            if app == "stack":
                lines.append("| scheme | implementation | metric | count | average |")
                lines.append("| --- | --- | --- | ---: | ---: |")
            else:
                lines.append("| scheme | implementation | metric | count | average | median | min | max |")
                lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")
            for r in app_rows:
                cells = [r["scheme"], r["implementation"], bs.metric_display_name(r["metric"]), r["count"], r["average"]]
                if app != "stack":
                    cells += [r["median"], r["min"], r["max"]]
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
        sizes = [bs.CodeSize(platform="", family=family, scheme=k[1], implementation=k[2], app="speed", text=v["text"], data=v["data"], bss=v["bss"])
                 for k, v in sorted(code.items(), key=lambda kv: (kv[0][1].lower(), kv[0][2])) if k[0] == family]
        if sizes:
            bs.write_code_size_table(lines, sizes)
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="prefix of the canonical report, e.g. Out/benchmark_speed_nucleo-l4r5zi")
    ap.add_argument("--add", action="append", default=[], metavar="CSV[:MD[:LOG]]", help="a run to merge in (repeatable, later wins)")
    ap.add_argument("--raw-dir", default="Out/benchmark_raw")
    ap.add_argument("--note", action="append", default=[], help="line appended to the report header")
    ap.add_argument("--out", default=None, help="output prefix (default: overwrite --base, keeping .bak copies)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    base = Path(args.base)
    base_csv, base_md = base.with_suffix(".csv"), base.with_suffix(".md")
    rows = read_csv(base_csv)
    header, statuses, code = read_md(base_md)
    raw_dir = ROOT / args.raw_dir
    report: list[str] = []
    for spec in args.add:
        parts = spec.split(":")
        run_csv = Path(parts[0]); run_md = Path(parts[1]) if len(parts) > 1 and parts[1] else None
        run_log = Path(parts[2]) if len(parts) > 2 and parts[2] else None
        run_rows = read_csv(run_csv)
        _, run_statuses, run_code = read_md(run_md)
        blocks = log_blocks(run_log)
        targets = attempted_targets(run_log, run_rows, run_statuses)
        code.update(run_code)
        dropped = added = kept = 0
        keep: set[str] = set()
        for target in targets:
            m = re.match(r"^(crypto_(?:kem|kex|sign))_(.+)_(ref|m4)_([a-z]+)$", target)
            family, scheme, impl, app = m.groups()
            measured = measured_ops(run_rows, family, scheme, impl, app)
            text = failure_text(target, run_statuses.get(target), blocks.get(target, ""), raw_dir, measured, family)
            # A timeout that measured no more than an earlier (longer-capped) run already had carries no
            # new information: keep that run's rows and status line instead of degrading the target.
            if text and text.startswith("timeout") and set(measured) < set(measured_ops(rows, family, scheme, impl, app)):
                keep.add(target); kept += 1
                continue
            if target in statuses:
                del statuses[target]; dropped += 1
            if text:
                statuses[target] = text; added += 1
        run_rows = OrderedDict((k, v) for k, v in run_rows.items() if f"{k[1]}_{k[2]}_{k[3]}_{k[4]}" not in keep)
        # A row measured over fewer iterations never displaces one measured over more (a 1-iteration
        # rerun that merely completes the operation list keeps the earlier multi-iteration averages).
        fewer = [k for k, v in run_rows.items() if k in rows and to_int(rows[k]["count"]) > to_int(v["count"])]
        for k in fewer:
            del run_rows[k]
        replaced = sum(1 for k in run_rows if k in rows)
        rows.update(run_rows)
        report.append(f"{run_csv.name}: {len(run_rows)} rows ({replaced} replaced, {len(fewer)} kept from the base with more iterations), "
                      f"{len(targets)} targets attempted, {dropped} old status lines dropped, {added} status lines written, "
                      f"{kept} earlier results kept over a shorter-cap timeout, {len(run_code)} code sizes")
    rows = OrderedDict(sorted(rows.items(), key=lambda kv: metric_sort_key(kv[0])))
    notes = [n for n in args.note if n]
    out = Path(args.out) if args.out else base
    out_csv, out_md = out.with_suffix(".csv"), out.with_suffix(".md")
    for line in report:
        print(line)
    print(f"merged: {len(rows)} CSV rows, {len(statuses)} status lines, {len(code)} code sizes -> {out_csv}, {out_md}")
    if args.dry_run:
        return 0
    if out == base:
        shutil.copyfile(base_csv, base_csv.with_suffix(".csv.bak"))
        shutil.copyfile(base_md, base_md.with_suffix(".md.bak"))
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["platform", "family", "scheme", "implementation", "app", "metric", "count", "average", "median", "min", "max"])
        w.writeheader()
        for r in rows.values():
            w.writerow({k: r[k] for k in w.fieldnames})
    write_report(out_md, header, notes, statuses, rows, code)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
