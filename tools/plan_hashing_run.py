#!/usr/bin/env python3
"""Plan the board run of the hashing app over the implementations that completed a speed benchmark.

Reads the published site data (docs/data/benchmark.json, every implementation directory with its
run status and average cycles) and groups the "measured" implementations by how long 10 iterations
of all operations would take at the board clock, so that the slow hash-based signature schemes get
fewer iterations instead of timing out:

    est10 = sum(avg cycles of all operations) * 10 / 16 MHz
    est10 <= --fast-minutes   -> NGCC_ITERATIONS=10
    est10 <= --medium-minutes -> NGCC_ITERATIONS=3
    otherwise                 -> NGCC_ITERATIONS=1  (capture cap --slow-timeout)

Each group becomes one benchmark_schemes.py command (the iteration count is a make variable, and
changing it rebuilds everything, so one driver invocation per group). Implementations of a selected
scheme that were not measured by the speed run (e.g. an m4 port that HardFaulted) are excluded with
--skip family/scheme/impl patterns.

    python3 tools/plan_hashing_run.py                 # human-readable plan
    python3 tools/plan_hashing_run.py --json plan.json
    python3 tools/plan_hashing_run.py --commands      # one shell command per group
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOCK_HZ = 16_000_000


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=ROOT / "docs" / "data" / "benchmark.json")
    ap.add_argument("--platform", default="nucleo-l4r5zi")
    ap.add_argument("--fast-minutes", type=float, default=20.0, help="est10 at or below this: 10 iterations")
    ap.add_argument("--medium-minutes", type=float, default=70.0, help="est10 at or below this: 3 iterations")
    ap.add_argument("--fast-timeout", type=int, default=1800, help="capture cap (s) for the 10- and 3-iteration groups")
    ap.add_argument("--slow-timeout", type=int, default=4500, help="capture cap (s) for the 1-iteration group")
    ap.add_argument("--jobs", default="8")
    ap.add_argument("--out-prefix", default="Out/benchmark_hashing", help="CSV/MD/log prefix; the group suffix _iterN is appended")
    ap.add_argument("--raw-dir", default="Out/benchmark_raw_hashing")
    ap.add_argument("--skip-mk", default="Out/hashing_skip.mk",
                    help="skip-list fragment written by this script: every implementation without a complete speed "
                         "benchmark (passed to the driver as --skip-file, so only measured implementations run)")
    ap.add_argument("--json", type=Path, help="write the plan as JSON")
    ap.add_argument("--commands", action="store_true", help="print one benchmark_schemes.py command per group")
    args = ap.parse_args(argv)

    data = json.loads(args.data.read_text(encoding="utf-8"))
    rows = [r for cat in data["categories"].values() for r in cat["rows"]]
    impls_by_scheme: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        impls_by_scheme.setdefault((r["family"], r["scheme"]), []).append(r["impl"])

    measured = [r for r in rows if r["run_status"] == "measured"]
    groups: dict[int, dict] = {
        10: {"iterations": 10, "timeout": args.fast_timeout, "schemes": [], "skip": [], "est_minutes": 0.0},
        3: {"iterations": 3, "timeout": args.fast_timeout, "schemes": [], "skip": [], "est_minutes": 0.0},
        1: {"iterations": 1, "timeout": args.slow_timeout, "schemes": [], "skip": [], "est_minutes": 0.0},
    }
    per_scheme: dict[tuple[str, str], int] = {}
    detail: list[dict] = []
    for r in measured:
        cycles = sum(v["avg"] for v in r["cycles"].values())
        est10 = cycles * 10 / CLOCK_HZ / 60
        iters = 10 if est10 <= args.fast_minutes else 3 if est10 <= args.medium_minutes else 1
        key = (r["family"], r["scheme"])
        # one scheme name = one driver argument; if its implementations fall in different groups, the slower wins
        per_scheme[key] = min(per_scheme.get(key, 10), iters)
        detail.append({"id": r["id"], "family": r["family"], "scheme": r["scheme"], "impl": r["impl"],
                       "est10_minutes": round(est10, 1), "iterations": iters, "speed_count": min(v["count"] for v in r["cycles"].values())})
    measured_ids = {(r["family"], r["scheme"], r["impl"]) for r in measured}
    scheme_names_seen: dict[str, str] = {}
    for (family, scheme), iters in sorted(per_scheme.items()):
        if scheme in scheme_names_seen and scheme_names_seen[scheme] != family:
            print(f"warning: scheme name {scheme!r} exists in {scheme_names_seen[scheme]} and {family}; "
                  f"the driver selects both (use --family to split)", file=sys.stderr)
        scheme_names_seen[scheme] = family
        g = groups[iters]
        g["schemes"].append(scheme)
        for impl in impls_by_scheme[(family, scheme)]:
            if (family, scheme, impl) not in measured_ids:
                g["skip"].append(f"{family}/{scheme}/{impl}")
        g["est_minutes"] += sum(d["est10_minutes"] / 10 * iters for d in detail if d["family"] == family and d["scheme"] == scheme)
    # the driver also selects every implementation of a scheme that lives in another family under the same name:
    # exclude those unless they are measured too (they would be in per_scheme anyway)
    for g in groups.values():
        g["schemes"] = sorted(set(g["schemes"]))
        g["skip"] = sorted(set(g["skip"]))
        g["est_minutes"] = round(g["est_minutes"], 1)

    # one skip file for every group: all implementations that have no complete speed benchmark
    not_measured = sorted(f"{r['family']}/{r['scheme']}/{r['impl']}" for r in rows
                          if (r["family"], r["scheme"], r["impl"]) not in measured_ids)
    skip_mk = ROOT / args.skip_mk
    skip_mk.parent.mkdir(parents=True, exist_ok=True)
    skip_mk.write_text(
        "# Written by tools/plan_hashing_run.py: implementations without a complete speed benchmark\n"
        "# (run_status != measured in docs/data/benchmark.json). Used as --skip-file / SKIP_MK for the hashing run.\n"
        "SKIP_SCHEMES +=\n" + "".join(f"SKIP_IMPLS += {p}\n" for p in not_measured), encoding="utf-8")

    def command(g: dict) -> str:
        parts = ["python3", "benchmark_schemes.py", f"PLATFORM={args.platform}", f"NGCC_ITERATIONS={g['iterations']}",
                 "--tier", "all", "--skip-file", args.skip_mk, "--apps", "hashing", "--no-code-size",
                 "--timeout", str(g["timeout"]), "-j", args.jobs,
                 "--csv", f"{args.out_prefix}_iter{g['iterations']}.csv", "--md", f"{args.out_prefix}_iter{g['iterations']}.md",
                 "--raw-dir", args.raw_dir]
        parts += g["schemes"]
        return " ".join(shlex.quote(p) for p in parts)

    plan = {"platform": args.platform, "measured_implementations": len(measured), "skip_mk": args.skip_mk,
            "not_measured_implementations": len(not_measured),
            "groups": [dict(g, command=command(g)) for g in (groups[10], groups[3], groups[1]) if g["schemes"]],
            "implementations": sorted(detail, key=lambda d: -d["est10_minutes"])}
    if args.json:
        args.json.write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    if args.commands:
        for g in plan["groups"]:
            print(g["command"])
        return 0
    print(f"{len(measured)} measured implementations in {sum(len(g['schemes']) for g in plan['groups'])} schemes")
    for g in plan["groups"]:
        print(f"\nNGCC_ITERATIONS={g['iterations']} (cap {g['timeout']} s): {len(g['schemes'])} schemes, "
              f"~{g['est_minutes']} min of board time + build/flash")
        print("  " + " ".join(g["schemes"]))
        if g["skip"]:
            print("  excluded implementations of these schemes (no speed result): " + " ".join(g["skip"]))
    print("\nslowest implementations (minutes for 10 iterations of all operations):")
    for d in plan["implementations"][:30]:
        print(f"  {d['id']:50s} {d['est10_minutes']:7.1f}  -> {d['iterations']} iteration(s); speed run had {d['speed_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
