# Phase 3 changes to configs/iot_soc.py (from the Phase 2 Appendix A script)

1. Add one command-line flag after the existing --opp flag:

    parser.add_argument("--l2-ways-on", type=int, default=8, choices=[4, 8])

2. Size the L2 from that flag (way gating: 4 of 8 ways off = 64 KiB, 4-way).
   Replace the L2Cache class body's size/assoc line with:

    size = "128KiB" if args.l2_ways_on == 8 else "64KiB"
    assoc = args.l2_ways_on

   and scale L2 leakage in l2_on_model / the idle models by args.l2_ways_on / 8.

3. Fix the L2 clock-gated power model. Clock gating stops switching, not
   leakage, so the CLK_GATED slot must keep full leakage:

    def l2_clk_gated_model():
        m = MathExprPowerModel()
        m.dyn = "0"
        m.st = "{k} * voltage".format(k=PARAMS["leak_l2"] * args.l2_ways_on / 8)
        return m

    l2.power_model = PowerModel(pm=[
        l2_on_model(l2.path()), l2_clk_gated_model(),
        l2_retention_model(), off_model()])
