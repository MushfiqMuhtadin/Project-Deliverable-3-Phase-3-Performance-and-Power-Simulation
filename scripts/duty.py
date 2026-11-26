"""Duty-cycled energy per 1 s frame, using model results (results.json)."""
import json
from model import idle_power, P
R = json.load(open("results.json"))
def get(tab, w, opp): return next(r for r in R[tab] if r["workload"] == w and r["opp"] == opp)
FRAME = 1.0          # s
N_FIR = 10           # one 2048-sample filter block every 100 ms
N_MM = 1             # one inference per second
E_TRANS = 1.0e-6     # J per retention sleep entry+exit (assumed)
T_WAKE = 20e-6       # s per wake (assumed), spent at clock-gated power
V_SLEEP = 0.70       # sleep at the lowest OPP voltage
def frame(fir_w, mm_w, opp, idle, tab="base", l2s=1.0):
    f, m = get(tab, fir_w, opp), get(tab, mm_w, opp)
    t_act = N_FIR * f["time_ms"] / 1e3 + N_MM * m["time_ms"] / 1e3
    e_act = (N_FIR * f["energy_uj"] + N_MM * m["energy_uj"]) / 1e6
    wakes = N_FIR + N_MM if idle == "SRAM_RETENTION" else 0
    t_idle = FRAME - t_act - wakes * T_WAKE
    v_idle = V_SLEEP if idle == "SRAM_RETENTION" else f["v"]
    e_idle = idle_power(v_idle, idle, l2s) * t_idle
    e_tr = wakes * (E_TRANS + T_WAKE * idle_power(V_SLEEP, "CLK_GATED", l2s))
    e = e_act + e_idle + e_tr
    return dict(t_act_ms=t_act * 1e3, e_act_mj=e_act * 1e3, e_idle_mj=(e_idle + e_tr) * 1e3,
                e_mj=e * 1e3, p_avg_mw=e / FRAME * 1e3,
                worst_latency_ms=max(f["time_ms"], m["time_ms"]))
rows = []
cases = [
 ("A Baseline (Phase 2 model)", "fir_q15", "matmul_i8", "OPP0", "CLK_GATED", "base", 1.0),
 ("B + loop unroll and tiling", "fir_q15_unroll4", "matmul_i8_tiled", "OPP0", "CLK_GATED", "base", 1.0),
 ("C + retention sleep (race to idle)", "fir_q15_unroll4", "matmul_i8_tiled", "OPP0", "SRAM_RETENTION", "base", 1.0),
 ("C1 retention sleep at OPP1", "fir_q15_unroll4", "matmul_i8_tiled", "OPP1", "SRAM_RETENTION", "base", 1.0),
 ("D + run at OPP2", "fir_q15_unroll4", "matmul_i8_tiled", "OPP2", "SRAM_RETENTION", "base", 1.0),
 ("E + L2 way gating (64 KiB)", "fir_q15_unroll4", "matmul_i8_tiled", "OPP2", "SRAM_RETENTION", "l2half", 0.5),
 ("X OPP2, clock gating only", "fir_q15_unroll4", "matmul_i8_tiled", "OPP2", "CLK_GATED", "base", 1.0),
]
for c in cases:
    r = frame(*c[1:]); r["case"] = c[0]; rows.append(r)
    print("{case:38s} act={t_act_ms:7.2f}ms Eact={e_act_mj:.3f}mJ Eidle={e_idle_mj:.3f}mJ "
          "E={e_mj:.3f}mJ Pavg={p_avg_mw:.2f}mW worst={worst_latency_ms:.2f}ms".format(**r))
json.dump(rows, open("duty.json", "w"), indent=1)
b = rows[0]["e_mj"]
for r in rows: print(r["case"], "saving %.1f%%" % (100 * (1 - r["e_mj"] / b)))
# break-even sleep time for retention vs clock gating at 0.7 V
d = idle_power(0.7, "CLK_GATED") - idle_power(0.7, "SRAM_RETENTION")
print("break-even us", E_TRANS / d * 1e6)
# compare core-only power with Phase 2 Table 3 at reported IPC
for r in R["base"]:
    if r["workload"] in ("fir_q15", "matmul_i8"):
        print(r["workload"], r["opp"], "core mW %.1f" % r["p_core_mw"], "core EPI pJ %.0f" % (r["p_core_mw"]*1e-3*r["time_ms"]*1e-3/r["insts"]*1e12), "IPC %.3f"%r["ipc"])
