"""Collect Phase 3 metrics from every results/<run>/stats.txt into one CSV.

Usage: python3 scripts/parse_stats.py results > results/summary.csv
Columns match Table 2 and Table 5 of the Phase 3 report.
"""
import csv
import os
import re
import sys

STATS = {
    "simInsts": "simInsts",
    "simSeconds": "simSeconds",
    "ipc": "system.cpu.ipc",
    "l1d_miss": "system.cpu.dcache.overallMissRate::total",
    "l2_miss": "system.l2cache.overallMissRate::total",
    "core_dyn_w": "system.cpu.power_model.dynamicPower",
    "core_st_w": "system.cpu.power_model.staticPower",
    "l2_dyn_w": "system.l2cache.power_model.dynamicPower",
    "l2_st_w": "system.l2cache.power_model.staticPower",
}


def read_stats(path):
    """Values from the LAST stats dump in the file."""
    vals = {}
    with open(path) as f:
        for line in f:
            if line.startswith("---------- Begin"):
                vals = {}
            parts = line.split()
            if len(parts) >= 2:
                vals[parts[0]] = parts[1]
    return vals


def main(root):
    w = csv.writer(sys.stdout)
    w.writerow(["run", "workload", "opp", "l2_ways"] + list(STATS) +
               ["power_mw", "energy_uj", "epi_pj"])
    for run in sorted(os.listdir(root)):
        p = os.path.join(root, run, "stats.txt")
        if not os.path.isfile(p):
            continue
        m = re.match(r"(.+)_opp(\d)_l2w(\d)", run)
        s = read_stats(p)
        row = {k: float(s.get(v, "nan")) for k, v in STATS.items()}
        power = row["core_dyn_w"] + row["core_st_w"] + row["l2_dyn_w"] + row["l2_st_w"]
        energy = power * row["simSeconds"]
        w.writerow([run, m.group(1), m.group(2), m.group(3)] +
                   ["%.6g" % row[k] for k in STATS] +
                   ["%.2f" % (power * 1e3), "%.2f" % (energy * 1e6),
                    "%.1f" % (energy / row["simInsts"] * 1e12)])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results")
