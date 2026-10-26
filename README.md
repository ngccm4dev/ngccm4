
# NGCCM4

## Introduction
This repository aims to provide an automated tools, similar to [pqm4](https://github.com/mupq/pqm4) for benchmarking algorithms submitted to the New Generation Commercial Cryptography ([NGCC](https://niccs.org.cn/symmbzyjy/tzgg/pc/content/1976155884915003392/content_1976155884915003392.html)) issued by the Institute of Commercial Cryptography Standards (ICCS) in China.

Authors: 
- [Junhao Huang](https://github.com/JunhaoHuang), jhhuang_nuaa@126.com, Singapore Management University
- Claude Code Fable 5.1

--------------------
## Clone and Dependencies

Clone the repository through:
```bash
git clone --recursive-submodules https://github.com/ngccm4dev/ngccm4.git
```
This repository relies on [libopencm3(@87a080c)](https://github.com/libopencm3/libopencm3/tree/87a080c94ce67643216464821c752c1c406c6414) to provide M4-related supports.

## Set-up/Installation

The makefile system requires a few host tools to be installed:

- `make`
- `python3`
- `arm-none-eabi-gcc`, `arm-none-eabi-cpp`, `arm-none-eabi-objcopy`, `arm-none-eabi-size`
- `qemu-system-arm` for `PLATFORM=mps2-an386` and `qemu-run`
- `openocd` only if you want to flash and debug on real hardware

On Ubuntu/Debian, install them with the executable helper:

```bash
./install-deps-ubuntu.sh
```

If you do not need hardware flashing, omit `openocd`:

```bash
./install-deps-ubuntu.sh --no-openocd
```

Tool purpose:

- `gcc-arm-none-eabi` and `binutils-arm-none-eabi` provide the Cortex-M4 cross compiler and binary utilities used by the makefiles.
- `python3` is needed by `libopencm3/scripts/genlink.py` during linker-script and device setup.
- `qemu-system-arm` is required only for QEMU-based runs on `mps2-an386`.
- `openocd` is optional and is only needed for flashing supported STM32 boards.

Quick verification:

```bash
arm-none-eabi-gcc --version
python3 --version
qemu-system-arm --version
openocd --version
```

If you do not need hardware flashing, `openocd` can be omitted.


## Structure
- ngccm4:
	- common: common files for the algorithms
		- SM3 for xof and drng, required by ICCS
		- SHA3 for better comparison with NIST's variants of PQC schemes.
	- crypto_kem: Key Encapsulation Mechanism schemes
	- crypto_sign: Digital Signature schemes
	- crypto_kex: Key Exchange schemes
	- libopencm3: third-party library for ARM Cortex-M4
	- mk: Makefiles related for building and compiling
	- tools: related scripts for collecting data and maintaining website.
	- README.md

## Manual Usage

The preferred interface is the pqm4-style output-stem target. You can build a binary directly by naming the expected output stem:

```bash
make crypto_kem_{SCHEME_NAME}_ref_test
make crypto_kem_{SCHEME_NAME}_ref_speed
make crypto_kem_{SCHEME_NAME}_ref_hashing
```

The generated files are:

```bash
elf/crypto_kem_{SCHEME_NAME}_ref_test.elf
bin/crypto_kem_{SCHEME_NAME}_ref_test.bin
```

The explicit selector form is still supported when needed:

```bash
make FAMILY=crypto_kem SCHEME={SCHEME_NAME} IMPLEMENTATION=ref APP=test -j1
```

## Usage for QEMU Emulation

Typical build/run examples:

```bash
make PLATFORM=mps2-an386 crypto_kem_{SCHEME_NAME}_ref_test qemu-run -j1
```


Notes:
- The QEMU build and run should be only used for correctness verification, e.g., test, testvectors. 
- Supported families in the makefile system are `crypto_kem`, `crypto_kex`, and `crypto_sign`.
- The current repository contains KEM implementations. `crypto_kex` and `crypto_sign` are already wired into the discovery/build system
- Supported hardware platforms are `nucleo-l4r5zi` (STM32L4R5ZI) and `stm32f4discovery` (STM32F407VG); `mps2-an386` is the QEMU emulation target.
- `PLATFORM=nucleo-l4r5zi` is the default hardware build target. Pass `PLATFORM=stm32f4discovery` to build for the STM32F4DISCOVERY board.
- `-j1` means serial build mode. You can increase it, for example `-j4`, once the environment is working.

## Flashing on Real Hardware

The makefile system currently builds `.elf` and `.bin` files but does not provide a dedicated `flash` target. Use `openocd` to program the generated `.elf` file to hardware.

### Default platform: `nucleo-l4r5zi`

Build an application first:

```bash
make crypto_kem_{SCHEME_NAME}_ref_test
```

This generates:

```bash
elf/crypto_kem_{SCHEME_NAME}_ref_test.elf
bin/crypto_kem_{SCHEME_NAME}_ref_test.bin
```

Flash it with the project-local OpenOCD config:

```bash
openocd \
	-f st_nucleo_l4r5.cfg \
	-c "program elf/crypto_kem_{SCHEME_NAME}_ref_test.elf verify reset exit"
```

To receive the output, run `python3 hostside/host_unidirectional.py`.

Notes:

- `nucleo-l4r5zi` is the default `PLATFORM`, so you do not need to pass `PLATFORM=nucleo-l4r5zi`.
- This expects the board to be connected through the on-board ST-Link debugger.

### Platform: `stm32f4discovery`

Build an application for the STM32F4DISCOVERY (STM32F407VG) board:

```bash
make PLATFORM=stm32f4discovery crypto_kem_{SCHEME_NAME}_ref_test
```

This generates:

```bash
elf/crypto_kem_{SCHEME_NAME}_ref_test.elf
bin/crypto_kem_{SCHEME_NAME}_ref_test.bin
```

Flash it with OpenOCD using the ST-Link interface and the STM32F4 target config:

```bash
openocd \
	-f interface/stlink.cfg \
	-f target/stm32f4x.cfg \
	-c "program elf/crypto_kem_{SCHEME_NAME}_ref_test.elf verify reset exit"
```

These two config files ship with OpenOCD itself (no project-local `.cfg` is
needed for this board). To flash the raw `.bin` instead, give the flash base
address:

```bash
openocd \
	-f interface/stlink.cfg \
	-f target/stm32f4x.cfg \
	-c "program bin/crypto_kem_{SCHEME_NAME}_ref_test.bin 0x08000000 verify reset exit"
```

Notes:

- This expects the board to be connected through the on-board ST-Link debugger
  (the mini-USB / ST-Link port).
- If OpenOCD reports a USB permission error, install the ST-Link udev rules
  (`contrib/60-openocd.rules` from the OpenOCD distribution) or run the command
  with `sudo`.
- The STM32F4DISCOVERY's on-board ST-Link has no virtual COM port, so serial
  output (used by `host_unidirectional.py` and `benchmark_schemes.py`) requires
  an external USB-to-UART adapter wired to `USART2` on `PA2` (TX) / `PA3` (RX)
  at 38400 baud.

### Building and Benchmarking Scripts

The repository also provides two Python helper scripts for batch builds and benchmark collection:

- `build_schemes.py`: discovers implementations for selected schemes and builds every app available in the corresponding family directory.
- `benchmark_schemes.py`: runs the `speed`, `stack`, and `hashing` apps, captures their output, and writes benchmark summaries.

Both scripts must be run from the repository root:

```bash
cd ngccm4
```

Supported platforms are:

```text
mps2-an386
nucleo-l4r5zi
stm32f4discovery
```

Other `PLATFORM` values are rejected by the scripts.

#### Batch Builds

Build every implementation and every family app for one or more schemes. Omit scheme names or use `all` to build every discovered scheme:

```bash
python3 build_schemes.py
python3 build_schemes.py all
python3 build_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME...}
python3 build_schemes.py PLATFORM=stm32f4discovery {SCHEME_NAME...}
python3 build_schemes.py PLATFORM=mps2-an386 {SCHEME_NAME...}
```

Useful build options:

```bash
python3 build_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME} USE_SM3_ASM=1 USE_KECCAK=0 LTO=1 NGCC_ITERATIONS=100 -j8
```

The script searches `crypto_kem`, `crypto_kex`, and `crypto_sign`. An implementation is detected when the implementation directory contains the family entry file, for example `KEM_AlgorithmInstance.c` for KEM schemes.

#### Benchmark Runs

Run the default benchmark apps, `speed`, `stack`, and `hashing`, for all implementations of selected schemes. Omit scheme names or use `all` to benchmark every discovered scheme:

```bash
python3 benchmark_schemes.py
python3 benchmark_schemes.py all
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME...} --apps speed hashing
python3 benchmark_schemes.py PLATFORM=stm32f4discovery {SCHEME_NAME...} --apps speed hashing
python3 benchmark_schemes.py PLATFORM=mps2-an386 {SCHEME_NAME...} --apps speed hashing
```

Benchmark only selected scheme categories with `--family` (accepted names: `kem`,
`kex`, `sign`; aliases `sig`, `crypto_kem`, `crypto_kex`, `crypto_sign`, `all`;
comma-separated or repeated):

```bash
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi --family kem --apps speed
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi --family kex,sign
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi --family kex --family sign
python3 build_schemes.py PLATFORM=nucleo-l4r5zi --family sign --list
```

Scheme names and `--family` combine: `python3 benchmark_schemes.py --family kem ZEN-128`
benchmarks only the KEM implementations of ZEN-128.

Select a subset of apps with `--apps`:

```bash
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME...} --apps speed
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME...} --apps speed stack hashing
```

Forward make variables after `PLATFORM=...` as usual:

```bash
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME...} USE_SM3_ASM=1 USE_KECCAK=0 LTO=1 NGCC_ITERATIONS=100 -j8
```

For `mps2-an386`, the benchmark script runs each target through QEMU:

```bash
make PLATFORM=mps2-an386 <target> qemu-run
```

For `nucleo-l4r5zi`, the script builds each target, flashes it with:

```bash
openocd -f st_nucleo_l4r5.cfg -c "program <elf> verify reset exit"
```

For `stm32f4discovery`, the script builds each target and flashes it with the
OpenOCD-provided ST-Link and STM32F4 target configs:

```bash
openocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c "program <elf> verify reset exit"
```

Hardware benchmark output is captured from the serial port until the `#` completion marker is received. By default the script uses `/dev/ttyACM0` on Linux and `/dev/tty.usbserial-0001` on macOS, at 38400 baud. Override these when needed:

```bash
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME...} --serial-port /dev/ttyACM1 --baud 38400
```

Benchmark outputs are written to:

```text
Out/benchmark_summary.csv
Out/benchmark_summary.md
Out/benchmark_raw/<target>.run<N>.txt
```

The CSV keeps raw metric names for post-processing. The Markdown summary is grouped by family and app. The `speed` table reports average, median, minimum, and maximum. The `stack` table reports average only. The `hashing` table reports the percentage of total operation cycles spent in hashing:

```text
average(<operation>_hash_cycles) / average(<operation>_cycles) * 100
```

`<operation>_hash_cycles` is accumulated by the `HASHING_PROFILE` build of the
library (`obj/hashprof/`): the ICCS hash API in `common/auxfunc.c` (`sm3hash`,
`pseudohash`, `pseudoXOF`, `pseudoXOF_squeeze`) and the SM3 DRNG in
`common/drng.c` add the DWT cycles of every call. `<operation>_cycles` is the
whole operation measured in the same run, so the ratio is self-consistent (the
instrumentation costs well under 1%). A scheme that links its own Keccak, SHA-2
or SM3 code spends hash cycles that are not counted; `tools/hashing_coverage.py`
records that per implementation from the symbols of the linked hashing ELF (the
link uses `--gc-sections`, so a symbol in the ELF is reachable code).

To measure the hashing share of every implementation that has a complete speed
benchmark, in iteration groups so that the slow hash-based signatures do not time
out (10 iterations when 10 iterations of all operations take at most 20 minutes,
else 3, else 1):

```bash
python3 tools/plan_hashing_run.py                 # show the groups and the per-group driver commands
tools/run_hashing_benchmark.sh nucleo-l4r5zi      # run them, scan coverage, write Out/benchmark_hashing_nucleo-l4r5zi.{csv,md}
python3 tools/hashing_percentage.py Out/benchmark_hashing_iter10.csv Out/benchmark_hashing_iter3.csv \
    Out/benchmark_hashing_iter1.csv --csv Out/benchmark_hashing_percent_nucleo-l4r5zi.csv   # percentage table only
```

`tools/hashing_percentage.py` merges the per-group CSVs (later files win unless
an earlier row has more iterations), writes the merged raw CSV, a percentage CSV
with one row per operation plus an `all` row per implementation (sum of hash
cycles over sum of operation cycles), and the Markdown report.

Notes:

- Compare benchmark numbers only within the same platform. QEMU `mps2-an386` timings are useful for automation and regression checks, but they are not cycle-accurate hardware measurements.
- Hardware benchmark runs require `openocd`, a connected board, and a readable serial device.
- Use `--dry-run` to inspect the generated build, flash, and run commands without executing them.
- Use `--runs N` to repeat each target and aggregate samples in the summaries.


## Importing NGCC Reference Implementations

All NGCC Round-1 public-key candidates can be imported from a local mirror of
the NGCC submissions (the `NGCC/` directory inside this repository, which
provides `schemes.json`, `schemes/<folder>/Reference_Implementation/...` and
`schemes/<folder>/Test_Vectors/KAT_*.txt`):

```bash
python3 tools/import_ngcc.py --list                 # show what would be imported
python3 tools/import_ngcc.py                        # import every supported instance
python3 tools/import_ngcc.py --only CheetahKEM BiT  # selected scheme folders or instances
python3 tools/import_ngcc.py --ngcc-root /path/to/NGCC
```

Every instance lands in `crypto_<family>/<instance>/ref/` as a flat directory
that the Makefile discovers automatically. The importer

- strips the ICCS template files (`drng.*`, `auxfunc.*`, `KAT_*.c`), host-only
  harnesses and every file defining `main()`; the scheme then uses
  `common/drng.c` and `common/auxfunc.c` like the hand-ported schemes;
- normalises the entry file to `KEM_/KEX_/SIG_AlgorithmInstance.c` and writes a
  shim header when the scheme names its API header differently;
- rewrites `#include "../x.h"` style includes after flattening;
- writes `ngcc_config.h` (instance-selecting defines such as `PARAMS=1`, plus
  `common/ngcc_compat.h`, which turns host `printf` calls into no-ops). The build
  force-includes it for the implementation's C files and the app driver;
- writes `config.mk` with `IMPL_CFLAGS_<impl>` / `IMPL_EXCLUDE_COMMON_<impl>`
  when a scheme needs, for example, `-std=gnu11` or its own DRNG;
- records provenance in `NGCC_ORIGIN.txt` and the expected platform in
  `ngcc_tier.txt` (`board` = fits the STM32L4R5, `qemu` = mps2-an386 only).

Per-scheme rules live in `tools/ngcc_manifest.json` (copy dirs, excluded files,
defines, sed rules, patches, tier, or `unsupported` with a reason). Schemes that
need GMP, x86 intrinsics, `__int128`, or multi-megabyte keys are listed there as
unsupported and are not copied. Re-running the importer replaces the generated
directories; edit the manifest rather than the imported sources.

Imported schemes are built with `USE_KECCAK=0` (the default): many ship their
own `fips202.c`, which would clash with `common/fips202.c`.

### Submitters' Cortex-M4 implementations

Nine NGCC packages ship their own Cortex-M4 code. Four of them (DKEM, DKEX,
ADKEX, ZEN) are the origin of the hand-ported `<scheme>/m4` directories in this
repository; AFS-KEX's "ARM" tree is the reference C code in a pqm4 harness. The
remaining four are imported into `crypto_kem/<instance>/m4/` by the same
importer, driven by an `m4` block in the manifest:

| submission | zip sub-directory | instances | notes |
| --- | --- | --- | --- |
| BW-KEM | `Implementations/Additional_Implementation/ARM-performance-optimized` | BW_KEM_C128/256/512 (`m4fspeed`) | NTT/basemul assembly, SM3 M4 kernels |
| DTRU | `Implementations and Test_Vectors/Implementations/Additional_Implementation/KEM-DTRU-ARM-Optimized` | all seven DTRU sets (`m4fspeed`) | NTT/base-inversion assembly; the importer adds `vpush`/`vpop` to DTRU-Light's `ntt_fast`/`invntt_fast` (they clobber the callee-saved s17/s18) and DTRU-1024's `doublebasemul_asm_opt` (s24), see below |
| MORNING-Scabbard | `Implementations/Additional_Implementations/Cortex_M4` | scabbard128/256 | Toom/schoolbook multiplication in assembly (`SCABBARD_USE_ASM_MUL=1`); scabbard512 is too large for the board, as for `ref` |
| Rudraksh2 | `Implementations/Additional_Implementations/Cortex_M4` | lwekem128/256/512 | plain C, no assembly (on the board it runs at the same speed as `ref`, within 0.5 %); the package's `minal.c` for 128/256 sets `MINAL_BETA 0` where the reference uses 220, the importer restores the reference value so the KATs match |

The mirror keeps only `Reference_Implementation/` of each package, so the M4
trees are unpacked from the original zips first:

```bash
# zips go to NGCC/tmp/<zip_name> (zip_url and zip_sha256 are in NGCC/schemes.json)
python3 tools/extract_ngcc_m4.py            # -> NGCC/schemes/<folder>/M4_Implementation/
python3 tools/import_ngcc.py --impl m4      # -> crypto_kem/<instance>/m4/
```

The m4 import inherits the scheme-level rules and the instance's defines of the
reference import; `NGCC_ORIGIN.txt` records `impl=m4` and the zip
sub-directory. All fifteen imported m4 implementations build for the board and
match the official KAT files on QEMU.

Calling-convention check: Cortex-M4 code built with `-mfloat-abi=hard` must
preserve s16 to s31 (d8 to d15) across calls (AAPCS). DTRU-Light's
`fastntt.S`/`fastinvntt.S` keep their Barrett constants in s17/s18 and
DTRU-1024's `fastbasemul.S` uses s24 as a scratch slot, none of them saved. GCC
keeps a 64-bit zero in d8 in the hashing app's `main()` and clears the cycle
counters with `vstr d8`, so after the first NTT the DTRU-Light counters read
`0xffed0ae3` in their high words (the Barrett constant). Manifest `sed` rules on
the `m4` instances add `vpush {s16-s19}` / `vpop` and `vpush {s24-s25}` /
`vpop` (found with an OpenOCD watchpoint on the counter: `wp 0x2000094c 4 w`).
The hand-ported DKEM/DKEX/ADKEX `matacc_asm.S` also write s16 to s21 and s26 to
s29 without saving them; no corruption has been observed there, but callers
must not keep live data in those registers.

### Skip list

`mk/skip.mk` names implementations that the build system and the drivers
(`build_schemes.py`, `benchmark_schemes.py`, `kat_check.py`) leave out, for
example schemes known to hard-fault on the board or to take hours:

```make
SKIP_SCHEMES += scabbard512 Tins128          # every family / implementation of these schemes
SKIP_IMPLS   += crypto_sign/Galas-512S/ref   # family/scheme/implementation, make % wildcards allowed
```

`mk/scheme.mk` includes the file automatically, so `make`, `make list` and the
shorthand targets no longer see those implementations (`make list-skipped`
prints them). The same rules apply on the command line:

```bash
make SKIP="scabbard512 crypto_kem/%/m4"           # add to the skip list for this invocation
make NOSKIP=1 crypto_kem_scabbard512_ref_speed    # ignore the skip list
python3 benchmark_schemes.py --skip scabbard512 --skip crypto_sign/%/ref
python3 build_schemes.py --no-skip Tins128
python3 kat_check.py --skip-file mk/skip-qemu.mk  # another fragment with the same syntax
```

The drivers parse the fragment themselves and forward `SKIP=`, `NOSKIP=1` and
`SKIP_MK=` to make, so both sides always agree. Skipping does not remove
anything: the directories stay, and the benchmark site still lists the
implementations (with their previous results, or as "not yet run").

### Implementations that link other implementations

Some submissions are protocols built on other submissions. CreTAKE, for
example, is an authenticated key exchange whose package wraps copies of the
PolarLAC, ZEN and BiT reference code; its 25 instances only differ in the
protocol layer and in which KEM/signature pair they use. Such schemes are
imported protocol-layer only and link the implementations already in this
tree:

```make
# crypto_kex/CreTAKE-K2S-PLAC128-BiT128/ref/config.mk (generated from the manifest "deps" list)
IMPL_DEPS_crypto_kex_CreTAKE-K2S-PLAC128-BiT128_ref := crypto_kem/POLARLAC-128/ref crypto_sign/BiT-128/ref
```

For every dependency, `mk/scheme.mk` compiles the dependency's own sources
with its usual flags, partially links them into one relocatable object
(`obj/<impl>/deps/<dep>.o`) and keeps only its public API global
(`IMPL_DEP_KEEP_<impl>`, default `kem_* sig_* pke_* PKE_* kex_*`), so two
dependencies that both define `poly_add` or `shake128` can be linked into the
same ELF. Dependencies are built even when the current `make` selection does
not include them. The protocol sources include the dependency headers by
relative path (`../../../crypto_kem/POLARLAC-128/ref/params.h`, rewritten from
the package's `../../Common/primitives/...` by a manifest sed rule). The KEM
and signature backends themselves are benchmarked under their own names; the
package's copies are not imported.

All 25 CreTAKE instances build for the board and reproduce the official KAT
files on QEMU; the ones using BiT-256/512 are QEMU tier because those BiT sets
fault on the board. Fixing them exposed an ICCS-API gap in the hand-ported
ZEN glue, which did not write the output lengths of `kem_keygen`, `kem_enc`
and `kem_dec` (our drivers pre-fill them, CreTAKE relies on them); all six ZEN
glue files now do.

### Family drivers

All three families share the same five apps, so every scheme is measured the
same way:

| family | apps | operations reported |
| --- | --- | --- |
| `crypto_kem` | test, speed, stack, hashing, testvectors | keypair, encaps, decaps |
| `crypto_sign` | test, speed, stack, hashing, testvectors | keypair, sign, verify (59-byte messages, `-DNGCC_SIG_MLEN=` to change) |
| `crypto_kex` | test, speed, stack, hashing, testvectors | init_a, init_b, pass1 ... pass5, derive_a, derive_b (any pass count) |

### Known-answer tests

`testvectors` reproduces the ICCS `KAT_*.c` sequence (seed DRNG from
`"seed"x16`, ten counts). `kat_check.py` builds and runs it on QEMU and diffs
the output against the official `Test_Vectors/KAT_<TYPE>_<instance>.txt`:

```bash
python3 kat_check.py                    # every implementation with a KAT file
python3 kat_check.py Cheetah128 BiT-128 AFS_KEX_C128
python3 kat_check.py --tier board -j8 --md Out/kat_summary.md
```

### Tiers in the batch scripts

`build_schemes.py` and `benchmark_schemes.py` accept `--tier board|qemu|all`
(hand-ported schemes count as `board`). `benchmark_schemes.py` defaults to
`board` on hardware platforms and `all` on `mps2-an386`, and its Markdown
summary starts with a status table for targets that failed to build or run.

## Benchmark website

The board results are published as a static site at
<https://ngccm4dev.github.io/ngccm4/> (GitHub Pages, served from `docs/`).
It shows the three categories (KEM, key exchange, signatures) on separate tabs
with every column sortable (cycles per operation, hashing share of each
operation, code size, stack usage, key
sizes with proportional bars, KAT status, security level normalised to
128/192/256/384/512 bits, a link to the submission's specification PDF), a report of every
scheme without a complete board benchmark and why, and the measurement
conditions.

`docs/data/benchmark.json` (and its `data.js` twin that the page loads) is
generated from the gitignored `Out/` directory and the NGCC mirror:

```bash
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi --apps speed   # Out/benchmark_speed_nucleo-l4r5zi.{csv,md}
tools/run_hashing_benchmark.sh nucleo-l4r5zi                         # Out/benchmark_hashing_nucleo-l4r5zi.{csv,md}, Out/benchmark_hashing_coverage.json
python3 kat_check.py --md Out/kat_summary.md                        # Out/kat_summary.md, Out/kat_raw/
python3 tools/collect_ngcc_specs.py                                # docs/specs/*.pdf + tools/ngcc_specs.json (specification PDFs)
python3 tools/fetch_ngcc_links.py                                  # tools/ngcc_links.json (zip + comment URLs; only when the NGCC list changes)
python3 tools/make_site_data.py --ngcc-root NGCC                 # docs/data/benchmark.json, docs/data/data.js
git add docs && git commit -m "site: regenerate benchmark data"
```

The generator reads the speed CSV and Markdown report (including the
hand-written target status table and code-size tables), `Out/benchmark_sizes/`,
the stack logs in `Out/benchmark_raw/`, the hashing-run CSV and coverage JSON
(`Out/benchmark_hashing_nucleo-l4r5zi.csv`, `Out/benchmark_hashing_coverage.json`;
missing files only drop the "Hashing %" columns), `Out/kat_summary.md`, `Out/kat_raw/`,
`tools/ngcc_manifest.json`, `tools/ngcc_specs.json` (which PDF under each
submission's `Specification/` is the algorithm specification; written by
`tools/collect_ngcc_specs.py`, which also copies those PDFs and their addenda
into `docs/specs/` so every row links to a specification served by the site
itself rather than to the NGCC web site), `tools/ngcc_links.json` (submission
zip and public-comment URLs, from `tools/fetch_ngcc_links.py`, shown in the row
details as additional information) and
`NGCC/{schemes.json,schemes/*/Test_Vectors,results}`.
Key sizes are taken from the benchmarked binary's testvectors dump when one
exists, then from the NGCC host results, then from the official KAT file. The
generator exits non-zero when an implementation cannot be mapped to an NGCC
instance or when the NGCC instance accounting does not close; `--strict` also
fails when an implementation has no key sizes.

Preview locally with `python3 -m http.server -d docs 8000` (the page also works
when `docs/index.html` is opened directly). To publish, enable GitHub Pages once
in the repository settings: Settings, Pages, "Deploy from a branch", branch
`master`, folder `/docs`.

## Hash primitives: SM3 and Keccak assembly, `USE_KECCAK`

NGCCM4 uses SM3-based hashing and deterministic random generation (the ICCS
`auxfunc`/`drng` API in `common/`) by default. The hash primitives in `common/`
are assembly: SM3 compression (`common/sm3_bit_compress_asm_fp.S`, selected by
`USE_SM3_ASM=1`, the default) and the Keccak-f[1600] permutation
(`common/keccakf1600.S`, always in every library since 2026-10-20).

Imported schemes that bring their own hash code are routed to these primitives
at import time, so the reference code's padding, absorb/squeeze and API layers
stay as shipped while the expensive core runs in assembly:

- the assembly permutation keeps its state *bit-interleaved* (each 64-bit lane
  split into its even and odd bits; only `KeccakF1600_StateXORBytes` and
  `KeccakF1600_StateExtractBytes` understand the plain byte view), while every
  reference `fips202.c` reads and writes the lanes directly. Scheme code therefore
  calls `KeccakF1600_StatePermute_plain` (`common/keccakf1600_plain.c`), which
  interleaves the plain state into a scratch state, permutes it and extracts it
  back; the conversion costs a few hundred cycles per permutation of roughly ten
  thousand;
- every `KeccakF1600_StatePermute` definition (the Kyber/Dilithium/SPHINCS+-style
  `fips202.c` found in 69 implementation directories of Aigis-Enc+, Aigis-Sig+,
  BiT, DARTS, MAMBA-NIKE, NEV, NEV-AKE, PolarLAC, Phoenix-SHAKE, Scloudplus,
  TRINE, Weaver) is renamed to an unused `*_c` function by the importer's default
  rule `KECCAK_ASM_SED` in `tools/import_ngcc.py`, and a macro sends the file's
  calls to the plain-state wrapper; a manifest entry can opt out with
  `"keccak_asm": false`. The KAT check showed that only HQC, Lore-SHAKE,
  MAMBA-NIKE, Scloudplus (AES/SHAKE sets), GreatWall and Phoenix-SHAKE actually
  reach a Keccak permutation; in the other submissions the shipped `fips202.c` is
  dead code (they hash through the ICCS SM3 API) and the rewrite changes nothing;
- permutations under other names are routed by per-scheme `sed` rules in
  `tools/ngcc_manifest.json`: Lore (`keccak_permute`), NSS-HQC (`keccakf1600`),
  GreatWall (XKCP reference, `keccakp1600_permute`, 24-round calls only) and the
  XKCP opt64 code shared by Lynxer and ReSolveD (`KeccakP1600_Permute_24rounds`
  and `KeccakF1600_FastLoop_Absorb`); their KAT paths use `pseudoXOF` and their
  own C SHA-256 (`enc.c`), so for them the Keccak routing is dormant and the
  SHA-256 remains uncounted hash code;
- the schemes' own SM3 compression functions are routed to `sm3_bit_compress`
  (Phoenix-SM3 `crypto_hashblocks_sm3`, Aigis-Sig+ `UpdateSM3`) or directly to
  `sm3_bit_compress_asm` (Scloudplus, whose `sm3_reference.c` is a copy of the
  ICCS `auxfunc.c`). The hand-ported `crypto_sign/dilithium/ref/fips202.c` (a
  DKEX dependency) was edited the same way. BW-KEM's submitter M4 port keeps its
  own SM3 assembly kernels.

Every other scheme already hashes through the ICCS API (`sm3hash`, `pseudohash`,
`pseudoXOF`) and therefore through the SM3 assembly. The KAT check
(`kat_check.py`) is the correctness gate for these rewrites: a routed scheme must
still match its official test vectors.

`USE_KECCAK` is a different switch: it changes the apps' randomness from the
SM3 DRNG to `common/randombytes.c` (the board's hardware RNG, a fixed-seed
fallback on QEMU) and adds the C FIPS 202 API layer (`common/fips202.c`,
`fips202.h`) for scheme code guarded by `#ifdef USE_KECCAK`. It stays off by
default because the test-vector app can only reproduce the official KATs with
the deterministic SM3 DRNG. To build with it:

```bash
make PLATFORM=nucleo-l4r5zi USE_KECCAK=1 crypto_kem_{SCHEME_NAME}_ref_test
make PLATFORM=mps2-an386 USE_KECCAK=1 crypto_kem_{SCHEME_NAME}_ref_test qemu-run -j1
python3 build_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME...} USE_KECCAK=1
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME...} --apps speed hashing USE_KECCAK=1
```

Notes:

- `USE_KECCAK` and `USE_SM3_ASM` only accept `0` or `1`; other values are rejected by `mk/config.mk`.
- Changing either changes the build configuration, so the make system cleans stale `bin`, `elf`, and `obj` outputs automatically.
- With `USE_SM3_ASM=0` the routed schemes fall back to the C SM3 compression in `common/auxfunc.c` (or their own, for Scloudplus); the Keccak routing has no C fallback switch, the assembly permutation is always used.
- The hashing app counts the assembly primitives for every caller: the hashing ELF is linked with `--wrap=KeccakF1600_StatePermute --wrap=KeccakF1600_StatePermute_plain --wrap=sm3_bit_compress_asm` and `common/hashprof.c` provides nesting-safe trampolines (`common/hashprof.h`), so hash cycles are counted once whether a scheme calls the ICCS wrappers or the primitives directly.


## Licenses

**ngccm4** is a collection of code from different sources, and different parts are under different terms.
Nothing in this section is legal advice; the license text that ships with each component is authoritative.

### Code written for ngccm4

The build system (`Makefile`, `mk/`, `ldscripts/`), the Python drivers and tools (`build_schemes.py`,
`benchmark_schemes.py`, `kat_check.py`, `tools/`, `hostside/`), the board/QEMU HAL and benchmark apps
(`common/hal-*.c`, `crypto_*/{speed,stack,hashing,test,testvectors}.c`), the SM3 compression-function
assembly (`common/sm3_bit_compress_asm*.S`), the hand-written Cortex-M4 ports in `crypto_*/<scheme>/m4`
for ZEN, DKEM, DKEX and ADKEX, the benchmark website (`docs/`) and the published measurement data are
dual-licensed: you may use them under the terms of either the
[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) or
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/), at your option
(`SPDX-License-Identifier: Apache-2.0 OR CC0-1.0`). This is the same convention as
[pqm4](https://github.com/mupq/pqm4), on which the layout of this repository is modelled.

### Third-party support code in `common/`

- `common/fips202.c` / `fips202.h` are based on the public-domain Keccak reference and "TweetFips202"
  implementations.
- `common/keccakf1600.S` is the Cortex-M4 Keccak-f[1600] permutation from the Keccak Code Package / pqm4;
  its authors waived all copyright (CC0).
- `common/sha256_armv7m.S` and `common/internal-sha256.h` are Copyright (C) 2021 Southern Storm Software,
  Pty Ltd, under the MIT license stated in the file headers.
- `crypto_sign/dilithium/` (used only as the signature component of the hand-ported DKEX schemes) is the
  CRYSTALS-Dilithium reference code; see its `LICENSE` (public domain / CC0, or Apache 2.0, or GPL 2.0)
  and `AUTHORS.md`.

### libopencm3

`libopencm3/` is a git submodule of [libopencm3](https://github.com/libopencm3/libopencm3), licensed under
the GNU Lesser General Public License v3 (its examples under the GPL v3). Copies of both licenses are kept
in `COPYING.LGPL3` and `COPYING.GPL3` in the repository root. Board ELFs built by this repository link
against it and are therefore subject to the LGPL's terms.

### NGCC candidate implementations

The reference implementations under `crypto_kem/`, `crypto_kex/` and `crypto_sign/` (and the submitters'
own Cortex-M4 ports imported as `<scheme>/m4`) are taken from the Round-1 submission packages published by
the Institute of Commercial Cryptography Standards (ICCS) on the
[NGCC page](https://niccs.org.cn/symmbzyjy/tzgg/pc/content/1976155884915003392/content_1976155884915003392.html).
They are the work of the respective submission teams, who retain the copyright; each scheme should be
credited to its team, and the submission package is the authoritative source.

- This repository does not grant any license to the NGCC code. The terms are whatever the submission
  package states, and they differ from package to package: many files declare themselves public domain or
  CC0 (for example Aigis, BiT, DARTS, Galas, GreatWall, Phoenix, TRINE, TSUOV), several use the MIT license
  (for example Lynxer, ReSolveD, SYDO), some mix MIT and CC0 files (the MPC-in-the-head family), QIMEN-PIKE and SQIsign2D ship
  Apache-2.0 `LICENSE`/`NOTICE` files, and a number of packages carry no license statement at all.
  Some packages also bundle third-party components with their own notices (NIST's KAT `rng.c`, Intel IPP
  Crypto sources, and others). Check the package before using any of this code outside benchmarking.
- The code is redistributed here for the purpose of benchmarking and research. Every imported directory
  contains an `NGCC_ORIGIN.txt` naming the submission, the package SHA-256 and the instance it was taken
  from, and listing the files that `tools/import_ngcc.py` left out (KAT harnesses, duplicated DRNG/hash
  glue). The only textual changes are the per-package `sed` rules in `tools/ngcc_manifest.json`, which fix build or
  correctness problems noted in the manifest; the sources are otherwise as published.
- The schemes' algorithm-specification PDFs served by the website (`docs/specs/`) are likewise the
  submitters' documents, copied unchanged from the submission packages.

If you are a submitter and would like your package to be attributed, licensed or described differently
here, please open an issue or contact the maintainer listed above.
