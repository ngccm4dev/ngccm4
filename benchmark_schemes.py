#!/usr/bin/env python3
"""Run hardware benchmark apps and summarize implementation measurements.

Examples:
    python3 benchmark_schemes.py
    python3 benchmark_schemes.py all
    python3 benchmark_schemes.py PLATFORM=mps2-an386 DKEM-128 DKEM-256
    python3 benchmark_schemes.py PLATFORM=mps2-an386 ADKEX-128 --apps speed
    python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi DKEM-128 DKEM-256
    python3 benchmark_schemes.py PLATFORM=stm32f4discovery DKEM-128 --runs 3
    python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi DKEM-512 USE_SM3_ASM=1 -j8
    python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi --family kem,kex --apps speed
    python3 benchmark_schemes.py --family sign --skip Galas-512S,crypto_sign/%/ref   # on top of mk/skip.mk
    python3 benchmark_schemes.py --no-skip Tins128                                   # ignore the skip list

Supported platforms are mps2-an386, nucleo-l4r5zi, and stm32f4discovery.
The mps2-an386 runner uses make qemu-run. Hardware runners build each target,
open the serial port, flash the ELF with OpenOCD, capture output until '#', and
summarize the speed, stack, and hashing app metrics. The summary also includes
code size from the speed app ELF, measured with arm-none-eabi-size.
"""

from __future__ import annotations

import argparse
import csv
import os
import platform as host_platform
import re
import shlex
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import build_schemes


DEFAULT_APPS = ("speed", "stack", "hashing")
DONE_MARKER = "#"
DEFAULT_BAUD = 38400

OPENOCD_COMMANDS = {
    "nucleo-l4r5zi": ["openocd", "-f", "st_nucleo_l4r5.cfg", "-c"],
    "stm32f4discovery": [
        "openocd",
        "-f",
        "interface/stlink.cfg",
        "-f",
        "target/stm32f4x.cfg",
        "-c",
    ],
}

# Operations reported by the family drivers, in display order.
#   KEM: keypair/encaps/decaps   SIG: keypair/sign/verify
#   KEX: init_a/init_b/pass1..pass5/derive_a/derive_b
OPERATIONS = (
    "keypair", "encaps", "decaps", "sign", "verify",
    "init_a", "init_b", "pass1", "pass2", "pass3", "pass4", "pass5", "derive_a", "derive_b",
)

METRIC_PATTERNS = tuple(
    [(f"{op}_cycles", re.compile(rf"^{op} cycles:\s*$")) for op in OPERATIONS]
    + [(f"{op}_stack_bytes", re.compile(rf"^{op} stack usage:\s*$")) for op in OPERATIONS]
    + [(f"{op}_hash_cycles", re.compile(rf"^{op} hash cycles:\s*$")) for op in OPERATIONS]
)

METRIC_OPERATION_ORDER = {
    "keypair": 0,
    "encaps": 1,
    "decaps": 2,
    "sign": 1,
    "verify": 2,
    "init_a": 0,
    "init_b": 1,
    "pass1": 2,
    "pass2": 3,
    "pass3": 4,
    "pass4": 5,
    "pass5": 6,
    "derive_a": 7,
    "derive_b": 8,
}

TIERS = ("board", "qemu", "all")


@dataclass(frozen=True)
class Measurement:
    platform: str
    family: str
    scheme: str
    implementation: str
    app: str
    metric: str
    samples: tuple[int, ...]

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def average(self) -> float:
        return statistics.fmean(self.samples)

    @property
    def median(self) -> float:
        return float(statistics.median(self.samples))

    @property
    def minimum(self) -> int:
        return min(self.samples)

    @property
    def maximum(self) -> int:
        return max(self.samples)


@dataclass(frozen=True)
class CodeSize:
    platform: str
    family: str
    scheme: str
    implementation: str
    app: str
    text: int
    data: int
    bss: int

    @property
    def total(self) -> int:
        return self.text + self.data + self.bss


def default_serial_port() -> str:
    if host_platform.system() == "Darwin":
        return "/dev/tty.usbserial-0001"
    return "/dev/ttyACM0"


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, str, list[str], list[str]]:
    parser = argparse.ArgumentParser(
        description="Run speed/stack/hashing apps on supported boards and summarize measurements.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("schemes", nargs="*", help="Scheme names to benchmark. Use 'all' or omit schemes to benchmark all discovered schemes.")
    parser.add_argument(
        "--apps",
        nargs="+",
        default=list(DEFAULT_APPS),
        choices=DEFAULT_APPS,
        help="Benchmark apps to run.",
    )
    parser.add_argument("--runs", type=int, default=1, help="Executions per target.")
    parser.add_argument(
        "--tier",
        choices=TIERS,
        default=None,
        help=(
            "Only run implementations whose ngcc_tier.txt matches (imported NGCC schemes; "
            "hand-ported schemes count as 'board'). Default: 'board' on hardware platforms, 'all' on mps2-an386."
        ),
    )
    parser.add_argument(
        "--family",
        "--category",
        dest="families",
        action="append",
        metavar="FAMILY[,FAMILY...]",
        default=None,
        help=(
            "Only benchmark these scheme categories, comma-separated or repeated: kem, kex, sign "
            "(aliases: sig, crypto_kem, crypto_kex, crypto_sign, all). Default: all three."
        ),
    )
    build_schemes.add_skip_arguments(parser)
    parser.add_argument("-j", "--jobs", default="1", help="Forwarded make parallelism.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=1800.0,
        help="Seconds allowed per build/run step (slow hash-based signatures need many minutes on QEMU).",
    )
    parser.add_argument(
        "--flash-timeout",
        type=float,
        default=30.0,
        help="Seconds allowed for OpenOCD flashing.",
    )
    parser.add_argument("--serial-port", default=default_serial_port(), help="Serial device to capture board output.")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Serial baud rate.")
    parser.add_argument("--csv", default="benchmark_summary.csv", help="CSV summary output path.")
    parser.add_argument("--md", default="benchmark_summary.md", help="Markdown summary output path.")
    parser.add_argument("--raw-dir", default="Out/benchmark_raw", help="Directory for raw per-target output logs.")
    parser.add_argument(
        "--run-command",
        default="",
        help=(
            "Optional custom command template that prints app output to stdout. "
            "Placeholders: {platform}, {family}, {scheme}, {implementation}, {app}, {target}, {elf}, {bin}."
        ),
    )
    parser.add_argument("--no-build", action="store_true", help="Skip the make build step before running.")
    parser.add_argument(
        "--no-code-size",
        action="store_true",
        help="Do not build the speed app for the code-size table (saves a full rebuild per implementation when only the stack or hashing app is wanted).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failed target.")

    platform = ""
    make_vars: list[str] = []
    parser_args: list[str] = []

    for arg in argv:
        if "=" in arg and not arg.startswith("-"):
            key, value = arg.split("=", 1)
            if not key or not value:
                raise SystemExit(f"invalid make variable argument: {arg!r}")
            if key == "PLATFORM":
                platform = value
            else:
                make_vars.append(arg)
        else:
            parser_args.append(arg)

    args = parser.parse_args(parser_args)
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if not platform:
        platform = os.environ.get("PLATFORM", build_schemes.DEFAULT_TARGET_PLATFORM)

    return args, platform, make_vars, args.schemes


def make_jobs_arg(jobs: str | None) -> str | None:
    if not jobs:
        return None
    return jobs if jobs.startswith("-j") else f"-j{jobs}"


def target_name(impl: build_schemes.Implementation, app: str) -> str:
    return f"{impl.stem}_{app}"


def build_target_command(platform: str, target: str, make_vars: list[str], jobs: str | None) -> list[str]:
    command = ["make", f"PLATFORM={platform}", *make_vars, target]
    jobs_arg = make_jobs_arg(jobs)
    if jobs_arg:
        command.append(jobs_arg)
    return command


def qemu_run_command(platform: str, target: str, make_vars: list[str], jobs: str | None) -> list[str]:
    command = ["make", f"PLATFORM={platform}", *make_vars, target, "qemu-run"]
    jobs_arg = make_jobs_arg(jobs)
    if jobs_arg:
        command.append(jobs_arg)
    return command


def openocd_command(platform: str, elf: str) -> list[str]:
    return [*OPENOCD_COMMANDS[platform], f"program {elf} verify reset exit"]


def make_var_value(make_vars: list[str], key: str) -> str:
    for var in reversed(make_vars):
        var_key, _, value = var.partition("=")
        if var_key == key:
            return value
    return os.environ.get(key, "")


def size_tool(make_vars: list[str]) -> str:
    explicit_size = make_var_value(make_vars, "SIZE")
    if explicit_size:
        return explicit_size
    cross_prefix = make_var_value(make_vars, "CROSS_PREFIX") or "arm-none-eabi"
    return f"{cross_prefix}-size"


def size_command(make_vars: list[str], elf: str) -> list[str]:
    return [size_tool(make_vars), "-A", elf]


def format_run_command(template: str, platform: str, impl: build_schemes.Implementation, app: str) -> list[str]:
    target = target_name(impl, app)
    values = {
        "platform": platform,
        "family": impl.family,
        "scheme": impl.scheme,
        "implementation": impl.name,
        "app": app,
        "target": target,
        "elf": f"elf/{target}.elf",
        "bin": f"bin/{target}.bin",
    }
    return shlex.split(template.format(**values))


def parse_metrics(output: str) -> dict[str, list[int]]:
    lines = [line.strip() for line in output.replace("\r", "\n").splitlines()]
    metrics: dict[str, list[int]] = {name: [] for name, _ in METRIC_PATTERNS}

    for index, line in enumerate(lines[:-1]):
        for name, pattern in METRIC_PATTERNS:
            if not pattern.match(line):
                continue
            value_line = lines[index + 1]
            if re.fullmatch(r"[0-9]+", value_line):
                metrics[name].append(int(value_line))
            break

    return {name: values for name, values in metrics.items() if values}


def parse_code_size(output: str) -> dict[str, int]:
    sections: dict[str, int] = {}
    for line in output.splitlines():
        match = re.match(r"^(\.\S+)\s+([0-9]+)\s+", line.strip())
        if not match:
            continue
        section, size = match.groups()
        if section in {".text", ".data", ".bss"}:
            sections[section] = int(size)

    missing = [section for section in (".text", ".data", ".bss") if section not in sections]
    if missing:
        raise ValueError("missing section(s): " + ", ".join(missing))

    return sections


def write_raw_log(raw_dir: Path, target: str, run_index: int, output: str) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_path = raw_dir / f"{target}.run{run_index}.txt"
    log_path.write_text(output, encoding="utf-8", errors="replace")


def run_command(command: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return result.returncode, result.stdout


def run_board_capture(
    platform: str,
    elf: str,
    serial_port: str,
    baud: int,
    cwd: Path,
    flash_timeout: float,
    capture_timeout: float,
) -> tuple[int, str]:
    try:
        import serial
    except ImportError:
        return 127, "error: pyserial is required for board capture; install python3-serial or pyserial\n"

    command = openocd_command(platform, elf)
    output_parts: list[str] = ["+ " + " ".join(command) + "\n"]

    try:
        with serial.Serial(serial_port, baud, timeout=0.05) as device:
            try:
                device.reset_input_buffer()
            except Exception:
                pass

            flash = subprocess.run(
                command,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=flash_timeout,
            )
            output_parts.append(flash.stdout)
            if flash.returncode != 0:
                return flash.returncode, "".join(output_parts)

            # The ST-LINK VCP buffers what the target printed while no host had
            # the port open and delivers it right after the next open, racing
            # with reset_input_buffer() above. With the pre-fix firmware that
            # is the tail of the HardFault dump printed after main() returned,
            # whose '#' would end this capture before any real output arrives.
            # Drain until 0.5 s of silence (3 s cap): hal_setup() keeps the
            # target silent for several seconds after reset, so nothing is lost.
            drain_deadline = time.monotonic() + 3.0
            quiet_since = time.monotonic()
            stale = bytearray()
            while time.monotonic() < drain_deadline:
                data = device.read(4096)
                if data:
                    stale.extend(data)
                    quiet_since = time.monotonic()
                elif time.monotonic() - quiet_since >= 0.5:
                    break
            if stale:
                output_parts.append(
                    f"(discarded {len(stale)} stale bytes buffered by the ST-LINK before this run)\n"
                )

            deadline = time.monotonic() + capture_timeout
            captured = bytearray()
            while time.monotonic() < deadline:
                data = device.read(1)
                if not data:
                    continue
                captured.extend(data)
                if data == DONE_MARKER.encode("ascii"):
                    break

            output_parts.append(captured.decode("utf-8", errors="replace"))
            if DONE_MARKER.encode("ascii") not in captured:
                output_parts.append(f"\nwarning: timed out waiting for {DONE_MARKER!r}\n")
                return 124, "".join(output_parts)
            return 0, "".join(output_parts)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        return 124, "".join(output_parts) + output + f"\nerror: OpenOCD timed out after {flash_timeout:.1f}s\n"
    except Exception as exc:
        return 1, "".join(output_parts) + f"error: board capture failed: {exc}\n"


def format_integer(value: int) -> str:
    return f"{value:,}"


def format_rounded(value: float) -> str:
    return f"{value:,.0f}"


def format_percentage(value: float) -> str:
    return f"{value:,.2f}%"


def write_csv(path: Path, measurements: list[Measurement]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "platform",
                "family",
                "scheme",
                "implementation",
                "app",
                "metric",
                "count",
                "average",
                "median",
                "min",
                "max",
            ]
        )
        for measurement in measurements:
            writer.writerow(
                [
                    measurement.platform,
                    measurement.family,
                    measurement.scheme,
                    measurement.implementation,
                    measurement.app,
                    measurement.metric,
                    format_integer(measurement.count),
                    format_rounded(measurement.average),
                    format_rounded(measurement.median),
                    format_integer(measurement.minimum),
                    format_integer(measurement.maximum),
                ]
            )


def metric_operation(metric: str) -> str:
    for suffix in ("_hash_cycles", "_stack_bytes", "_cycles"):
        if metric.endswith(suffix):
            return metric[: -len(suffix)]
    return metric


def metric_display_name(metric: str) -> str:
    return metric_operation(metric)


def metric_order(metric: str) -> int:
    operation = metric_operation(metric)
    return METRIC_OPERATION_ORDER.get(operation, len(METRIC_OPERATION_ORDER))


def ordered_apps(measurements: list[Measurement]) -> list[str]:
    app_index = {app: index for index, app in enumerate(DEFAULT_APPS)}
    return sorted(
        {measurement.app for measurement in measurements},
        key=lambda app: (app_index.get(app, len(app_index)), app),
    )


def measurement_belongs_in_app_table(measurement: Measurement) -> bool:
    if measurement.app == "speed":
        return measurement.metric.endswith("_cycles") and "_hash_" not in measurement.metric
    if measurement.app == "stack":
        return measurement.metric.endswith("_stack_bytes")
    if measurement.app == "hashing":
        return measurement.metric.endswith("_hash_cycles")
    return True


def hashing_percentage_rows(measurements: list[Measurement]) -> list[tuple[str, str, str, int, float]]:
    by_key = {
        (measurement.scheme, measurement.implementation, measurement.metric): measurement
        for measurement in measurements
        if measurement.app == "hashing"
    }
    rows: list[tuple[str, str, str, int, float]] = []

    for scheme, implementation, metric in sorted(by_key):
        if not metric.endswith("_hash_cycles"):
            continue
        operation = metric_display_name(metric)
        total_metric = f"{operation}_cycles"
        total = by_key.get((scheme, implementation, total_metric))
        hashed = by_key[(scheme, implementation, metric)]
        if total is None or total.average == 0:
            continue
        count = min(total.count, hashed.count)
        percentage = hashed.average / total.average * 100.0
        rows.append((scheme, implementation, operation, count, percentage))

    rows.sort(key=lambda row: (row[0], row[1], metric_order(row[2])))
    return rows


def write_code_size_table(lines: list[str], code_sizes: list[CodeSize]) -> None:
    if not code_sizes:
        return

    code_sizes.sort(key=lambda size: (size.scheme, size.implementation))
    lines.append("**code size (speed)**")
    lines.append("")
    lines.append("| scheme | implementation | .text | .data | .bss | total |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
    for size in code_sizes:
        lines.append(
            "| "
            + " | ".join(
                [
                    size.scheme,
                    size.implementation,
                    format_integer(size.text),
                    format_integer(size.data),
                    format_integer(size.bss),
                    format_integer(size.total),
                ]
            )
            + " |"
        )
    lines.append("")


def classify_failure(output: str, code: int) -> str:
    text = output.lower()
    if ("region" in text and "overflowed" in text) or "cannot move location counter" in text or "will not fit in region" in text:
        return "link-overflow"
    if "error:" in text and ("make:" in text or "collect2" in text):
        return "build-failed"
    if "alloc_failed" in text or "alloc failed" in text:
        return "alloc-failed"
    if "error keys" in text:
        return "wrong-result"
    if "reprogrammed during the capture" in text:
        return "board-interrupted"
    if "failed" in text:
        return "run-failed"
    return f"exit-{code}"


def write_status_table(lines: list[str], statuses: dict[str, str]) -> None:
    if not statuses:
        return
    lines.append("## target status")
    lines.append("")
    lines.append("| target | status |")
    lines.append("| --- | --- |")
    for target in sorted(statuses):
        lines.append(f"| {target} | {statuses[target]} |")
    lines.append("")


def write_markdown(path: Path, measurements: list[Measurement], code_sizes: list[CodeSize], statuses: dict[str, str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    failed = {target: status for target, status in (statuses or {}).items() if status != "ok"}
    write_status_table(lines, failed)
    families = sorted({measurement.family for measurement in measurements} | {size.family for size in code_sizes})

    for family in families:
        family_measurements = [measurement for measurement in measurements if measurement.family == family]
        family_code_sizes = [size for size in code_sizes if size.family == family]
        lines.append(f"## {family}")

        for app in ordered_apps(family_measurements):
            if app == "hashing":
                hash_rows = hashing_percentage_rows(family_measurements)
                if not hash_rows:
                    continue

                lines.append(f"**{app}**")
                lines.append("")
                lines.append("| scheme | implementation | metric | count | percentage |")
                lines.append("| --- | --- | --- | ---: | ---: |")
                for scheme, implementation, operation, count, percentage in hash_rows:
                    lines.append(
                        "| "
                        + " | ".join(
                            [
                                scheme,
                                implementation,
                                operation,
                                format_integer(count),
                                format_percentage(percentage),
                            ]
                        )
                        + " |"
                    )
                lines.append("")
                continue

            app_measurements = [
                measurement
                for measurement in family_measurements
                if measurement.app == app and measurement_belongs_in_app_table(measurement)
            ]
            if not app_measurements:
                continue

            app_measurements.sort(
                key=lambda measurement: (
                    measurement.scheme,
                    measurement.implementation,
                    metric_order(measurement.metric),
                    measurement.metric,
                )
            )

            lines.append(f"**{app}**")
            lines.append("")
            if app == "stack":
                lines.append("| scheme | implementation | metric | count | average |")
                lines.append("| --- | --- | --- | ---: | ---: |")
            else:
                lines.append("| scheme | implementation | metric | count | average | median | min | max |")
                lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")

            for measurement in app_measurements:
                row = [
                    measurement.scheme,
                    measurement.implementation,
                    metric_display_name(measurement.metric),
                    format_integer(measurement.count),
                    format_rounded(measurement.average),
                ]
                if app != "stack":
                    row.extend(
                        [
                            format_rounded(measurement.median),
                            format_integer(measurement.minimum),
                            format_integer(measurement.maximum),
                        ]
                    )
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")

        write_code_size_table(lines, family_code_sizes)
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def validate_platform(platform: str) -> bool:
    return platform in build_schemes.SUPPORTED_TARGET_PLATFORMS


def collect_code_size(
    root: Path,
    platform: str,
    impl: build_schemes.Implementation,
    make_vars: list[str],
    jobs: str | None,
    timeout: float,
    no_build: bool,
    dry_run: bool,
    built_targets: set[str],
) -> tuple[CodeSize | None, bool]:
    target = target_name(impl, "speed")
    elf = f"elf/{target}.elf"

    print(f"\n==> {target} code size")

    if not no_build and target not in built_targets:
        build_command = build_target_command(platform, target, make_vars, jobs)
        print("+ " + " ".join(build_command))
        if not dry_run:
            try:
                code, output = run_command(build_command, root, timeout)
            except FileNotFoundError as exc:
                print(f"build command failed: {exc}", file=sys.stderr)
                return None, True
            except subprocess.TimeoutExpired as exc:
                output = exc.stdout or ""
                print(output, file=sys.stderr)
                print(f"build timeout after {timeout:.1f}s: {target}", file=sys.stderr)
                return None, True
            if code != 0:
                print(output, file=sys.stderr)
                return None, True
            built_targets.add(target)

    command = size_command(make_vars, elf)
    print("+ " + " ".join(command))
    if dry_run:
        return None, False

    try:
        code, output = run_command(command, root, timeout)
    except FileNotFoundError as exc:
        print(f"size command failed: {exc}", file=sys.stderr)
        return None, True
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        print(output, file=sys.stderr)
        print(f"size timeout after {timeout:.1f}s: {target}", file=sys.stderr)
        return None, True

    if code != 0:
        print(output, file=sys.stderr)
        return None, True

    try:
        sections = parse_code_size(output)
    except ValueError as exc:
        print(f"could not parse code size for {target}: {exc}", file=sys.stderr)
        print(output, file=sys.stderr)
        return None, True

    return (
        CodeSize(
            platform=platform,
            family=impl.family,
            scheme=impl.scheme,
            implementation=impl.name,
            app="speed",
            text=sections[".text"],
            data=sections[".data"],
            bss=sections[".bss"],
        ),
        False,
    )


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent
    args, platform, make_vars, schemes = parse_args(argv)

    if not validate_platform(platform):
        print(
            f"error: unsupported PLATFORM={platform!r}; supported: "
            f"{' '.join(build_schemes.SUPPORTED_TARGET_PLATFORMS)}",
            file=sys.stderr,
        )
        return 2

    requested_schemes = build_schemes.normalize_requested_schemes(schemes)
    implementations = build_schemes.discover_implementations(root, requested_schemes)
    tier = args.tier or ("all" if platform == "mps2-an386" else "board")
    implementations = build_schemes.filter_by_tier(implementations, tier)
    families = build_schemes.normalize_families(args.families)
    implementations = build_schemes.filter_by_family(implementations, families)
    implementations, skipped = build_schemes.apply_skip_list(root, implementations, args, make_vars)
    build_schemes.report_skipped(skipped)
    if not implementations:
        print("error: no matching implementations found", file=sys.stderr)
        return 1
    print(f"Selected {len(implementations)} implementation(s) from {', '.join(sorted(families))} (tier: {tier})")

    statuses: dict[str, str] = {}
    measurements_by_key: dict[tuple[str, str, str, str, str, str], list[int]] = {}
    code_sizes: list[CodeSize] = []
    raw_dir = root / args.raw_dir
    built_targets: set[str] = set()
    failures = 0

    for impl in implementations:
        family_apps = set(build_schemes.family_apps(root, impl.family))
        selected_apps = [app for app in args.apps if app in family_apps]
        if not selected_apps:
            print(f"skip: {impl.family}/{impl.scheme}/{impl.name}: no selected apps found")
            continue

        for app in selected_apps:
            target = target_name(impl, app)
            elf = f"elf/{target}.elf"
            for run_index in range(1, args.runs + 1):
                print(f"\n==> {target} run {run_index}/{args.runs}")

                if args.run_command:
                    if not args.no_build:
                        build_command = build_target_command(platform, target, make_vars, args.jobs)
                        print("+ " + " ".join(build_command))
                        if not args.dry_run:
                            try:
                                code, output = run_command(build_command, root, args.timeout)
                            except subprocess.TimeoutExpired as exc:
                                output = exc.stdout or ""
                                print(output, file=sys.stderr)
                                print(f"build timeout after {args.timeout:.1f}s: {target}", file=sys.stderr)
                                failures += 1
                                if args.fail_fast:
                                    return 1
                                continue
                            if code != 0:
                                print(output, file=sys.stderr)
                                failures += 1
                                if args.fail_fast:
                                    return 1
                                continue
                            built_targets.add(target)
                    command = format_run_command(args.run_command, platform, impl, app)
                    print("+ " + " ".join(command))
                elif platform == "mps2-an386":
                    command = qemu_run_command(platform, target, make_vars, args.jobs)
                    print("+ " + " ".join(command))
                else:
                    if not args.no_build:
                        build_command = build_target_command(platform, target, make_vars, args.jobs)
                        print("+ " + " ".join(build_command))
                        if not args.dry_run:
                            try:
                                code, output = run_command(build_command, root, args.timeout)
                            except subprocess.TimeoutExpired as exc:
                                output = exc.stdout or ""
                                print(output, file=sys.stderr)
                                print(f"build timeout after {args.timeout:.1f}s: {target}", file=sys.stderr)
                                failures += 1
                                if args.fail_fast:
                                    return 1
                                continue
                            if code != 0:
                                print(output, file=sys.stderr)
                                failures += 1
                                if args.fail_fast:
                                    return 1
                                continue
                            built_targets.add(target)
                    command = openocd_command(platform, elf)
                    print("+ " + " ".join(command))
                    print(f"+ capture serial {args.serial_port} @ {args.baud} until {DONE_MARKER!r}")

                if args.dry_run:
                    continue

                if args.run_command or platform == "mps2-an386":
                    try:
                        code, output = run_command(command, root, args.timeout)
                    except subprocess.TimeoutExpired as exc:
                        output = exc.stdout or ""
                        print(f"timeout after {args.timeout:.1f}s: {target}", file=sys.stderr)
                        write_raw_log(raw_dir, target, run_index, output)
                        statuses[target] = "timeout"
                        failures += 1
                        if args.fail_fast:
                            return 1
                        continue
                else:
                    code, output = run_board_capture(
                        platform=platform,
                        elf=elf,
                        serial_port=args.serial_port,
                        baud=args.baud,
                        cwd=root,
                        flash_timeout=args.flash_timeout,
                        capture_timeout=args.timeout,
                    )
                    # The ST-LINK virtual COM port occasionally drops out right after flashing
                    # ("device reports readiness to read but returned no data"); that is a host-side
                    # glitch, not a result, so flash and capture once more before giving up.
                    for attempt in range(2):
                        if code == 0 or "returned no data" not in output:
                            break
                        print(f"serial port dropped out, retrying ({attempt + 1}/2): {target}", file=sys.stderr)
                        time.sleep(3)
                        code, output = run_board_capture(
                            platform=platform,
                            elf=elf,
                            serial_port=args.serial_port,
                            baud=args.baud,
                            cwd=root,
                            flash_timeout=args.flash_timeout,
                            capture_timeout=args.timeout,
                        )

                # Every app prints one start banner after hal_setup(); a second one means the board was
                # reset or reprogrammed by someone else during the capture, so the output is not ours.
                if code == 0 and output.count("==========================") > 1:
                    output += "\nerror: the board was reset or reprogrammed during the capture (second start banner seen); measurements discarded\n"
                    code = 1

                write_raw_log(raw_dir, target, run_index, output)

                if code != 0:
                    print(f"command failed with exit {code}: {target}", file=sys.stderr)
                    statuses[target] = classify_failure(output, code)
                    failures += 1
                    if args.fail_fast:
                        return 1
                    continue
                statuses[target] = "ok" if DONE_MARKER in output else "no-done-marker"
                if platform == "mps2-an386":
                    built_targets.add(target)

                if DONE_MARKER not in output:
                    print(f"warning: done marker '#' not seen in {target}", file=sys.stderr)

                parsed = parse_metrics(output)
                if not parsed:
                    print(f"warning: no metrics parsed from {target}", file=sys.stderr)

                for metric, values in parsed.items():
                    key = (platform, impl.family, impl.scheme, impl.name, app, metric)
                    measurements_by_key.setdefault(key, []).extend(values)

    for impl in ([] if args.no_code_size else implementations):
        family_apps = set(build_schemes.family_apps(root, impl.family))
        if "speed" not in family_apps:
            continue

        size, failed = collect_code_size(
            root=root,
            platform=platform,
            impl=impl,
            make_vars=make_vars,
            jobs=args.jobs,
            timeout=args.timeout,
            no_build=args.no_build,
            dry_run=args.dry_run,
            built_targets=built_targets,
        )
        if failed:
            failures += 1
            if args.fail_fast:
                return 1
        if size is not None:
            code_sizes.append(size)

    measurements = [
        Measurement(
            platform=key[0],
            family=key[1],
            scheme=key[2],
            implementation=key[3],
            app=key[4],
            metric=key[5],
            samples=tuple(values),
        )
        for key, values in sorted(
            measurements_by_key.items(),
            key=lambda item: (
                item[0][0],
                item[0][1],
                item[0][2],
                item[0][3],
                item[0][4],
                metric_order(item[0][5]),
                item[0][5],
            ),
        )
        if values
    ]

    if args.dry_run:
        return 0

    if not measurements and not code_sizes:
        print("error: no measurements or code sizes collected", file=sys.stderr)
        return 1

    csv_path = root / args.csv
    md_path = root / args.md
    write_csv(csv_path, measurements)
    write_markdown(md_path, measurements, code_sizes, statuses)

    print(f"\nWrote CSV summary: {csv_path}")
    print(f"Wrote Markdown summary: {md_path}")
    print(f"Raw logs: {raw_dir}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
