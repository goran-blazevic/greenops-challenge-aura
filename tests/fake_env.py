"""Small stand-in for the hosted simulator, used to test the orchestrator offline.

It models the rules the controller depends on (quotas, residency, boot/input/
output phases, throughput with sync overhead, stop/start, clock start on the
first VM, per-hour carbon intensity x PUE).  The electricity series are
synthetic and exist only inside this test file.
"""
import math
import random
from datetime import datetime, timedelta, timezone

from orchestrator.core import Illegal, Usage, eff_rate, parse_ts

AREA = {  # base, amplitude, hour of the daily minimum (solar / wind style)
    "AT": (140, 60, 13), "CH": (45, 15, 13), "DE": (330, 130, 13), "ES": (170, 90, 14),
    "IT": (280, 80, 13), "HR": (230, 70, 12), "BG": (450, 60, 12), "FR": (60, 15, 3),
}


class FakeEnv:
    def __init__(self, model, workloads, seed=1, start="2025-09-30T00:00:00Z"):
        self.m, self.rng = model, random.Random(seed)
        self.t = parse_ts(start)
        self.start = self.t
        self.clock = False
        self.vms, self.n = {}, 0
        self.w = {x["id"]: dict(x, done=0.0, out_left=x["output_seconds"], delivered=None) for x in workloads}
        self.carbon = 0.0
        self.kwh = 0.0
        self.log = []
        self.noise = {a: [self.rng.uniform(-1, 1) for _ in range(40)] for a in AREA}
        self.fcerr = {a: self.rng.uniform(-0.25, 0.25) for a in AREA}

    # ------------------------------------------------------------ electricity
    def actual(self, area, t):
        b, amp, mn = AREA[area]
        h = (t - self.start).total_seconds() / 3600
        d = int(h // 24) % 40
        v = b + amp * math.cos(2 * math.pi * ((t.hour - mn) / 24 + 0.5)) * -1 + 0.12 * b * self.noise[area][d]
        return max(15.0, v)

    def forecast(self, area):
        t0 = self.t.replace(minute=0, second=0, microsecond=0)
        return [(t0 + timedelta(hours=i), self.actual(area, t0 + timedelta(hours=i)) * (1 + self.fcerr[area] * i / 24))
                for i in range(24)]

    # ------------------------------------------------------------- Env API
    def status(self):
        ws = []
        for wid, w in self.w.items():
            asg = [{"vm_id": i, "zone": v["zone"], "state": v["state"]} for i, v in self.vms.items() if v["wid"] == wid]
            ws.append({"id": wid, "state": "x", "required_work": w["required_work"],
                       "completed_work": f"{w['done']:.6f}", "work_unit": w["work_unit"], "lost_work": "0.000000",
                       "final_output_delivered": w["delivered"] is not None, "assignments": asg})
        return {"run_id": "t", "virtual_time": self.t.strftime("%Y-%m-%dT%H:%M:%SZ"), "speed_multiplier": 720,
                "state": "RUNNING" if self.clock else "READY", "qualification": "QUALIFIED", "workloads": ws}

    def create(self, zone, p, wid, name):
        if wid:
            w = self.m.workloads[wid]
            self.m.assert_legal(w, zone, p["id"])      # a real run would be disqualified here
        u = Usage()
        for v in self.vms.values():
            u.add(self.m.profiles[v["pid"]])
        if not u.fits(self.m, p):
            raise RuntimeError("quota exceeded")
        self.n += 1
        vid = f"vm{self.n}"
        self.vms[vid] = {"zone": zone, "pid": p["id"], "wid": wid, "state": "creating", "boot": float(p["boot_seconds"]),
                         "stage": float(self.m.workloads[wid]["input_seconds"]) if wid else 0.0, "name": name}
        self.clock = True
        self.log.append((self.t, "create", name, zone))
        return vid

    def set_power(self, zone, vid, run):
        self.vms[vid]["state"] = "running" if run else "stopped"
        self.log.append((self.t, "start" if run else "stop", vid, zone))

    def delete(self, zone, vid):
        self.vms.pop(vid, None)
        self.log.append((self.t, "delete", vid, zone))

    def adopt(self):
        return []

    # ------------------------------------------------------------ simulation
    def advance(self, seconds, step=60):
        if not self.clock:
            return
        for _ in range(int(seconds // step)):
            self._step(step)

    def _step(self, dt):
        self.t += timedelta(seconds=dt)
        for wid, w in self.w.items():
            if w["delivered"]:
                continue
            spec = self.m.workloads[wid]
            ready = []
            for vid, v in self.vms.items():
                if v["wid"] != wid or v["state"] == "stopped":
                    continue
                if v["state"] == "creating":
                    v["boot"] -= dt
                    if v["boot"] <= 0:
                        v["state"] = "running"
                    self._burn(v, "idle", dt)
                elif self.t < parse_ts(spec["release_at"]):
                    self._burn(v, "idle", dt)
                elif v["stage"] > 0:
                    v["stage"] -= dt
                    self._burn(v, "idle", dt)
                else:
                    ready.append(v)
            if ready:
                if w["done"] < float(spec["required_work"]):
                    p = self.m.profiles[ready[0]["pid"]]
                    rate = eff_rate(p, len(ready), float(spec["sync_overhead"]))
                    w["done"] = min(float(spec["required_work"]), w["done"] + rate * dt / 3600)
                    for v in ready:
                        self._burn(v, "active", dt)
                else:
                    w["out_left"] -= dt
                    for v in ready:
                        self._burn(v, "idle", dt)
                    if w["out_left"] <= 0:
                        w["delivered"] = self.t
        for v in self.vms.values():
            if v["wid"] is None and v["state"] != "stopped":
                self._burn(v, "idle", dt)

    def _burn(self, v, mode, dt):
        p = self.m.profiles[v["pid"]]
        z = self.m.zones[v["zone"]]
        watts = float(p["active_watts" if mode == "active" else "idle_watts"])
        kwh = watts / 1000 * dt / 3600 * float(z["pue"])
        self.kwh += kwh
        self.carbon += kwh * self.actual(z["electricity_area"], self.t)

    def late(self):
        out = {}
        for wid, w in self.w.items():
            dl = parse_ts(self.m.workloads[wid]["deadline_at"])
            if w["delivered"] is None or w["delivered"] > dl:
                out[wid] = (w["delivered"], dl)
        return out
