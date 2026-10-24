"""Offline policy benchmark: compares controller variants on many SYNTHETIC grids.

    python tests/bench.py                 # current controller, 24 synthetic scenarios
    python tests/bench.py --seeds 60 --grid fake    # daily-cycle grid of tests/fake_env.py

Every scenario draws random grid levels, daily cycles, multi-day weather swings,
noise and forecast errors per electricity area.  None of these numbers is real
or taken from a run: they only exist to check that a policy change helps across
many different grids instead of one lucky curve.  The orchestrator never reads
anything from this file.

Accounting follows docs/API.md: boot, staging, output and unbound time draw idle
watts, compute draws active watts, stopped VMs draw nothing; lifecycle kg/h is
charged for every non-stopped hour.  The controller is polled every ~12-25
virtual minutes, like a 1 s wall poll at 720x plus API latency.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fake_env import FakeEnv                       # noqa: E402
from orchestrator.controller import Controller     # noqa: E402
from orchestrator.core import Model                # noqa: E402

CATALOG = json.loads((ROOT / "challenge/catalog.json").read_text())
WORKLOADS = json.loads((ROOT / "challenge/workloads.json").read_text())
AREAS = ["AT", "BG", "CH", "DE", "ES", "FR", "HR", "IT"]
GRID = "synth"        # "fake": the simpler daily-cycle grid of tests/fake_env.py
TICKS = (720, 780, 840, 960, 1200, 1500)   # virtual seconds between controller polls
STAGE_ACTIVE = False  # stress test: input staging draws active instead of idle watts


class SynthGrid:
    """Random synthetic grid per seed: level x (daily cycle + weather swing + noise)."""

    def __init__(self, seed: int, start, hours=150):
        r = random.Random(seed * 7919 + 13)
        self.start, self.series = start, {}
        for a in AREAS:
            level = math.exp(r.uniform(math.log(60), math.log(500)))
            solar = r.uniform(0.0, 0.55)                  # midday dip depth
            evening = r.uniform(0.0, 0.25)                # evening peak
            swing = r.uniform(0.05, 0.45)                 # multi-day weather amplitude
            period = r.uniform(40, 110)
            phase = r.uniform(0, 2 * math.pi)
            noise = r.uniform(0.02, 0.12)
            vals, ar = [], 0.0
            for h in range(hours + 30):
                hod = h % 24
                day = -solar * max(0.0, math.cos((hod - 13) / 24 * 2 * math.pi)) ** 2
                eve = evening * math.exp(-((hod - 19) ** 2) / 6)
                wx = swing * math.sin(2 * math.pi * h / period + phase)
                ar = 0.8 * ar + r.gauss(0, noise)
                vals.append(max(5.0, level * (1 + day + eve + wx + ar)))
            self.series[a] = vals
            self.ferr = getattr(self, "ferr", {})
            self.ferr[a] = (r.gauss(0, 0.06), [r.gauss(0, 1) for _ in range(hours + 30)])

    def actual(self, area, t):
        h = int((t - self.start).total_seconds() // 3600)
        return self.series[area][max(0, min(h, len(self.series[area]) - 1))]

    def forecast(self, area, now):
        """Smoothed, biased, horizon-growing error; re-issued every hour."""
        t0 = now.replace(minute=0, second=0, microsecond=0)
        h0 = int((t0 - self.start).total_seconds() // 3600)
        bias, eps = self.ferr[area]
        s = self.series[area]
        out = []
        for i in range(24):
            k = max(0, min(h0 + i, len(s) - 1))
            sm = (s[max(k - 1, 0)] + 2 * s[k] + s[min(k + 1, len(s) - 1)]) / 4
            err = bias * (i / 24) + 0.012 * math.sqrt(i) * eps[(h0 + i) % len(eps)]
            out.append((t0 + timedelta(hours=i), max(5.0, sm * (1 + err))))
        return out


class BenchEnv(FakeEnv):
    def __init__(self, model, workloads, seed):
        super().__init__(model, workloads, seed)
        self.grid = SynthGrid(seed, self.start)
        self.life = 0.0
        self.lost = 0.0

    def actual(self, area, t):
        if GRID == "fake":
            return FakeEnv.actual(self, area, t)
        return self.grid.actual(area, t)

    def forecast(self, area):
        if GRID == "fake":
            return FakeEnv.forecast(self, area)
        return self.grid.forecast(area, self.t)

    def _burn(self, v, mode, dt):
        if STAGE_ACTIVE and mode == "idle" and v.get("stage", 0) > 0 and v["state"] == "running":
            mode = "active"
        super()._burn(v, mode, dt)

    def _step(self, dt):
        before = {wid: w["done"] for wid, w in self.w.items()}
        super()._step(dt)
        for v in self.vms.values():
            if v["state"] != "stopped":
                self.life += float(self.m.profiles[v["pid"]]["lifecycle_kg_per_hour"]) * dt / 3600
        for wid, w in self.w.items():                 # checkpoint every checkpoint_seconds of compute
            c = self.m.workloads[wid]["checkpoint_seconds"]
            if w["done"] > before[wid] and c > 0:
                w["since"] = w.get("since", 0.0) + dt
                if w["since"] >= c or w["done"] >= float(self.m.workloads[wid]["required_work"]):
                    w["ckpt"], w["since"] = w["done"], 0.0

    def delete(self, zone, vid):
        """Deleting the last worker drops uncheckpointed progress (restart_from_zero: all of it)."""
        v = self.vms.get(vid)
        super().delete(zone, vid)
        if not v or not v["wid"]:
            return
        w = self.w[v["wid"]]
        if w["delivered"] or any(o["wid"] == v["wid"] for o in self.vms.values()):
            return
        spec = self.m.workloads[v["wid"]]
        keep = 0.0 if spec["restart_from_zero"] else w.get("ckpt", 0.0)
        if w["done"] < float(spec["required_work"]):
            self.lost += w["done"] - keep
            w["done"], w["since"] = keep, 0.0

    def status(self):
        st = super().status()
        st["workloads"] = [dict(x, completed_work=f"{self.w[x['id']]['done']:.6f}") for x in st["workloads"]]
        return st


def run(seed, make_ctl=None, hours=120):
    m = Model(CATALOG, WORKLOADS)
    env = BenchEnv(m, WORKLOADS, seed)
    ctl = (make_ctl or (lambda e, mm: Controller(e, mm, log=lambda *_: None)))(env, m)
    rng = random.Random(seed)
    end = env.start + timedelta(hours=hours)
    ctl.tick()                                    # READY -> starter VM starts the clock
    while env.t < end:
        r = ctl.tick()
        env.advance(rng.choice(TICKS), step=60)
        if r == "done":
            break
    while env.t < end:                            # nothing left: account any leftovers
        env.advance(3600, step=60)
    return {"kg": env.carbon / 1000, "life": env.life, "kwh": env.kwh, "late": len(env.late()),
            "left": len(env.vms), "lost": env.lost}


def summary(name, rows):
    kg = [r["kg"] for r in rows]
    print(f"{name:14s} usage {statistics.mean(kg):7.3f} kg  lifecycle {statistics.mean(r['life'] for r in rows):6.3f} kg"
          f"  energy {statistics.mean(r['kwh'] for r in rows):6.1f} kWh  late {sum(r['late'] for r in rows)}"
          f"  leftover VMs {sum(r['left'] for r in rows)}  lost {statistics.mean(r['lost'] for r in rows):.1f}")
    return kg


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=24)
    ap.add_argument("--grid", choices=["synth", "fake"], default="synth")
    a = ap.parse_args()
    GRID = a.grid
    summary("controller", [run(s) for s in range(1, a.seeds + 1)])
