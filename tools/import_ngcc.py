#!/usr/bin/env python3
"""Import NGCC reference implementations into the ngccm4 layout.

Reads NGCC/schemes.json (the NGCC mirror manifest) together with the curated
tools/ngcc_manifest.json and copies every supported instance into

    crypto_<family>/<instance>/ref/

as a flat directory that the mk/ build system can discover:

  * all C/assembly sources and headers are flattened into one directory
    (headers that lived in sub-directories are additionally kept at their
    relative path so `#include "sub/x.h"` keeps working);
  * ICCS template files (drng.*, auxfunc.*, KAT_*.c), host-only harness files
    and every file defining main() are stripped;
  * `#include "../x.h"` style includes are rewritten to the flattened name;
  * the entry file is normalised to KEM_/KEX_/SIG_AlgorithmInstance.c (with a
    shim header when the scheme names its header differently);
  * instance-selecting defines go into ngcc_config.h, which mk/scheme.mk
    force-includes; per-implementation compiler flags go into config.mk;
  * NGCC_ORIGIN.txt records provenance, ngcc_tier.txt the expected platform;
  * a manifest "deps" list (other implementations of this tree, e.g.
    crypto_kem/POLARLAC-128/ref) becomes IMPL_DEPS_<impl> in config.mk: the
    build links those implementations into this one, reduced to their public
    API (see mk/scheme.mk). Used for protocol submissions such as CreTAKE whose
    package only wraps other submissions; only the protocol layer is copied.

Submitter-provided Cortex-M4 implementations are imported the same way into

    crypto_<family>/<instance>/m4/

from a manifest "m4" block (see tools/ngcc_manifest.json "_comment"). Their
sources live in the submission zip, not in the mirror's Reference_Implementation
tree: run tools/extract_ngcc_m4.py first, which unpacks the configured zip
sub-directory into NGCC/schemes/<folder>/M4_Implementation/.

Usage:
    python3 tools/import_ngcc.py [--ngcc-root NGCC] [--only NAME ...]
                                 [--family kem|kex|sign] [--list] [--dry-run]
                                 [--force]

Re-running the importer replaces directories it generated earlier (they are
recognised by NGCC_ORIGIN.txt). A directory without that marker is never
touched unless --force is given.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

IMPORTER_VERSION = "1"

FAMILY_DIR = {"KEM": "crypto_kem", "KEX": "crypto_kex", "SIG": "crypto_sign"}
FAMILY_PREFIX = {"KEM": "KEM", "KEX": "KEX", "SIG": "SIG"}
FAMILY_TAG = {"crypto_kem": "kem", "crypto_kex": "kex", "crypto_sign": "sign"}
# A definition of one of these functions identifies the entry .c file.
FAMILY_ENTRY_FUNC = {"KEM": "kem_keygen", "KEX": "kex_init_a", "SIG": "sig_keygen"}
FAMILY_LEN_FUNC = {"KEM": "kem_get_pk_len_bytes", "KEX": "kex_get_passes_num", "SIG": "sig_get_pk_len_bytes"}

SOURCE_EXTS = {".c", ".h", ".S", ".s", ".i", ".inc", ".macros", ".def"}
HEADER_EXTS = {".h", ".inc", ".macros", ".def", ".i"}

# Directory names (any depth) that are never copied unless a manifest entry
# lists them explicitly in copy_dirs.
DEFAULT_EXCLUDE_DIRS = {
    "test", "tests", "speed_test", "test_speed", "KAT", "kat", "output", "bin",
    "obj", "build", "avx2", "neon", "armv8a-neon", "keccak4x", "x86_64",
    "aarch64", "precomputations_rANS", "fips202-ref", "plain32",
    "Self_Evaluation", "doc", "docs", "benchmark", "benchmarks", "examples",
}
# BAG-Piglet keeps its entry file in src/kat/, so "kat" is excluded by
# default but re-enabled per scheme through copy_dirs / include_dirs.

# Basenames (regexes, full match) that are always stripped: ICCS template
# files, host-only KAT/speed harnesses and RNG bridges.
DEFAULT_STRIP_FILES = [
    r"drng\.[ch]", r"auxfunc\.[ch]", r"KAT_.*\.c", r"PQCgenKAT.*\.c",
    r"SPEED_.*\.c", r"cpucycles\.[ch]", r"speed_print\.[ch]", r"test.*\.c",
    r".*_test\.c", r"tests_main\.c", r"bench.*\.c", r".*_bench.*\.c",
    r"main.*\.c", r"selftest\.c", r"check_kat\.c", r"kat_gen\.c",
    r"kat_verify\.c", r"verify_kat.*\.c", r"rng\.[ch]", r"randombytes_api\.c",
    r"kem_random\.c", r"randomness_os\.c", r"randombytes_system\.c",
    r"random\.c", r"kat_random\.c", r"api_pkc_kat_count\.c",
]

MAIN_RE = re.compile(r"^[ \t]*(?:int|void)[ \t]+main[ \t]*\(", re.MULTILINE)

# Headers provided by common/ that replace the scheme's own (stripped) copies:
# includes such as "kat_test/drng.h" are rewritten to the bare name.
COMMON_HEADERS = {"drng.h", "auxfunc.h"}

# Source rewrites applied to every imported .c/.h file (regex, replacement).
DEFAULT_SED = [
    # x86 intrinsics headers: harmless to drop when no intrinsics are used
    # (schemes that really use them fail to compile and are listed unsupported).
    [r"^[ \t]*#[ \t]*include[ \t]*<(?:immintrin|x86intrin|emmintrin|tmmintrin|smmintrin|wmmintrin)\.h>[ \t]*\n", ""],
    # Linux-only header pulled in by NEV's cca.c; errno values are unused.
    [r"^[ \t]*#[ \t]*include[ \t]*<asm-generic/errno\.h>[ \t]*\n", ""],
    # The driver owns the global DRNG context; schemes must only declare it.
    [r"^[ \t]*DRNG_ctx[ \t]+drng_algorithm[ \t]*;", "extern DRNG_ctx drng_algorithm;"],
]
# Route a scheme's own Keccak-f[1600] permutation to the assembly one in
# common/keccakf1600.S (always in the library): the definition is renamed to an
# unused *_c function and a macro sends every later call in the file to
# KeccakF1600_StatePermute_plain (keccakf1600_plain.c), which converts the plain
# lane state to the bit-interleaved form the assembly works on and back. Covers the Kyber/Dilithium/SPHINCS+-style fips202.c files (static
# or not, "uint64_t *state" or "uint64_t state[25]"). Permutations under other
# names (XKCP, Lore, HQC) get scheme-specific sed rules in the manifest. A
# scheme entry can opt out with "keccak_asm": false.
KECCAK_ASM_SED = [
    [r"^([ \t]*)(?:static[ \t]+)?void[ \t]+KeccakF1600_StatePermute[ \t]*\([ \t]*uint64_t[ \t]*(?:\*[ \t]*(\w+)|(\w+)[ \t]*\[[ \t]*25[ \t]*\])[ \t]*\)[ \t]*(\{?)[ \t]*$",
     r'\1#include "keccakf1600.h"\n\1#define KeccakF1600_StatePermute KeccakF1600_StatePermute_plain\n\1static void __attribute__((unused)) KeccakF1600_StatePermute_c(uint64_t *\2\3)\4'],
]

INCLUDE_RE = re.compile(r'^([ \t]*#[ \t]*include[ \t]*)"([^"\n]+)"', re.MULTILINE)


class ImportError_(Exception):
    pass


def sanitize_name(name: str) -> str:
    out = re.sub(r"[^A-Za-z0-9_-]+", "-", name)
    out = re.sub(r"-{2,}", "-", out).strip("-")
    return out


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def merged(scheme_cfg: dict, inst_cfg: dict, key: str, default):
    """Combine a scheme-level and an instance-level manifest value."""
    base = scheme_cfg.get(key, default)
    override = inst_cfg.get(key)
    if override is None:
        return base
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        out.update(override)
        return out
    if isinstance(base, list) and isinstance(override, list):
        return list(base) + list(override)
    return override


def file_defines_entry(text: str, func: str) -> bool:
    return re.search(r"\bint\s+" + re.escape(func) + r"\s*\([^;{]*\)\s*\{", text) is not None


def collect_sources(root: Path, exclude_dirs: set[str], extra_include_dirs: list[str], prefix: str = "") -> list[tuple[Path, str]]:
    """Return (absolute path, path relative to root) for every source file.

    `prefix` (the copy-dir name for copy dirs other than ".") is prepended to
    the relative path so manifest exclude/rename rules can address files of a
    specific copy dir, e.g. "kem/KEM_AlgorithmInstance.c".
    """
    found: list[tuple[Path, str]] = []
    allowed_subtrees = [root / d for d in extra_include_dirs]
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        kept = []
        for d in dirnames:
            candidate = current / d
            if d in exclude_dirs and not any(
                candidate == a or a in candidate.parents or candidate in a.parents for a in allowed_subtrees
            ):
                continue
            kept.append(d)
        dirnames[:] = sorted(kept)
        for f in sorted(filenames):
            p = current / f
            if p.suffix in SOURCE_EXTS:
                rel = os.path.relpath(p, root)
                found.append((p, os.path.join(prefix, rel) if prefix else rel))
    return found


def strip_reason(rel: str, text: str | None, strip_res: list[re.Pattern], exclude_globs: list[str], keep: set[str]) -> str | None:
    base = os.path.basename(rel)
    if base in keep or rel in keep:
        return None
    for g in exclude_globs:
        if fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(base, g):
            return f"manifest exclude '{g}'"
    for r in strip_res:
        if r.fullmatch(base):
            return f"strip rule '{r.pattern}'"
    if text is not None and base.endswith(".c") and MAIN_RE.search(text):
        return "defines main()"
    return None


def rewrite_includes(dest: Path) -> int:
    """Rewrite includes that no longer resolve after flattening."""
    changed = 0
    names = {p.name for p in dest.iterdir() if p.is_file()} | COMMON_HEADERS

    def fix(match: re.Match) -> str:
        prefix, target = match.group(1), match.group(2)
        if "/" not in target:
            return match.group(0)
        stripped = re.sub(r"^(\.\./)+", "", target)
        stripped = re.sub(r"^\./", "", stripped)
        if (dest / stripped).is_file():
            new = stripped
        elif os.path.basename(stripped) in names:
            new = os.path.basename(stripped)
        else:
            return match.group(0)
        if new == target:
            return match.group(0)
        return f'{prefix}"{new}"'

    for p in sorted(dest.rglob("*")):
        if not p.is_file() or p.suffix not in SOURCE_EXTS:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="surrogateescape")
        except OSError:
            continue
        new_text, n = INCLUDE_RE.subn(fix, text)
        if n and new_text != text:
            p.write_text(new_text, encoding="utf-8", errors="surrogateescape")
            changed += 1
    return changed


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


M4_SUBDIR = "M4_Implementation"
# Keys of a manifest entry that describe the reference import only and must not
# leak into the configuration of the m4 implementation.
M4_INHERIT_SKIP = {"instances", "copy_dirs", "m4", "variants", "only_instances", "skip_instances",
                   "status", "reason", "tier", "_note"}
M4_BLOCK_KEYS = {"instances", "zip_dir", "zip_exclude", "note", "_note"}


def m4_effective_cfg(scheme_cfg: dict, inst_cfg: dict, m4_cfg: dict, m4_inst_cfg: dict) -> tuple[dict, dict]:
    """Configuration of an m4 job: scheme-level rules (minus reference-only keys), overlaid with the
    scheme's m4 block; instance-level: the reference instance's defines, overlaid with the m4 instance."""
    eff_scheme = {k: v for k, v in scheme_cfg.items() if k not in M4_INHERIT_SKIP}
    for k, v in m4_cfg.items():
        if k in M4_BLOCK_KEYS:
            continue
        eff_scheme[k] = merged(eff_scheme, {k: v}, k, None) if k in eff_scheme else v
    eff_inst = {}
    if inst_cfg.get("defines"):
        eff_inst["defines"] = dict(inst_cfg["defines"])
    if inst_cfg.get("name"):
        eff_inst["name"] = inst_cfg["name"]
    for k, v in m4_inst_cfg.items():
        if k == "dir":
            continue
        eff_inst[k] = merged(eff_inst, {k: v}, k, None) if k in eff_inst else v
    return eff_scheme, eff_inst


class Job:
    def __init__(self, scheme: dict, inst: dict, scheme_cfg: dict, inst_cfg: dict, variant: dict | None,
                 impl: str = "ref", m4_dir: str | None = None, m4_block: dict | None = None):
        self.scheme = scheme
        self.inst = inst
        self.impl = impl
        self.m4_dir = m4_dir
        self.m4_block = m4_block or {}
        if impl == "m4":
            scheme_cfg, inst_cfg = m4_effective_cfg(scheme_cfg, inst_cfg, self.m4_block, (self.m4_block.get("instances") or {}).get(inst["name"], {}))
        self.scheme_cfg = scheme_cfg
        self.inst_cfg = inst_cfg
        self.variant = variant or {}
        self.category = scheme["category"]
        base_name = inst_cfg.get("name") or inst["name"]
        if self.variant:
            base_name = self.variant.get("name") or f"{base_name}-{self.variant['suffix']}"
        self.name = sanitize_name(base_name)
        self.family_dir = FAMILY_DIR[self.category]
        self.tier = self.variant.get("tier") or inst_cfg.get("tier") or scheme_cfg.get("tier", "board")

    @property
    def inst_rel_dir(self) -> str:
        """Instance source directory, relative to NGCC/schemes/<folder>/."""
        if self.impl == "m4":
            return f"{M4_SUBDIR}/{self.m4_dir}"
        return self.inst["dir"]

    def cfg(self, key: str, default):
        value = merged(self.scheme_cfg, self.inst_cfg, key, default)
        if self.variant and key in self.variant:
            v = self.variant[key]
            if isinstance(value, dict) and isinstance(v, dict):
                value = dict(value)
                value.update(v)
            elif isinstance(value, list) and isinstance(v, list):
                value = list(value) + list(v)
            else:
                value = v
        return value

    @property
    def dest(self) -> Path:
        return Path(self.family_dir) / self.name / self.impl

    @property
    def label(self) -> str:
        return (f"{self.scheme['folder']}/{self.inst['name']}" + (f" [{self.variant.get('suffix')}]" if self.variant else "")
                + (" (m4)" if self.impl == "m4" else ""))


def resolve_copy_dirs(ngcc_root: Path, scheme_folder: str, inst_dir: Path, copy_dirs: list[str]) -> list[Path]:
    out = []
    for d in copy_dirs:
        if d.startswith("@"):
            out.append(ngcc_root / "schemes" / scheme_folder / d[1:])
        else:
            out.append(inst_dir / d)
    return out


def run_job(job: Job, ngcc_root: Path, repo: Path, args) -> tuple[bool, str]:
    scheme_folder = job.scheme["folder"]
    inst_dir = ngcc_root / "schemes" / scheme_folder / job.inst_rel_dir
    if not inst_dir.is_dir():
        hint = " (run tools/extract_ngcc_m4.py first)" if job.impl == "m4" else ""
        return False, f"instance dir missing: {inst_dir}{hint}"

    dest = repo / job.dest
    marker = dest / "NGCC_ORIGIN.txt"
    if dest.exists():
        if not marker.exists() and not args.force:
            return False, f"{job.dest} exists and was not generated by the importer (use --force)"
    if args.dry_run:
        return True, f"would import into {job.dest}"

    copy_dirs = resolve_copy_dirs(ngcc_root, scheme_folder, inst_dir, job.cfg("copy_dirs", ["."]))
    exclude_dirs = set(DEFAULT_EXCLUDE_DIRS) | set(job.cfg("exclude_dirs", []))
    include_dirs = job.cfg("include_dirs", [])  # sub-directories to keep although excluded by default
    strip_res = [re.compile(r) for r in DEFAULT_STRIP_FILES + job.cfg("strip_files", [])]
    exclude_globs = job.cfg("exclude_files", [])
    keep_files = set(job.cfg("keep_files", []))
    renames = job.cfg("rename", {})
    keep_as = job.cfg("keep_as", {})  # {"drng.c": "phoenix_drng.c"}: keep a normally-stripped file under a new name

    # Collect all candidate files.
    files: list[tuple[Path, str]] = []
    for spec, root in zip(job.cfg("copy_dirs", ["."]), copy_dirs):
        if not root.is_dir():
            return False, f"copy dir missing: {root}"
        prefix = "" if spec == "." else os.path.basename(spec.rstrip("/"))
        files.extend(collect_sources(root, exclude_dirs, include_dirs, prefix))

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    placed: dict[str, str] = {}
    stripped: list[str] = []
    for src, rel in files:
        base = os.path.basename(rel)
        text = None
        if src.suffix == ".c":
            text = src.read_text(encoding="utf-8", errors="surrogateescape")
        target_name = keep_as.get(base) or keep_as.get(rel)
        if target_name is None:
            reason = strip_reason(rel, text, strip_res, exclude_globs, keep_files)
            if reason is not None:
                stripped.append(f"{rel} ({reason})")
                continue
            target_name = renames.get(rel) or renames.get(base) or base
        if target_name in placed:
            shutil.rmtree(dest)
            return False, f"basename collision: {rel} and {placed[target_name]} both map to {target_name}"
        placed[target_name] = rel
        shutil.copyfile(src, dest / target_name)
        # Keep headers reachable under their original relative path as well.
        if src.suffix in HEADER_EXTS and os.path.dirname(rel):
            sub = dest / rel
            sub.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, sub)

    # Entry file normalisation.
    prefix = FAMILY_PREFIX[job.category]
    entry_c = f"{prefix}_AlgorithmInstance.c"
    entry_h = f"{prefix}_AlgorithmInstance.h"
    entry_func = FAMILY_ENTRY_FUNC[job.category]
    if not (dest / entry_c).exists():
        candidates = []
        wanted = job.cfg("entry_c", None)
        for p in sorted(dest.glob("*.c")):
            if wanted and p.name != wanted:
                continue
            if file_defines_entry(p.read_text(encoding="utf-8", errors="surrogateescape"), entry_func):
                candidates.append(p)
        if len(candidates) != 1:
            shutil.rmtree(dest)
            return False, f"cannot identify entry file defining {entry_func}: {[c.name for c in candidates]}"
        candidates[0].rename(dest / entry_c)
    if not (dest / entry_h).exists():
        len_func = FAMILY_LEN_FUNC[job.category]
        wanted = job.cfg("entry_h", None)
        headers = []
        for p in sorted(dest.glob("*.h")):
            if wanted and p.name != wanted:
                continue
            if re.search(r"\b" + re.escape(len_func) + r"\s*\(", p.read_text(encoding="utf-8", errors="surrogateescape")):
                headers.append(p)
        if len(headers) != 1:
            shutil.rmtree(dest)
            return False, f"cannot identify API header declaring {len_func}: {[h.name for h in headers]}"
        write_text(dest / entry_h, f'/* generated by tools/import_ngcc.py */\n#include "{headers[0].name}"\n')

    # Extra generated files.
    for fname, content in job.cfg("extra_files", {}).items():
        write_text(dest / fname, content if content.endswith("\n") else content + "\n")

    # ngcc_config.h: force-included by mk/scheme.mk for every source of the impl.
    defines = job.cfg("defines", {})
    lines = [
        "/* generated by tools/import_ngcc.py - instance configuration */",
        "#ifndef NGCC_CONFIG_H",
        "#define NGCC_CONFIG_H",
        "#define NGCC_M4 1",
        f'#define NGCC_INSTANCE_NAME "{job.name}"',
        "#ifndef NDEBUG",
        "#define NDEBUG 1",
        "#endif",
    ]
    for key, value in defines.items():
        lines.append(f"#ifndef {key}")
        lines.append(f"#define {key} {value}".rstrip())
        lines.append("#endif")
    if job.cfg("compat", True):
        lines.append('#include "ngcc_compat.h"')
    lines.append("#endif /* NGCC_CONFIG_H */")
    write_text(dest / "ngcc_config.h", "\n".join(lines) + "\n")

    # config.mk: per-implementation make variables.
    impl_name = f"{job.family_dir}_{job.name}_{job.impl}"
    mk_lines = ["# generated by tools/import_ngcc.py"]
    cflags = job.cfg("cflags", "")
    if cflags:
        mk_lines.append(f"IMPL_CFLAGS_{impl_name} := {cflags}")
    exclude_common = job.cfg("exclude_common", [])
    if exclude_common:
        mk_lines.append(f"IMPL_EXCLUDE_COMMON_{impl_name} := {' '.join(exclude_common)}")
    deps = job.cfg("deps", [])
    if deps:
        for dep in deps:
            if not (repo / dep).is_dir():
                shutil.rmtree(dest)
                return False, f"dependency implementation missing: {dep}"
        mk_lines.append(f"IMPL_DEPS_{impl_name} := {' '.join(deps)}")
        dep_keep = job.cfg("dep_keep", [])
        if dep_keep:
            mk_lines.append(f"IMPL_DEP_KEEP_{impl_name} := {' '.join(dep_keep)}")
    if len(mk_lines) > 1:
        write_text(dest / "config.mk", "\n".join(mk_lines) + "\n")

    # Include rewriting, sed rules, patches.
    rewritten = rewrite_includes(dest)
    default_sed = [["*.c", pat, repl] for pat, repl in DEFAULT_SED] + [["*.h", pat, repl] for pat, repl in DEFAULT_SED]
    if job.cfg("keccak_asm", True):
        default_sed += [["*.c", pat, repl] for pat, repl in KECCAK_ASM_SED]
    for rule in default_sed + job.cfg("sed", []):
        glob_pat, pattern, repl = rule
        for p in sorted(dest.glob(glob_pat)):
            text = p.read_text(encoding="utf-8", errors="surrogateescape")
            new_text = re.sub(pattern, repl, text, flags=re.MULTILINE)
            if new_text != text:
                p.write_text(new_text, encoding="utf-8", errors="surrogateescape")
    for patch in job.cfg("patches", []):
        patch_path = repo / patch
        if not patch_path.exists():
            shutil.rmtree(dest)
            return False, f"patch not found: {patch}"
        result = subprocess.run(
            ["patch", "-p1", "-s", "-d", str(dest), "-i", str(patch_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            shutil.rmtree(dest)
            return False, f"patch {patch} failed: {result.stdout}{result.stderr}"

    # Provenance and tier.
    kat_name = job.cfg("kat", None) or f"KAT_{job.category}_{job.inst['name']}.txt"
    kat_path = ngcc_root / "schemes" / scheme_folder / "Test_Vectors" / kat_name
    origin = [
        f"importer_version={IMPORTER_VERSION}",
        f"ngcc_scheme={scheme_folder}",
        f"ngcc_title={job.scheme.get('title', '')}",
        f"ngcc_instance={job.inst['name']}",
        f"ngcc_instance_dir={job.inst_rel_dir}",
        f"impl={job.impl}",
        f"ngcc_zip_sha256={job.scheme.get('zip_sha256', '')}",
        f"ngcc_category={job.category}",
        f"tier={job.tier}",
        f"kat_file={'Test_Vectors/' + kat_name if kat_path.exists() else ''}",
        f"copy_dirs={';'.join(str(d.relative_to(ngcc_root)) for d in copy_dirs)}",
        f"deps={';'.join(job.cfg('deps', []))}",
        "stripped=" + ";".join(stripped),
    ]
    if job.impl == "m4":
        origin.insert(5, f"ngcc_m4_zip_dir={job.m4_block.get('zip_dir', '')}")
    write_text(dest / "NGCC_ORIGIN.txt", "\n".join(origin) + "\n")
    write_text(dest / "ngcc_tier.txt", job.tier + "\n")

    note = f"{len(placed)} files, {len(stripped)} stripped, {rewritten} include rewrites"
    if not kat_path.exists():
        note += f", no KAT file {kat_name}"
    return True, note


def build_jobs(manifest: dict, schemes: list[dict], args) -> tuple[list[Job], list[str]]:
    jobs: list[Job] = []
    notes: list[str] = []
    for scheme in schemes:
        folder = scheme["folder"]
        cfg = manifest.get(folder)
        if cfg is None:
            notes.append(f"skip {folder}: no manifest entry")
            continue
        status = cfg.get("status", "supported")
        if status in ("skip", "unsupported"):
            notes.append(f"{status} {folder}: {cfg.get('reason', '')}")
            continue
        if args.family and FAMILY_TAG[FAMILY_DIR[scheme["category"]]] != args.family:
            continue
        skip_instances = set(cfg.get("skip_instances", []))
        only_instances = cfg.get("only_instances")
        for inst in scheme["instances"]:
            if inst["name"] in skip_instances or inst.get("component"):
                continue
            if only_instances and inst["name"] not in only_instances:
                continue
            inst_cfg = cfg.get("instances", {}).get(inst["name"], {})
            if inst_cfg.get("status") in ("skip", "unsupported"):
                notes.append(f"{inst_cfg['status']} {folder}/{inst['name']}: {inst_cfg.get('reason', '')}")
                continue
            variants = inst_cfg.get("variants") or cfg.get("variants")
            if variants:
                for variant in variants:
                    jobs.append(Job(scheme, inst, cfg, inst_cfg, variant))
            else:
                jobs.append(Job(scheme, inst, cfg, inst_cfg, None))
            # Submitter-provided Cortex-M4 implementation of the same instance.
            m4_block = cfg.get("m4") or {}
            if m4_block.get("status") in ("skip", "unsupported"):
                if inst is scheme["instances"][0]:
                    notes.append(f"{m4_block['status']} {folder} (m4): {m4_block.get('reason', '')}")
                continue
            m4_inst = (m4_block.get("instances") or {}).get(inst["name"])
            if m4_inst and m4_inst.get("status") not in ("skip", "unsupported"):
                m4_variants = m4_inst.get("variants")
                if m4_variants:
                    for variant in m4_variants:
                        jobs.append(Job(scheme, inst, cfg, inst_cfg, variant, impl="m4", m4_dir=m4_inst["dir"], m4_block=m4_block))
                else:
                    jobs.append(Job(scheme, inst, cfg, inst_cfg, None, impl="m4", m4_dir=m4_inst["dir"], m4_block=m4_block))
            elif m4_inst:
                notes.append(f"{m4_inst['status']} {folder}/{inst['name']} (m4): {m4_inst.get('reason', '')}")
    if args.only:
        wanted = set(args.only)
        jobs = [j for j in jobs if j.scheme["folder"] in wanted or j.inst["name"] in wanted or j.name in wanted]
    if getattr(args, "impl", None):
        jobs = [j for j in jobs if j.impl == args.impl]
    return jobs, notes


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ngcc-root", default=None, help="NGCC mirror root (default: NGCC/ inside this repo)")
    parser.add_argument("--manifest", default=None, help="curated manifest (default: tools/ngcc_manifest.json)")
    parser.add_argument("--only", nargs="*", default=None, help="scheme folders or instance names to import")
    parser.add_argument("--family", choices=("kem", "kex", "sign"), default=None)
    parser.add_argument("--impl", choices=("ref", "m4"), default=None, help="only import this implementation kind")
    parser.add_argument("--list", action="store_true", help="list what would be imported and exit")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="replace directories not generated by the importer")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--prune", action="store_true",
                        help="remove importer-generated directories that are no longer produced by the manifest")
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parent.parent
    ngcc_root = Path(args.ngcc_root).resolve() if args.ngcc_root else (repo / "NGCC")
    manifest_path = Path(args.manifest) if args.manifest else repo / "tools" / "ngcc_manifest.json"

    schemes = load_json(ngcc_root / "schemes.json")["schemes"]
    manifest = load_json(manifest_path)
    manifest.pop("_comment", None)

    jobs, notes = build_jobs(manifest, schemes, args)
    for n in notes:
        if not args.only:
            print(n)
    if args.list:
        for job in jobs:
            print(f"{job.label:45s} -> {job.dest} (tier {job.tier})")
        print(f"{len(jobs)} instances")
        return 0

    if args.prune and not args.only and not args.family and not args.impl:
        wanted = {str(job.dest) for job in jobs}
        for family_dir in FAMILY_DIR.values():
            for marker in sorted((repo / family_dir).glob("*/*/NGCC_ORIGIN.txt")):
                rel = str(marker.parent.relative_to(repo))
                if rel not in wanted:
                    print(f"prune {rel}")
                    if not args.dry_run:
                        shutil.rmtree(marker.parent)
                        if not any(marker.parent.parent.iterdir()):
                            marker.parent.parent.rmdir()

    ok = 0
    failures: list[str] = []
    for job in jobs:
        success, msg = run_job(job, ngcc_root, repo, args)
        status = "ok  " if success else "FAIL"
        print(f"{status} {job.label:45s} -> {job.dest}: {msg}")
        if success:
            ok += 1
        else:
            failures.append(f"{job.label}: {msg}")
            if args.fail_fast:
                break
    print(f"\nimported {ok}/{len(jobs)} instances")
    if failures:
        print("failures:")
        for f in failures:
            print("  " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
