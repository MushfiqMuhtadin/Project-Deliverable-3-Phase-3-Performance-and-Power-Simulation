"""Trace-driven performance and power model of the Phase 2 gem5 configuration.

This is NOT gem5. It reproduces the Phase 2 iot_soc.py system as closely as a
small Python model can, so Phase 3 experiments can be designed and predicted:

  * Caches: exact set-associative LRU simulation of every data access the
    kernels make (L1D 16 KiB 4-way, L2 128 KiB 8-way, 64 B lines, write-back,
    write-allocate, no prefetcher -- the gem5 classic Cache defaults).
  * Core: steady-state schedule of each inner loop on a 2-wide in-order
    pipeline (MinorCPU-like: in-order issue, <=1 memory op and <=1 multiply
    per cycle, load-to-use 3 cycles, integer multiply 3 cycles, 1 bubble per
    taken branch, 4-cycle penalty per loop-exit mispredict).
  * Miss cost: L2 hit = 20 core cycles (L2 is in the CPU clock domain, so it
    scales with DVFS); DRAM = 20 core cycles + 75 ns fixed (memory bus and
    LPDDR3 stay at 1 GHz). Misses are assumed not to overlap (conservative).
  * Power: the Phase 2 MathExprPowerModel equations, unchanged.
"""
import json
import math

LINE = 64
OPPS = [  # (label, Hz, V)
    ("OPP0", 1.0e9, 1.00),
    ("OPP1", 600e6, 0.85),
    ("OPP2", 300e6, 0.70),
]
P = dict(c_eff_core=0.25e-9, leak_core=0.020, e_l2_access=0.5e-9,
         leak_l2=0.008, retention_frac=0.25)
L2_HIT_CYC = 20
DRAM_NS = 75e-9


# ------------------------------------------------------------------ caches
class Cache:
    def __init__(self, size, assoc, nxt=None):
        self.assoc = assoc
        self.nsets = size // (LINE * assoc)
        self.sets = [[] for _ in range(self.nsets)]  # MRU first: [tag, dirty]
        self.nxt = nxt
        self.acc = self.miss = self.wb = 0

    def access(self, line, write=False):
        """Returns True on hit. line = address // LINE."""
        self.acc += 1
        s = self.sets[line % self.nsets]
        for i, e in enumerate(s):
            if e[0] == line:
                if i:
                    s.insert(0, s.pop(i))
                if write:
                    s[0][1] = True
                return True
        self.miss += 1
        if self.nxt is not None:
            self.nxt.access(line, False)  # fill
        s.insert(0, [line, write])
        if len(s) > self.assoc:
            v = s.pop()
            if v[1]:
                self.wb += 1
                if self.nxt is not None:
                    self.nxt.access(v[0], True)  # write-back into next level
        return False


class Hierarchy:
    def __init__(self, l2_size=128 * 1024, l2_assoc=8):
        self.l2 = Cache(l2_size, l2_assoc)
        self.l1 = Cache(16 * 1024, 4, self.l2)
        self.l2_from_demand = 0  # L2 accesses caused by L1 demand misses
        self.dram = 0

    def ld(self, addr):
        self._a(addr, False)

    def st(self, addr):
        self._a(addr, True)

    def _a(self, addr, w):
        line = addr // LINE
        m_before = self.l2.miss
        if not self.l1.access(line, w):
            self.l2_from_demand += 1
            if self.l2.miss > m_before:
                self.dram += 1


# ------------------------------------------------------------ pipeline
def schedule(body, iters=64, width=2, branch_bubble=1):
    """Steady-state cycles per iteration of a loop body on an in-order
    dual-issue pipeline. body = list of (dest, [srcs], kind)."""
    LAT = {"alu": 1, "ld": 3, "st": 1, "mul": 3, "br": 1}
    ready = {}
    cyc = 0
    starts = []
    for it in range(iters):
        slot = 0
        mem_used = mul_used = False
        starts.append(cyc)
        for dest, srcs, kind in body:
            t = max([cyc] + [ready.get(s, 0) for s in srcs])
            if t > cyc:
                cyc, slot, mem_used, mul_used = t, 0, False, False
            if slot == width or (kind in ("ld", "st") and mem_used) or (kind == "mul" and mul_used):
                cyc, slot, mem_used, mul_used = cyc + 1, 0, False, False
            slot += 1
            mem_used |= kind in ("ld", "st")
            mul_used |= kind == "mul"
            if dest:
                ready[dest] = cyc + LAT[kind]
            if kind == "br":
                cyc, slot, mem_used, mul_used = cyc + 1 + branch_bubble, 0, False, False
    per_iter = (starts[-1] - starts[iters // 2]) / (iters - 1 - iters // 2)
    return per_iter, len(body)


# ------------------------------------------------------------- kernels
A_BASE = 0x100000


def fir(unroll, l2=(128 * 1024, 8)):
    """32-tap Q15 FIR over 2048 samples. Baseline: one accumulator.
    Optimised: taps unrolled x4 into four independent accumulators."""
    N, T = 2048, 32
    x, h = A_BASE, A_BASE + (N + T) * 2
    y = h + 64 + 64  # padded
    mem = Hierarchy(*l2)
    for n in range(N):
        for k in range(T):
            mem.ld(x + (n + k) * 2)
            mem.ld(h + k * 2)
        mem.st(y + n * 2)
    if unroll == 1:
        body = [("xv", ["px"], "ld"), ("hv", ["ph"], "ld"),
                ("acc", ["xv", "hv", "acc"], "mul"),
                ("px", ["px"], "alu"), ("ph", ["ph"], "alu"),
                ("k", ["k"], "alu"), (None, ["k"], "br")]
        inner_iters = T
    else:
        body = []
        for u in range(4):
            body += [(f"x{u}", ["px"], "ld"), (f"h{u}", ["ph"], "ld"),
                     (f"a{u}", [f"x{u}", f"h{u}", f"a{u}"], "mul")]
        body += [("px", ["px"], "alu"), ("ph", ["ph"], "alu"),
                 ("k", ["k"], "alu"), (None, ["k"], "br")]
        inner_iters = T // 4
    cpi_iter, n_inst = schedule(body)
    outer_inst, outer_cyc = (8, 10) if unroll == 1 else (12, 14)  # setup, adds, sat, store
    insts = N * (inner_iters * n_inst + outer_inst)
    cycles = N * (inner_iters * cpi_iter + outer_cyc + 4)  # +4 loop-exit mispredict
    return dict(name="fir_q15" + ("" if unroll == 1 else "_unroll4"),
                insts=insts, core_cycles=cycles, mem=mem,
                ld=N * T * 2, st=N, bytes_ws=(N + T) * 2 + 64 + N * 2)


def matmul(opt, l2=(128 * 1024, 8)):
    """int8 128x128 matrix multiply, int32 result.
    Baseline: naive i-j-k (B walked down a column, 128 B stride).
    Optimised: B transposed once, j blocked by 32 so a 4 KiB block of B^T stays
    in L1D, inner k loop unrolled x4 with two accumulators."""
    n = 128
    A = A_BASE
    B = A + n * n
    C = B + n * n
    BT = C + n * n * 4
    mem = Hierarchy(*l2)
    insts = cycles = 0
    if not opt:
        for i in range(n):
            for j in range(n):
                for k in range(n):
                    mem.ld(A + i * n + k)
                    mem.ld(B + k * n + j)
                mem.st(C + (i * n + j) * 4)
        body = [("a", ["pa"], "ld"), ("b", ["pb"], "ld"),
                ("acc", ["a", "b", "acc"], "mul"),
                ("pa", ["pa"], "alu"), ("pb", ["pb"], "alu"),
                ("k", ["k"], "alu"), (None, ["k"], "br")]
        cpi_iter, n_inst = schedule(body)
        insts = n * n * (n * n_inst + 8)
        cycles = n * n * (n * cpi_iter + 10 + 4)
    else:
        for k in range(n):  # transpose pass
            for j in range(n):
                mem.ld(B + k * n + j)
                mem.st(BT + j * n + k)
        t_inst, t_cyc = schedule([("v", ["p"], "ld"), (None, ["q", "v"], "st"),
                                  ("p", ["p"], "alu"), ("q", ["q"], "alu"),
                                  ("j", ["j"], "alu"), (None, ["j"], "br")])[1], \
            schedule([("v", ["p"], "ld"), (None, ["q", "v"], "st"),
                      ("p", ["p"], "alu"), ("q", ["q"], "alu"),
                      ("j", ["j"], "alu"), (None, ["j"], "br")])[0]
        insts += n * n * t_inst
        cycles += n * n * t_cyc + n * 4
        JB = 32
        for jb in range(0, n, JB):
            for i in range(n):
                for j in range(jb, jb + JB):
                    for k in range(n):
                        mem.ld(A + i * n + k)
                        mem.ld(BT + j * n + k)
                    mem.st(C + (i * n + j) * 4)
        body = []
        for u in range(4):
            acc = "s0" if u % 2 == 0 else "s1"
            body += [(f"a{u}", ["pa"], "ld"), (f"b{u}", ["pb"], "ld"),
                     (acc, [f"a{u}", f"b{u}", acc], "mul")]
        body += [("pa", ["pa"], "alu"), ("pb", ["pb"], "alu"),
                 ("k", ["k"], "alu"), (None, ["k"], "br")]
        cpi_iter, n_inst = schedule(body)
        insts += n * n * ((n // 4) * n_inst + 10)
        cycles += n * n * ((n // 4) * cpi_iter + 12 + 4)
    return dict(name="matmul_i8" + ("_tiled" if opt else ""), insts=insts,
                core_cycles=cycles, mem=mem)


# --------------------------------------------------------------- power
def evaluate(k, opp, l2_leak_scale=1.0):
    label, f, V = opp
    mem = k["mem"]
    l2_hits = mem.l2_from_demand - mem.dram
    stall_cyc = l2_hits * L2_HIT_CYC + mem.dram * (L2_HIT_CYC + DRAM_NS * f)
    cycles = k["core_cycles"] + stall_cyc
    t = cycles / f
    ipc = k["insts"] / cycles
    p_core_dyn = P["c_eff_core"] * V * V * f * (0.4 + 0.3 * ipc)
    p_core_st = P["leak_core"] * V
    l2_acc = mem.l2.acc
    p_l2_dyn = P["e_l2_access"] * V * V * l2_acc / t
    p_l2_st = P["leak_l2"] * V * l2_leak_scale
    p_tot = p_core_dyn + p_core_st + p_l2_dyn + p_l2_st
    e = p_tot * t
    return dict(workload=k["name"], opp=label, f_mhz=f / 1e6, v=V,
                insts=k["insts"], cycles=round(cycles), time_ms=t * 1e3,
                ipc=ipc, cpi=1 / ipc,
                l1d_miss=mem.l1.miss / mem.l1.acc,
                l2_miss=mem.l2.miss / max(mem.l2.acc, 1),
                l1d_acc=mem.l1.acc, l1d_misses=mem.l1.miss, l2_acc=l2_acc,
                dram_lines=mem.dram, stall_frac=stall_cyc / cycles,
                p_core_mw=(p_core_dyn + p_core_st) * 1e3,
                p_l2_mw=(p_l2_dyn + p_l2_st) * 1e3,
                p_total_mw=p_tot * 1e3, energy_uj=e * 1e6,
                epi_pj=e / k["insts"] * 1e12,
                edp=e * t)


def idle_power(V, state, l2_scale=1.0):
    """Power while idle at voltage V in a Phase 2 power state (core + L2)."""
    if state == "CLK_GATED":
        return P["leak_core"] * V + P["leak_l2"] * V * l2_scale
    if state == "SRAM_RETENTION":
        return (P["leak_core"] + P["leak_l2"] * l2_scale) * V * P["retention_frac"]
    return 0.0


if __name__ == "__main__":
    import sys
    ks = [fir(1), fir(4), matmul(False), matmul(True)]
    rows = [evaluate(k, o) for k in ks for o in OPPS]
    for r in rows:
        print("{workload:18s} {opp} IPC={ipc:.3f} L1D={l1d_miss:.4f} L2miss={l2_miss:.3f} "
              "t={time_ms:.3f}ms P={p_total_mw:.1f}mW E={energy_uj:.1f}uJ EPI={epi_pj:.0f}pJ "
              "stall={stall_frac:.2f}".format(**r))
    half = [fir(4, (64 * 1024, 4)), matmul(False, (64 * 1024, 4)), matmul(True, (64 * 1024, 4))]
    hrows = [evaluate(k, o, l2_leak_scale=0.5) for k in half for o in OPPS]
    print("-- L2 64 KiB (4 of 8 ways gated)")
    for r in hrows:
        print("{workload:18s} {opp} IPC={ipc:.3f} L1D={l1d_miss:.4f} L2miss={l2_miss:.3f} "
              "t={time_ms:.3f}ms P={p_total_mw:.1f}mW E={energy_uj:.1f}uJ EPI={epi_pj:.0f}pJ".format(**r))
    json.dump({"base": rows, "l2half": hrows}, open("results.json", "w"), indent=1)
