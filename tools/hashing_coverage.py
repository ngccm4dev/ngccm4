#!/usr/bin/env python3
"""Record which hash code the hashing app actually counts, per linked hashing ELF.

The hashing app (crypto_*/hashing.c) adds the cycles spent in the HASHING_PROFILE-instrumented
functions of common/: the ICCS hash API (sm3hash, pseudohash, pseudoXOF, pseudoXOF_squeeze) and the
SM3 DRNG. A scheme that links its own Keccak/SHA-2/SM3 code, or that calls the common primitives
(sm3_bit, sha256_transform) directly instead of through the instrumented wrappers, spends hash cycles
that are not counted, so its hashing share is a lower bound.

This script looks at every elf/*_hashing.elf and the matching objects under obj/hashprof/<impl>/
(run it right after a benchmark_schemes.py --apps hashing run, before the next NGCC_ITERATIONS change
wipes obj/ and elf/) and writes, per implementation:

  counted            instrumented common functions linked into the ELF (reachable code: the link uses
                     --gc-sections, so an unreferenced function is dropped), plus the assembly
                     primitives counted through the --wrap trampolines of common/hashprof.c
  own_hash_symbols   function symbols of hash/XOF primitives defined outside common/ and still present
                     in the ELF, i.e. the scheme's own hash code that is reachable
  direct_primitives  common primitives the scheme's objects call directly (bypassing the wrappers)
  self_instrumented  the implementation's own sources contain HASHING_PROFILE (they count themselves)
  own_primitive_symbols  the subset of own_hash_symbols that are real primitives (permutation rounds,
                     compression functions, SHA-2 blocks) rather than absorb/squeeze/padding wrappers
  coverage           "full" when nothing uncounted was found; "core" when only the scheme's own
                     wrapper layer (padding, absorb/squeeze byte handling) around the counted
                     assembly primitive is uncounted; "partial" when an uncounted primitive is reachable

Results are merged into --out (JSON keyed by implementation stem); existing entries are replaced.

    python3 tools/hashing_coverage.py [--elf-dir elf] [--obj-dir obj/hashprof] [--out Out/benchmark_hashing_coverage.json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INSTRUMENTED = ("sm3hash", "pseudohash", "pseudoXOF", "pseudoXOF_squeeze")
DRNG = ("SM3_DRNG_Instantiate", "SM3_DRNG_Generate")
PRIMITIVES = ("sm3_bit", "sm3_bit_compress", "sm3_bit_compress_asm", "sha256_transform")
# own hash/XOF primitive code: Keccak/SHAKE/SHA-3, SHA-2, SM3, and the usual MPCitH/hash-signature extras
OWN_HASH_RE = re.compile(r"keccak|shake|sha3|sha_?256|sha_?512|sha_?224|sha_?384|sha2\b|(?<![a-z])sm3|blake|haraka|ascon|fips202|xkcp|sponge", re.I)
FUNC_TYPES = set("TtWw")
# among a scheme's own hash symbols, the ones that are real primitives (everything else is the API/
# padding layer around a counted primitive); the routed wrappers and the *_c fallbacks that stay
# reachable only through a non-24-round argument (GreatWall) are neither
OWN_PRIMITIVE_RE = re.compile(r"permut|round|keccakf1600|hashblocks|compress|transform|sha_?256|sha_?512|sha_?224|sha_?384|K_SHA|blake|haraka|ascon|UpdateSM3|sm3_m4", re.I)
ROUTED_WRAPPERS = {"KeccakP1600_Permute_24rounds", "keccakp1600_permute", "keccak_permute", "keccakf1600", "crypto_hashblocks_sm3",
                   "sm3_bit_compress", "UpdateSM3", "KeccakF1600_FastLoop_Absorb"}
ROUTED_FALLBACKS = {"keccakp1600_permute_c"}


def base_symbol(name: str) -> str:
    """strip GCC clone suffixes: foo.constprop.0, foo.isra.1, foo.part.2"""
    return re.sub(r"\.(?:constprop|isra|part|cold|lto_priv)\.\d+$", "", name)


def nm(nm_tool: str, path: Path, flag: str) -> list[tuple[str, str]]:
    out = subprocess.run([nm_tool, flag, str(path)], capture_output=True, text=True, check=True).stdout
    symbols: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            symbols.append((parts[1], parts[2]))
        elif len(parts) == 2:
            symbols.append((parts[0], parts[1]))
    return symbols


def impl_dir(stem: str) -> Path | None:
    m = re.match(r"^(crypto_(?:kem|kex|sign))_(.+)_(ref|m4)$", stem)
    if not m:
        return None
    return ROOT / m.group(1) / m.group(2) / m.group(3)


def self_instrumented(stem: str) -> bool:
    d = impl_dir(stem)
    if d is None or not d.is_dir():
        return False
    return any("HASHING_PROFILE" in p.read_text(encoding="utf-8", errors="replace") for p in d.glob("*.[chS]"))


def scan(stem: str, elf: Path, obj_dir: Path, nm_tool: str) -> dict:
    common_syms: set[str] = set()
    common_dir = obj_dir / stem / "common"
    for o in sorted(common_dir.glob("*.o")) if common_dir.is_dir() else []:
        common_syms.update(name for typ, name in nm(nm_tool, o, "--defined-only"))
    if not common_syms:
        common_syms = set(INSTRUMENTED) | set(DRNG) | set(PRIMITIVES) | {"pseudohash_512", "pseudohash_768", "pseudohash_1024"}
    elf_funcs = {name for typ, name in nm(nm_tool, elf, "--defined-only") if typ in FUNC_TYPES}
    # the common assembly primitives are counted through --wrap trampolines (common/hashprof.c)
    wrapped = {p for p in ("KeccakF1600_StatePermute", "sm3_bit_compress_asm") if f"__wrap_{p}" in elf_funcs and p in elf_funcs}
    own = sorted(s for s in elf_funcs - common_syms if OWN_HASH_RE.search(s) and not s.startswith("hashing_")
                 and not s.startswith("__wrap_") and not s.startswith("__real_") and s not in wrapped)
    own = [s for s in own if base_symbol(s) not in ROUTED_WRAPPERS and base_symbol(s) not in ROUTED_FALLBACKS]
    own_prim = [s for s in own if OWN_PRIMITIVE_RE.search(base_symbol(s))]
    counted = [s for s in INSTRUMENTED if s in elf_funcs] + sorted(f"{p} (asm, wrapped)" for p in wrapped)
    direct: set[str] = set()
    scheme_objs = [o for o in (obj_dir / stem).rglob("*.o") if "common" not in o.relative_to(obj_dir / stem).parts] if (obj_dir / stem).is_dir() else []
    for o in scheme_objs:
        for typ, name in nm(nm_tool, o, "--undefined-only"):
            if name in PRIMITIVES and not (name == "sm3_bit_compress_asm" and name in wrapped) and not (name == "sm3_bit_compress" and "sm3_bit_compress_asm" in wrapped):
                direct.add(name)
    selfi = self_instrumented(stem)
    if own_prim or (direct and not selfi):
        coverage = "partial"
    elif own:
        coverage = "core"
    else:
        coverage = "full"
    return {
        "counted": counted + ["SM3_DRNG"],
        "own_hash_symbols": own,
        "own_primitive_symbols": own_prim,
        "direct_primitives": sorted(direct),
        "self_instrumented": selfi,
        "coverage": coverage,
        "objects_scanned": len(scheme_objs),
        "scanned_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--elf-dir", type=Path, default=ROOT / "elf")
    ap.add_argument("--obj-dir", type=Path, default=ROOT / "obj" / "hashprof")
    ap.add_argument("--out", type=Path, default=ROOT / "Out" / "benchmark_hashing_coverage.json")
    ap.add_argument("--nm", default="arm-none-eabi-nm")
    ap.add_argument("--only", nargs="*", default=None, help="implementation stems to scan (default: every *_hashing.elf)")
    args = ap.parse_args(argv)

    data: dict[str, dict] = {}
    if args.out.is_file():
        data = json.loads(args.out.read_text(encoding="utf-8"))
    elfs = sorted(args.elf_dir.glob("*_hashing.elf"))
    n = 0
    for elf in elfs:
        stem = elf.name[: -len("_hashing.elf")]
        if args.only and stem not in args.only:
            continue
        data[stem] = scan(stem, elf, args.obj_dir, args.nm)
        n += 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(sorted(data.items())), indent=1) + "\n", encoding="utf-8")
    partial = [s for s, v in data.items() if v["coverage"] == "partial"]
    core = [s for s, v in data.items() if v["coverage"] == "core"]
    print(f"scanned {n} hashing ELF(s); {len(data)} implementations recorded in {args.out}; "
          f"{len(partial)} with an uncounted hash primitive, {len(core)} with only their own wrapper layer uncounted")
    for s in partial:
        if not args.only or s in args.only:
            v = data[s]
            print(f"  {s}: primitives={', '.join(v.get('own_primitive_symbols', [])[:6])}"
                  f"{'; direct=' + ', '.join(v['direct_primitives']) if v['direct_primitives'] else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
