
# NGCCM4

## Introduction
This repository aims to provide an automated tools, similar to [pqm4](https://github.com/mupq/pqm4) for benchmarking algorithms submitted to the New Generation Commercial Cryptography ([NGCC](https://niccs.org.cn/symmbzyjy/tzgg/pc/content/1976155884915003392/content_1976155884915003392.html)) issued by the Institute of Commercial Cryptography Standards (ICCS) in China.

Authors: [Junhao Huang](https://github.com/JunhaoHuang), jhhuang_nuaa@126.com, Singapore Management University.

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
		- DKEM
		- ZEN: NTRU-based KEM
	- crypto_sign: Digital Signature schemes
	- crypto_kex: Key Exchange schemes
	- libopencm3: third-party library for ARM Cortex-M4
	- mk: Makefiles related for building and compiling
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
| DTRU | `Implementations and Test_Vectors/Implementations/Additional_Implementation/KEM-DTRU-ARM-Optimized` | all seven DTRU sets (`m4fspeed`) | NTT/base-inversion assembly |
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
with every column sortable (cycles per operation, code size, stack usage, key
sizes with proportional bars, KAT status, security level normalised to
128/192/256/384/512 bits, a link to the submission's specification PDF), a report of every
scheme without a complete board benchmark and why, and the measurement
conditions.

`docs/data/benchmark.json` (and its `data.js` twin that the page loads) is
generated from the gitignored `Out/` directory and the NGCC mirror:

```bash
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi --apps speed   # Out/benchmark_speed_nucleo-l4r5zi.{csv,md}
python3 kat_check.py --md Out/kat_summary.md                        # Out/kat_summary.md, Out/kat_raw/
python3 tools/collect_ngcc_specs.py                                # docs/specs/*.pdf + tools/ngcc_specs.json (specification PDFs)
python3 tools/fetch_ngcc_links.py                                  # tools/ngcc_links.json (zip + comment URLs; only when the NGCC list changes)
python3 tools/make_site_data.py --ngcc-root NGCC                 # docs/data/benchmark.json, docs/data/data.js
git add docs && git commit -m "site: regenerate benchmark data"
```

The generator reads the speed CSV and Markdown report (including the
hand-written target status table and code-size tables), `Out/benchmark_sizes/`,
the stack logs in `Out/benchmark_raw/`, `Out/kat_summary.md`, `Out/kat_raw/`,
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

## Usage of SHA3

NGCCM4 uses SM3-based hashing and deterministic random generation by default. To build the schemes with the SHA3/SHAKE code path, pass `USE_KECCAK=1` to `make`, `build_schemes.py`, or `benchmark_schemes.py`.

When `USE_KECCAK=1` is enabled, the build system defines `USE_KECCAK` and adds the FIPS 202 implementation files from `common/`:

```text
common/fips202.c
common/fips202.h
common/keccakf1600.S
common/keccakf1600.h
common/randombytes.c
common/randombytes.h
```

This switches the guarded scheme code to the Keccak/SHA3/SHAKE implementation, including SHAKE-based XOF usage in sampling and SHA3/SHAKE-based hashing paths where the scheme code is guarded by `#ifdef USE_KECCAK`. For schemes that want to use SHA3, you need to add support for the SHA3 calls using `#ifdef USE_KECCAK` manually.

Examples:

```bash
make PLATFORM=nucleo-l4r5zi USE_KECCAK=1 crypto_kem_{SCHEME_NAME}_ref_test
make PLATFORM=mps2-an386 USE_KECCAK=1 crypto_kem_{SCHEME_NAME}_ref_test qemu-run -j1
python3 build_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME...} USE_KECCAK=1
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME...} --apps speed hashing USE_KECCAK=1
```

To use the default SM3 path explicitly, pass `USE_KECCAK=0`:

```bash
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi {SCHEME_NAME} --apps speed hashing USE_KECCAK=0
```

Notes:

- `USE_KECCAK` only accepts `0` or `1`; other values are rejected by `mk/config.mk`.
- Changing `USE_KECCAK` changes the build configuration, so the make system will clean stale `bin`, `elf`, and `obj` outputs automatically.
- `USE_SM3_ASM=1` controls the optimized SM3 assembly path. It is independent from `USE_KECCAK`.


## LICENSES
Different parts of **ngccm4** have different licenses. 
Each subdirectory containing implementations contains a LICENSE or COPYING file stating 
under what license that specific implementation is released. 
The files in common contain licensing information at the top of the file. 

All other code in this repository is licensed under [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0) and under the conditions of [CC0](https://creativecommons.org/publicdomain/zero/1.0/).

