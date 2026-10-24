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


FORECAST_H = 24      # hours of forecast this run publishes; the sample we rank on


class Forecast:
    """Per-area view of *this* run's currently published carbon intensity.

    Besides the plain mean it answers "what intensity may a plan expect if it only
    runs during the cleanest `duty` share of the published hours?".  That is the
    intensity placement actually faces, because `decide_run` keeps the VM off during
    the dirty ones.  Ranking on the flat mean undervalues a volatile grid and makes
    every size of one GPU family look identical, which is what the footprint
    tie-break then had to resolve blindly.
    """

    def __init__(self, means: dict | None = None):
        self._mean: dict[str, float] = {k: float(v) for k, v in (means or {}).items()}
        self._cum: dict[str, list[float]] = {}

    def set(self, area: str, vals: list[float]) -> None:
        window = [float(v) for v in vals[:FORECAST_H]]
        if not window:
            return
        self._mean[area] = sum(window) / len(window)
        cum, total = [0.0], 0.0
        for v in sorted(window):
            total += v
            cum.append(total)
        self._cum[area] = cum

    def setdefault(self, area: str, value: float) -> None:
        self._mean.setdefault(area, value)

    def means(self) -> dict:
        return self._mean

    def mean(self, area: str) -> float:
        return self._mean.get(area, 1.0)

    def duty_mean(self, area: str, duty: float) -> float:
        """Mean of the cleanest `duty` share of the published hours, interpolated over
        the partial hour.  Falls back to the flat mean when no series is published."""
        cum = self._cum.get(area)
        if not cum:
            return self.mean(area)
        n = len(cum) - 1
        x = min(max(duty, 1.0 / n), 1.0) * n
        k = int(x)
        rest = x - k
        nxt = (cum[k + 1] - cum[k]) if k < n else 0.0   # the (k+1)-th cleanest hour
        return (cum[k] + rest * nxt) / x


def as_forecast(ci) -> Forecast:
    return ci if isinstance(ci, Forecast) else Forecast(ci)


@dataclass
class Option:
    zone: str
    pid: str
    ratio: float      # share of the available window used by staging+work+output
    cost: float       # relative carbon cost of the remaining work
    footprint: float  # tie-break: smaller VMs leave quota for the others


def rank_options(m: Model, w: dict, now: datetime, completed: float, ci,
                 exclude=(), margin: float = 1.0, duty_aware: bool = True) -> list[Option]:
    """Expected carbon of finishing `w` on each legal (zone, profile).

    The compute phase is the only part that can be shifted, so it is priced at the
    mean of the cleanest hours a plan with that duty cycle can occupy; boot, input
    staging and output run whenever they fall and are priced at the flat mean.
    A faster profile therefore earns its keep through a lower duty cycle, which is
    the real reason to prefer it over a smaller one of the same efficiency.
    """
    f = as_forecast(ci)
    start = max(now, parse_ts(w["release_at"]))
    window_h = max((parse_ts(w["deadline_at"]) - start).total_seconds() / HOUR, 1e-6)
    remaining = max(float(w["required_work"]) - completed, 0.0)
    over_h = (w["input_seconds"] + w["output_seconds"]) / HOUR
    out = []
    for slug, p in m.options(w, exclude):
        z = m.zones[slug]
        area = z["electricity_area"]
        work_h = remaining / rate_per_hour(p)
        boot_h = float(p["boot_seconds"]) / HOUR
        idle_h = over_h + boot_h
        ratio = (work_h + idle_h) / window_h
        duty = min(1.0, work_h / max(window_h - idle_h, 1e-6) * margin)
        ci_work = f.duty_mean(area, duty) if duty_aware else f.mean(area)
        # IT energy of the remaining work plus the idle boot/staging/output phases
        kwh_work = float(p["active_watts"]) * work_h / 1000.0
        kwh_idle = float(p["idle_watts"]) * idle_h / 1000.0
        cost = float(z["pue"]) * (ci_work * kwh_work + f.mean(area) * kwh_idle)
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


def carbon_workers(w: dict, p: dict, remaining: float, hours_avail: float, ci,
                   area: str, margin: float = 1.25, gain: float = 0.04) -> int:
    """Worker count with the lowest expected carbon, not merely the one that fits.

    `n` workers cost `1 + sync_overhead * (n - 1)` times the energy of one, but finish
    in roughly `1/n` of the time and can therefore sit in the cleanest hours only.
    Whenever the spread of the published forecast is wider than the sync penalty, more
    workers are the cheaper plan; `gain` keeps us from paying for a marginal one.
    """
    f = as_forecast(ci)
    s = float(w["sync_overhead"])
    best_n, best_c = 1, None
    for n in range(1, int(w["max_workers"]) + 1):
        work_h = remaining / eff_rate(p, n, s)
        duty = min(1.0, work_h / max(hours_avail, 1e-6) * margin)
        c = (1.0 + s * (n - 1)) * f.duty_mean(area, duty)
        if n == 1:
            best_c = c
        elif best_c is not None and c < best_c * (1.0 - gain):
            best_n, best_c = n, c
    return best_n
