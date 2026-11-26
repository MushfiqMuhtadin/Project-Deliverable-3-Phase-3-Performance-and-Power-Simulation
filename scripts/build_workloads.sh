#!/usr/bin/env bash
# Builds the four static AArch64 workloads. -O1 without auto-vectorisation keeps
# the instruction mix scalar, as the Phase 2 in-order core model assumes.
set -euo pipefail
cd "$(dirname "$0")/../workloads"
CC=aarch64-linux-gnu-gcc
FLAGS="-O1 -fno-tree-vectorize -static"
$CC $FLAGS -o fir_q15          fir_q15.c
$CC $FLAGS -DUNROLL4 -o fir_q15_unroll4 fir_q15.c
$CC $FLAGS -o matmul_i8        matmul_i8.c
$CC $FLAGS -DTILED   -o matmul_i8_tiled matmul_i8.c
file fir_q15 | grep -q "statically linked" && echo "workloads built"
