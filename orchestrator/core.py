"""Pure decision logic of the carbon-aware orchestrator.

No network, no wall clock: everything here is a function of public workload /
catalog data, the run's *current* virtual time and the run's *currently
published* forecast.  That keeps it unit-testable and keeps the information
rules of the challenge easy to audit (see docs/RULES.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

HOUR = 3600.0
# Feasibility tiers: share of the available window that a plan may occupy.
# A small share leaves room to pause the VM during dirty hours.
TIERS = (0.55, 0.85, 0.97)
SHARE_MIN = 0.2      # never plan to run in fewer than 20 % of the hours
NEAR_TIE = 1.005     # plans within this cost factor count as ties -> smaller VM (efficiency first)


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


class Illegal(Exception):
    """A placement would violate residency / profile rules."""


class Model:
    def __init__(self, catalog: dict, workloads: list[dict]):
        self.zones = {z["slug"]: z for z in catalog["zones"]}
        self.profiles = {p["id"]: p for p in catalog["profiles"]}
        self.workloads = {w["id"]: w for w in workloads}
        self.max_vms = int(catalog["max_vms"])
        self.max_vcpus = int(catalog["max_vcpus"])
        self.gpu_quota = dict(catalog["gpu_family_quotas"])

    # ---- legality (checked twice: when ranking and right before create) ----
    def zone_ok(self, w: dict, slug: str) -> bool:
        z = self.zones[slug]
        c = z["country"]
        if c in w.get("forbidden_countries", []):
            return False
        allowed = w.get("allowed_countries")
        if allowed and c not in allowed:
            return False
        res = w.get("residency", "ANYWHERE")
        if res == "EU":
            return bool(z["eu_member"])
        if res != "ANYWHERE" and c != res:
            return False
        return True

    def profile_ok(self, w: dict, p: dict, slug: str) -> bool:
        if slug not in p["zones"]:
            return False
        if (p["gpu_count"] > 0) != (w["kind"] == "gpu"):
            return False
        if w.get("allowed_families") and p["family"] not in w["allowed_families"]:
            return False
        if w.get("allowed_profile_ids") and p["id"] not in w["allowed_profile_ids"]:
            return False
        if p["gpu_count"] > 0 and p.get("gpu_memory_gib", 0) < w.get("minimum_gpu_memory_gib", 0):
            return False
        return True

    def assert_legal(self, w: dict, slug: str, pid: str) -> None:
        p = self.profiles[pid]
        if slug not in self.zones or not self.zone_ok(w, slug) or not self.profile_ok(w, p, slug):
            raise Illegal(f"{w['id']} must not run as {pid} in {slug}")

    def options(self, w: dict, exclude=()):
        for slug in self.zones:
            if slug in exclude or not self.zone_ok(w, slug):
                continue
            for p in self.profiles.values():
                if self.profile_ok(w, p, slug):
                    yield slug, p


def rate_per_hour(p: dict) -> float:
    """Work units per hour of one VM (vCPU-hours/h; GPU throughput is tflop/s)."""
    tp = float(p["throughput"])
    return tp if p["work_unit"] == "vcpu_hour" else tp * HOUR


def eff_rate(p: dict, n: int, sync: float) -> float:
    return n * rate_per_hour(p) / (1.0 + sync * (n - 1))


@dataclass
class Usage:
    vms: int = 0
    vcpus: int = 0
    cards: dict = field(default_factory=dict)

    def add(self, p: dict, n: int = 1) -> None:
        self.vms += n
        self.vcpus += n * p["cpu_cores"]
        if p["gpu_count"]:
            self.cards[p["family"]] = self.cards.get(p["family"], 0) + n * p["gpu_count"]

    def sub(self, p: dict, n: int = 1) -> None:
        self.vms -= n
        self.vcpus -= n * p["cpu_cores"]
        if p["gpu_count"]:
            self.cards[p["family"]] -= n * p["gpu_count"]

    def fits(self, m: Model, p: dict, n: int = 1) -> bool:
        if self.vms + n > m.max_vms or self.vcpus + n * p["cpu_cores"] > m.max_vcpus:
            return False
        if p["gpu_count"]:
            return self.cards.get(p["family"], 0) + n * p["gpu_count"] <= m.gpu_quota.get(p["family"], 0)
        return True


def over_quota(m: Model, u: Usage) -> bool:
    return (u.vms > m.max_vms or u.vcpus > m.max_vcpus
            or any(n > m.gpu_quota.get(f, 0) for f, n in u.cards.items()))


@dataclass
class Option:
    zone: str
    pid: str
    ratio: float      # share of the available window used by staging+work+output
    cost: float       # relative carbon cost of the remaining work
    footprint: float  # tie-break: smaller VMs leave quota for the others


def rank_options(m: Model, w: dict, now: datetime, completed: float, ci_mean: dict,
                 exclude=()) -> list[Option]:
    start = max(now, parse_ts(w["release_at"]))
    window_h = max((parse_ts(w["deadline_at"]) - start).total_seconds() / HOUR, 1e-6)
    remaining = max(float(w["required_work"]) - completed, 0.0)
    over_h = (w["input_seconds"] + w["output_seconds"]) / HOUR
    out = []
    for slug, p in m.options(w, exclude):
        z = m.zones[slug]
        work_h = remaining / rate_per_hour(p)
        boot_h = float(p["boot_seconds"]) / HOUR
        ratio = (work_h + over_h + boot_h) / window_h
        ci_data = ci_mean.get(z["electricity_area"], 1.0)
        # A 24h forecast must not be extrapolated across a 40-90h workload.
        # For the post-horizon tail, blend only this run's already-published
        # historical mean, shrinking it toward the current forecast when history
        # is sparse. This is a horizon-aware expected-intensity estimate, not a
        # stored cross-run scenario profile.
        total_h = max(work_h + over_h + boot_h, 1e-9)
        if isinstance(ci_data, dict):
            forecast_ci = float(ci_data.get("forecast_mean", 1.0))
            history_ci = float(ci_data.get("history_mean", forecast_ci))
            hist_n = int(ci_data.get("history_count", 0))
            confidence = min(1.0, hist_n / 12.0)
            tail_ci = history_ci * confidence + forecast_ci * (1.0 - confidence)
            forecast_h = min(total_h, 24.0)
            ci = (forecast_ci * forecast_h + tail_ci * (total_h - forecast_h)) / total_h
        else:
            ci = float(ci_data)
        # IT energy of the remaining work plus the idle boot/staging/output phases
        kwh = (float(p["active_watts"]) * work_h + float(p["idle_watts"]) * (over_h + boot_h)) / 1000.0
        cost = float(z["pue"]) * ci * kwh
        fp = p["cpu_cores"] + 1000 * p["gpu_count"]
        out.append(Option(slug, p["id"], ratio, cost, fp))
    return out


def pick(options: list[Option], m: Model | None = None, usage: Usage | None = None) -> Option | None:
    """Cheapest plan among those that leave room to pause; smallest footprint on near-ties."""
    def fits(o):
        return usage is None or usage.fits(m, m.profiles[o.pid])
    for lim in TIERS:
        tier = [o for o in options if o.ratio <= lim and fits(o)]
        if tier:
            best = min(o.cost for o in tier)
            near = [o for o in tier if o.cost <= best * NEAR_TIE + 1e-12]
            return min(near, key=lambda o: (o.footprint, o.cost))
    if usage is not None and any(o.ratio <= TIERS[-1] for o in options):
        return None          # a safe plan exists but does not fit the quota yet: wait, never take a doomed one
    cand = [o for o in options if fits(o)]
    return min(cand, key=lambda o: o.ratio) if cand else None


def min_footprint(options: list[Option], limit: float = 0.9) -> Option | None:
    """Smallest VM that still meets the deadline (what we must keep free for a workload)."""
    ok = [o for o in options if o.ratio <= limit]
    return min(ok, key=lambda o: (o.footprint, o.cost)) if ok else pick(options)


def quantile(vals: list[float], q: float) -> float:
    s = sorted(vals)
    if not s:
        return float("inf")
    x = min(max(q, 0.0), 1.0) * (len(s) - 1)
    lo = int(x)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (x - lo)


def _threshold(remaining_h: float, hours_to_deadline: float, output_h: float,
               series: list[float], margin: float):
    """(usable hours, run threshold) - the job runs while the current hour is among the
    cleanest q share of the forecast window, q = needed time / usable time x margin."""
    guard = 3.0 + 0.04 * max(hours_to_deadline, 0.0)
    t_avail = hours_to_deadline - output_h - guard
    if t_avail <= 0 or len(series) < 4:
        return t_avail, None
    q = min(1.0, max(SHARE_MIN, remaining_h / t_avail * margin))
    return t_avail, quantile(series[: max(4, min(len(series), int(t_avail)))], q)


def decide_run(remaining_h: float, hours_to_deadline: float, output_h: float,
               series: list[float], margin: float = 1.25) -> tuple[bool, bool]:
    """Return (run_now, forced).

    remaining_h: compute (+ staging) hours still needed at the current rate.
    series: published carbon-intensity forecast, series[0] = current hour.
    The VM runs in the cleanest `q` share of the next hours, where q is the
    share of time the job needs until its deadline (times a safety margin).
    """
    t_avail, thr = _threshold(remaining_h, hours_to_deadline, output_h, series, margin)
    if t_avail <= 0 or remaining_h >= 0.8 * t_avail:
        return True, True
    if thr is None:
        return True, False
    return series[0] <= thr + 1e-9, False


def excess(remaining_h: float, hours_to_deadline: float, output_h: float,
           series: list[float], margin: float = 1.25) -> float:
    """How much dirtier the current hour is than the job's run threshold
    (0.25 = 25 % above it); 0 when it should run anyway."""
    _, thr = _threshold(remaining_h, hours_to_deadline, output_h, series, margin)
    return max(0.0, series[0] / thr - 1.0) if thr else 0.0


def dirty_run_h(remaining_h: float, hours_to_deadline: float, output_h: float,
                series: list[float], margin: float = 1.25) -> int:
    """Forecast hours from now until the job would want to run again."""
    _, thr = _threshold(remaining_h, hours_to_deadline, output_h, series, margin)
    if thr is None:
        return 0
    n = 0
    for v in series:
        if v <= thr + 1e-9:
            break
        n += 1
    return n


def workers_needed(remaining: float, hours_avail: float, p: dict, w: dict) -> int:
    """Smallest worker count that finishes `remaining` work in `hours_avail`."""
    s = float(w["sync_overhead"])
    for n in range(1, int(w["max_workers"]) + 1):
        if eff_rate(p, n, s) * max(hours_avail, 0.0) >= remaining * 1.05:
            return n
    return int(w["max_workers"])
