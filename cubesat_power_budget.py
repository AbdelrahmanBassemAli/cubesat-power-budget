#!/usr/bin/env python3
"""
CubeSat orbit-average power budget (first-order model).

Given an orbit, solar-cell layout and a list of loads, it estimates:
  - orbital period, eclipse and sunlight duration (beta-angle aware)
  - solar power generation (tumbling or sun-pointing)
  - energy balance per orbit and power margin
  - required battery capacity for a chosen depth of discharge
  - how all of this changes with beta angle (worst case = beta 0)

All default numbers are ASSUMPTIONS for a generic 1U CubeSat. Replace them
with your own design values (see config.example.json) before quoting results.

Usage:
  python cubesat_power_budget.py                      # defaults
  python cubesat_power_budget.py --alt 550 --beta 20
  python cubesat_power_budget.py --attitude sun_pointing --deployed-area 0.02
  python cubesat_power_budget.py --config my_cubesat.json
  python cubesat_power_budget.py --animate            # also writes results/power_animation.gif
  python cubesat_power_budget.py --animate --orbits 5 --battery-wh 3
  python cubesat_power_budget.py --selftest
"""
import argparse
import json
import math
import os
from dataclasses import asdict, dataclass, field

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

MU = 398600.4418   # Earth gravitational parameter, km^3/s^2
RE = 6378.137      # Earth equatorial radius, km
S0 = 1361.0        # solar constant, W/m^2


@dataclass
class Load:
    name: str
    power_w: float   # power while active
    duty: float      # fraction of the orbit it is active (0..1)


def default_loads():
    return [
        Load("OBC", 0.40, 1.00),
        Load("EPS housekeeping", 0.15, 1.00),
        Load("Comms RX / beacon", 0.30, 1.00),
        Load("Comms TX", 2.00, 0.05),
        Load("Payload / sensors", 0.50, 0.50),
        Load("ADCS (magnetorquers)", 0.30, 0.30),
    ]


@dataclass
class Config:
    altitude_km: float = 500.0
    beta_deg: float = 0.0              # angle between orbit plane and sun vector
    face_area_m2: float = 0.01         # 1U face = 0.1 m x 0.1 m
    covered_faces: int = 4             # faces with solar cells (tumbling model)
    attitude: str = "tumbling"         # "tumbling" or "sun_pointing"
    deployed_area_m2: float = 0.0      # extra panel area, used when sun_pointing
    cell_efficiency: float = 0.28      # triple-junction cell, beginning of life
    packing_factor: float = 0.70       # fraction of face area covered by cells
    degradation: float = 0.80          # temperature, wiring, EOL losses combined
    eps_efficiency: float = 0.85       # MPPT / regulator chain
    battery_efficiency: float = 0.92   # per direction (charge, discharge)
    depth_of_discharge: float = 0.30   # chosen DoD for cycle life in LEO
    battery_capacity_wh: float = 0.0   # 0 = auto-size from DoD (used by the animation)
    loads: list = field(default_factory=default_loads)


# ---------------- orbit ----------------
def orbit_period_s(alt_km):
    a = RE + alt_km
    return 2 * math.pi * math.sqrt(a ** 3 / MU)


def eclipse_time_s(alt_km, beta_deg):
    """Eclipse duration for a circular orbit with cylindrical Earth shadow."""
    a = RE + alt_km
    beta = math.radians(beta_deg)
    if abs(beta) >= math.asin(RE / a):
        return 0.0
    x = math.sqrt(alt_km ** 2 + 2 * RE * alt_km) / (a * math.cos(beta))
    return orbit_period_s(alt_km) / math.pi * math.acos(min(1.0, x))


# ---------------- power ----------------
def sunlit_generation_w(c: Config):
    """Orbit-average power while in sunlight, before the EPS chain."""
    if c.attitude == "tumbling":
        # mean projected area of a convex face is face_area / 4
        area = c.covered_faces * c.face_area_m2 / 4.0
    elif c.attitude == "sun_pointing":
        area = c.face_area_m2 + c.deployed_area_m2
    else:
        raise ValueError("attitude must be 'tumbling' or 'sun_pointing'")
    return S0 * c.cell_efficiency * c.packing_factor * c.degradation * area


def average_load_w(c: Config):
    loads = [Load(**l) if isinstance(l, dict) else l for l in c.loads]
    return sum(l.power_w * l.duty for l in loads)


def analyze(c: Config):
    T = orbit_period_s(c.altitude_km)
    t_ecl = eclipse_time_s(c.altitude_km, c.beta_deg)
    t_sun = T - t_ecl
    p_sun = sunlit_generation_w(c)
    p_load = average_load_w(c)
    eta = c.battery_efficiency

    e_gen_wh = p_sun * c.eps_efficiency * t_sun / 3600
    e_load_sun_wh = p_load * t_sun / 3600
    e_load_ecl_wh = p_load * t_ecl / 3600
    # eclipse energy passes through the battery twice (charge + discharge)
    e_need_wh = e_load_sun_wh + e_load_ecl_wh / (eta ** 2)
    margin = e_gen_wh / e_need_wh - 1 if e_need_wh > 0 else float("inf")
    batt_wh = e_load_ecl_wh / (c.depth_of_discharge * eta)
    orbits_per_year = 365.25 * 86400 / T

    return {
        "period_min": T / 60,
        "eclipse_min": t_ecl / 60,
        "sunlight_min": t_sun / 60,
        "sunlit_generation_w": p_sun,
        "orbit_avg_generation_w": p_sun * c.eps_efficiency * t_sun / T,
        "orbit_avg_load_w": p_load,
        "energy_generated_wh_per_orbit": e_gen_wh,
        "energy_needed_wh_per_orbit": e_need_wh,
        "power_margin_pct": margin * 100,
        "battery_capacity_wh_required": batt_wh,
        "battery_cycles_per_year": orbits_per_year if t_ecl > 0 else 0,
        "power_positive": margin >= 0,
    }


def beta_sweep(c: Config, step=1):
    rows = []
    for b in range(0, 91, step):
        cc = Config(**{**asdict(c), "beta_deg": float(b)})
        r = analyze(cc)
        r["beta_deg"] = b
        rows.append(r)
    return rows


# ---------------- reporting ----------------
def print_report(c, r):
    print(f"\nCubeSat power budget: {c.altitude_km:.0f} km, beta {c.beta_deg:.0f} deg, {c.attitude}")
    print("-" * 62)
    print(f"Orbit period            : {r['period_min']:.1f} min")
    print(f"Eclipse / sunlight      : {r['eclipse_min']:.1f} / {r['sunlight_min']:.1f} min")
    print(f"Sunlit generation       : {r['sunlit_generation_w']:.2f} W (before EPS losses)")
    print(f"Orbit-avg generation    : {r['orbit_avg_generation_w']:.2f} W (after EPS losses)")
    print(f"Orbit-avg load          : {r['orbit_avg_load_w']:.2f} W")
    print(f"Energy gen / needed     : {r['energy_generated_wh_per_orbit']:.2f} / {r['energy_needed_wh_per_orbit']:.2f} Wh per orbit")
    print(f"Power margin            : {r['power_margin_pct']:+.1f} %  ({'OK' if r['power_positive'] else 'NEGATIVE: battery drains over time'})")
    print(f"Battery needed          : {r['battery_capacity_wh_required']:.2f} Wh at {c.depth_of_discharge*100:.0f}% DoD")
    print(f"Battery cycles per year : {r['battery_cycles_per_year']:.0f}")
    loads = [Load(**l) if isinstance(l, dict) else l for l in c.loads]
    print("\nLoads:")
    for l in loads:
        print(f"  {l.name:<24} {l.power_w:5.2f} W x {l.duty:4.2f} duty = {l.power_w*l.duty:5.2f} W")


def make_plots(c, rows, outdir):
    os.makedirs(outdir, exist_ok=True)
    b = [r["beta_deg"] for r in rows]
    fig, ax = plt.subplots(1, 3, figsize=(14, 3.8))
    ax[0].plot(b, [r["eclipse_min"] for r in rows])
    ax[0].set(xlabel="Beta angle (deg)", ylabel="Eclipse (min)", title="Eclipse duration")
    ax[1].plot(b, [r["power_margin_pct"] for r in rows])
    ax[1].axhline(0, color="red", lw=1, ls="--")
    ax[1].set(xlabel="Beta angle (deg)", ylabel="Margin (%)", title="Energy margin per orbit")
    ax[2].plot(b, [r["battery_capacity_wh_required"] for r in rows])
    ax[2].set(xlabel="Beta angle (deg)", ylabel="Wh", title=f"Battery for {c.depth_of_discharge*100:.0f}% DoD")
    for a in ax:
        a.grid(alpha=0.3)
    fig.suptitle(f"{c.altitude_km:.0f} km, {c.attitude}, {c.covered_faces} cell faces")
    fig.tight_layout()
    path = os.path.join(outdir, "power_budget_beta_sweep.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# ---------------- time-domain simulation + animation ----------------
def simulate(c: Config, orbits=3, dt=10.0):
    """Step through several orbits and track the battery state of charge."""
    T = orbit_period_s(c.altitude_km)
    a = RE + c.altitude_km
    cb = math.cos(math.radians(c.beta_deg))
    p_gen_on = sunlit_generation_w(c) * c.eps_efficiency
    p_load = average_load_w(c)
    cap = c.battery_capacity_wh or max(analyze(c)["battery_capacity_wh_required"], 1.0)
    eta = c.battery_efficiency

    n = int(orbits * T / dt)
    t = np.arange(n) * dt
    theta = 2 * np.pi * t / T                      # 0 = sub-solar point
    cos_t = np.cos(theta)
    # in the shadow cylinder: on the night side and closer to the Sun line than Re
    in_ecl = (cos_t < 0) & (a * a * (1 - (cos_t * cb) ** 2) < RE * RE)
    gen = np.where(in_ecl, 0.0, p_gen_on)

    soc = np.empty(n)
    s = cap                                         # start with a full battery
    for i in range(n):
        net = gen[i] - p_load
        s += (net * eta if net >= 0 else net / eta) * dt / 3600
        s = min(max(s, 0.0), cap)
        soc[i] = s
    return {"t": t, "theta": theta, "in_ecl": in_ecl, "gen": gen, "load": p_load,
            "soc": soc, "cap": cap, "T": T, "a": a}


def animate(c: Config, path, orbits=3, dt=10.0, fps=20, frames=150):
    from matplotlib.animation import FuncAnimation, PillowWriter

    sim = simulate(c, orbits, dt)
    t_min = sim["t"] / 60
    a, T = sim["a"], sim["T"]
    beta = math.radians(c.beta_deg)
    n = len(t_min)
    idx = np.linspace(0, n - 1, frames).astype(int)

    fig = plt.figure(figsize=(11, 5.4))
    gs = fig.add_gridspec(2, 2, width_ratios=[1, 1.35])
    ax0 = fig.add_subplot(gs[:, 0])
    axp = fig.add_subplot(gs[0, 1])
    axb = fig.add_subplot(gs[1, 1])

    # --- orbit view (looking at the orbit plane, Sun on the right) ---
    lim = 1.5 * a
    ax0.set(xlim=(-lim, lim), ylim=(-lim, lim), aspect="equal")
    ax0.axis("off")
    xs = np.linspace(-lim, 0, 200)
    ys = np.sqrt(np.clip(RE ** 2 - (xs * math.sin(beta)) ** 2, 0, None))
    ax0.fill_between(xs, -ys, ys, color="0.85", zorder=0)                  # shadow
    ax0.add_patch(plt.Circle((0, 0), a, fill=False, ls="--", color="0.6"))  # orbit
    ax0.add_patch(plt.Circle((0, 0), RE, color="#3b7dd8", zorder=2))         # Earth
    ax0.annotate("", xy=(0.95 * a, 0), xytext=(1.45 * a, 0),
                 arrowprops=dict(arrowstyle="-|>", color="#f2a900", lw=2))
    ax0.text(1.2 * a, 0.12 * a, "Sun", color="#f2a900", ha="center", fontsize=11, weight="bold")
    ax0.text(-1.28 * a, 0.0, "Earth's\nshadow", color="0.4", ha="center", va="center", fontsize=9, zorder=6)
    sat, = ax0.plot([], [], "o", ms=10, zorder=5)
    status = ax0.text(0, -1.38 * a, "", ha="center", fontsize=11, weight="bold")

    # --- power vs time ---
    gen_line, = axp.plot([], [], color="#f2a900", lw=2, label="Generation")
    axp.axhline(sim["load"], color="#d62728", ls="--", lw=1.5, label="Average load")
    axp.set(xlim=(0, t_min[-1]), ylim=(0, max(sim["gen"].max(), sim["load"]) * 1.25),
            ylabel="Power (W)")
    axp.legend(loc="upper right", fontsize=8)
    # --- battery state of charge ---
    soc_line, = axb.plot([], [], color="#2ca02c", lw=2)
    axb.axhline(sim["cap"], color="0.5", ls=":", lw=1)
    axb.set(xlim=(0, t_min[-1]), ylim=(0, sim["cap"] * 1.15),
            xlabel="Time (min)", ylabel="Battery (Wh)")
    # shade eclipse intervals on both time plots
    e = sim["in_ecl"].astype(int)
    starts = np.where(np.diff(e) == 1)[0] + 1
    ends = np.where(np.diff(e) == -1)[0] + 1
    if e[0]:
        starts = np.r_[0, starts]
    if e[-1]:
        ends = np.r_[ends, n - 1]
    for s0, s1 in zip(starts, ends):
        for ax in (axp, axb):
            ax.axvspan(t_min[s0], t_min[s1], color="0.85", zorder=0)
    for ax in (axp, axb):
        ax.grid(alpha=0.3)
    fig.suptitle(f"CubeSat power over {orbits} orbits: {c.altitude_km:.0f} km, beta {c.beta_deg:.0f} deg, "
                 f"{c.attitude}", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.95))

    def update(f):
        i = idx[f]
        th = sim["theta"][i]
        sat.set_data([a * math.cos(th)], [a * math.sin(th)])
        sat.set_color("#444444" if sim["in_ecl"][i] else "#f2a900")
        orbit_no = int(sim["t"][i] // T) + 1
        status.set_text(f"{'ECLIPSE' if sim['in_ecl'][i] else 'SUNLIGHT'}  |  orbit {orbit_no}  |  "
                        f"battery {sim['soc'][i]:.2f} Wh")
        gen_line.set_data(t_min[: i + 1], sim["gen"][: i + 1])
        soc_line.set_data(t_min[: i + 1], sim["soc"][: i + 1])
        return sat, status, gen_line, soc_line

    ani = FuncAnimation(fig, update, frames=len(idx), interval=1000 / fps, blit=False)
    ani.save(path, writer=PillowWriter(fps=fps), dpi=80)
    plt.close(fig)
    return path


# ---------------- self-test ----------------
def selftest():
    # 500 km: period ~94.6 min, max eclipse ~35.8 min (textbook values)
    assert abs(orbit_period_s(500) / 60 - 94.6) < 0.3
    assert abs(eclipse_time_s(500, 0) / 60 - 35.8) < 0.5
    # beyond the critical beta angle there is no eclipse
    assert eclipse_time_s(500, 80) == 0.0
    # tumbling cube, 4 faces: 4 * A/4 = one face-equivalent of projected area
    c = Config()
    expected = S0 * c.cell_efficiency * c.packing_factor * c.degradation * c.face_area_m2
    assert abs(sunlit_generation_w(c) - expected) < 1e-9
    # eclipse-free orbit must need less battery than beta 0
    assert analyze(Config(beta_deg=80))["battery_capacity_wh_required"] == 0
    # time simulation: eclipse fraction matches the analytic formula
    c0 = Config()
    sim = simulate(c0, orbits=2, dt=5.0)
    ecl_frac = sim["in_ecl"].mean()
    assert abs(ecl_frac - eclipse_time_s(500, 0) / orbit_period_s(500)) < 0.01
    # eclipse-free orbit keeps the battery full
    full = simulate(Config(beta_deg=80), orbits=2)
    assert full["soc"].min() >= full["cap"] - 1e-6
    # a power-negative design loses charge over successive orbits
    assert sim["soc"][-1] < sim["soc"][0] + 1e-9
    print("selftest passed")


# ---------------- CLI ----------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="JSON file overriding defaults")
    ap.add_argument("--alt", type=float, help="altitude, km")
    ap.add_argument("--beta", type=float, help="beta angle, deg")
    ap.add_argument("--attitude", choices=["tumbling", "sun_pointing"])
    ap.add_argument("--faces", type=int, help="faces covered with cells (tumbling)")
    ap.add_argument("--deployed-area", type=float, help="deployed panel area, m^2 (sun_pointing)")
    ap.add_argument("--out", default="results", help="output folder")
    ap.add_argument("--animate", action="store_true", help="write an animated GIF of the orbits")
    ap.add_argument("--orbits", type=int, default=3, help="orbits to animate")
    ap.add_argument("--battery-wh", type=float, help="battery capacity for the animation (default: auto)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    cfg = Config()
    if a.config:
        with open(a.config) as f:
            data = json.load(f)
        cfg = Config(**{**asdict(cfg), **data})
    if a.alt is not None:
        cfg.altitude_km = a.alt
    if a.beta is not None:
        cfg.beta_deg = a.beta
    if a.attitude:
        cfg.attitude = a.attitude
    if a.faces is not None:
        cfg.covered_faces = a.faces
    if a.deployed_area is not None:
        cfg.deployed_area_m2 = a.deployed_area

    if a.battery_wh is not None:
        cfg.battery_capacity_wh = a.battery_wh

    result = analyze(cfg)
    print_report(cfg, result)

    rows = beta_sweep(cfg)
    worst = min(rows, key=lambda r: r["power_margin_pct"])
    print(f"\nWorst case over beta 0-90 deg: margin {worst['power_margin_pct']:+.1f} % at beta {worst['beta_deg']} deg")
    path = make_plots(cfg, rows, a.out)
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump({"config": asdict(cfg), "result": result, "worst_case": worst}, f, indent=2)
    print(f"Saved: {path} and {a.out}/summary.json")
    if a.animate:
        gif = animate(cfg, os.path.join(a.out, "power_animation.gif"), orbits=a.orbits)
        print(f"Saved animation: {gif}")


if __name__ == "__main__":
    main()
