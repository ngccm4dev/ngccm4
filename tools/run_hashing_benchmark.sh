#!/usr/bin/env bash
# Run the hashing app on the board over every implementation with a complete speed benchmark,
# in the iteration groups chosen by tools/plan_hashing_run.py, and fold the results into the
# canonical Out/benchmark_hashing_<platform>.{csv,md} plus the coverage JSON.
#
#   tools/run_hashing_benchmark.sh [PLATFORM]          (default nucleo-l4r5zi)
#
# Each group is one benchmark_schemes.py invocation (NGCC_ITERATIONS is a make variable and changing it
# rebuilds everything); after each group tools/hashing_coverage.py scans the hashing ELFs before the
# next group's rebuild removes them. Driver logs: Out/benchmark_hashing_iter<N>.log.
set -u
cd "$(dirname "$0")/.."
PLATFORM="${1:-nucleo-l4r5zi}"
PLAN=Out/hashing_plan.json
COVERAGE=Out/benchmark_hashing_coverage.json
mkdir -p Out
python3 tools/plan_hashing_run.py --platform "$PLATFORM" --json "$PLAN" > Out/benchmark_hashing_plan.txt || exit 1
n=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['groups']))" "$PLAN")
started=$(date +%FT%T)
echo "[$started] hashing run on $PLATFORM: $n group(s)"
csvs=()
for i in $(seq 0 $((n - 1))); do
  cmd=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['groups'][int(sys.argv[2])]['command'])" "$PLAN" "$i")
  it=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['groups'][int(sys.argv[2])]['iterations'])" "$PLAN" "$i")
  log=Out/benchmark_hashing_iter${it}.log
  echo "[$(date +%FT%T)] ==> group NGCC_ITERATIONS=$it: $cmd"
  eval "$cmd" > "$log" 2>&1
  echo "[$(date +%FT%T)] driver exit $? (log: $log)"
  python3 tools/hashing_coverage.py --out "$COVERAGE"
  [ -f "Out/benchmark_hashing_iter${it}.csv" ] && csvs+=("Out/benchmark_hashing_iter${it}.csv")
done
if [ ${#csvs[@]} -gt 0 ]; then
  python3 tools/hashing_percentage.py "${csvs[@]}" \
    --merged-csv "Out/benchmark_hashing_${PLATFORM}.csv" \
    --csv "Out/benchmark_hashing_percent_${PLATFORM}.csv" \
    --md "Out/benchmark_hashing_${PLATFORM}.md" \
    --note "Measured $(date +%F) with \`benchmark_schemes.py PLATFORM=$PLATFORM --apps hashing\` (tools/run_hashing_benchmark.sh, groups from tools/plan_hashing_run.py)." \
    --note "Hash cycles are the DWT cycles spent in the HASHING_PROFILE-instrumented common hash functions (ICCS sm3hash/pseudohash/pseudoXOF and the SM3 DRNG); operation cycles are the whole operation measured in the same hashing-app run. Coverage per implementation: Out/benchmark_hashing_coverage.json."
fi
echo "[$(date +%FT%T)] done (started $started)"
