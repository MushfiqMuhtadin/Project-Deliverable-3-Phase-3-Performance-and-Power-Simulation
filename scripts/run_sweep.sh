#!/usr/bin/env bash
# Phase 3 sweep: every workload at every OPP, with the full and the way-gated L2.
# Usage: GEM5=~/gem5/build/ARM/gem5.opt ./scripts/run_sweep.sh
set -euo pipefail
GEM5=${GEM5:-$HOME/gem5/build/ARM/gem5.opt}
cd "$(dirname "$0")/.."
mkdir -p results
for w in fir_q15 fir_q15_unroll4 matmul_i8 matmul_i8_tiled; do
  for opp in 0 1 2; do
    for ways in 8 4; do
      out=results/${w}_opp${opp}_l2w${ways}
      [ -f "$out/stats.txt" ] && continue
      "$GEM5" --outdir="$out" configs/iot_soc.py \
        --binary workloads/$w --opp $opp --l2-ways-on $ways > "$out.log" 2>&1 &
      # run up to $(nproc) simulations at once
      while [ "$(jobs -rp | wc -l)" -ge "$(nproc)" ]; do sleep 2; done
    done
  done
done
wait
python3 scripts/parse_stats.py results > results/summary.csv
echo "wrote results/summary.csv"
