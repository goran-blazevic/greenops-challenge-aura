import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fake_env import FakeEnv                      # noqa: E402
from orchestrator.controller import Controller    # noqa: E402
from orchestrator.core import Illegal, Model, Usage, decide_run, dirty_run_h, excess, quantile  # noqa: E402

CATALOG = json.loads((ROOT / "challenge/catalog.json").read_text())
WORKLOADS = json.loads((ROOT / "challenge/workloads.json").read_text())


def model():
    return Model(CATALOG, WORKLOADS)


def run_sim(seed=1, carbon_aware=True, margin=1.25, hours=120):
    m = model()
    env = FakeEnv(m, WORKLOADS, seed)
    ctl = Controller(env, m, carbon_aware=carbon_aware, margin=margin, log=lambda *_: None)
    ticks = int(hours * 3600 / 720)
    for _ in range(ticks):
        r = ctl.tick()
        env.advance(720)
        if r == "done":
            break
    ctl.tick()
    return env, ctl


class LegalityTests(unittest.TestCase):
    def test_every_option_is_legal_for_every_workload(self):
        m = model()
        for w in WORKLOADS:
            opts = list(m.options(w))
            self.assertTrue(opts, w["id"])
            for slug, p in opts:
                m.assert_legal(w, slug, p["id"])
                c = m.zones[slug]["country"]
                self.assertNotIn(c, w.get("forbidden_countries", []))
                if w.get("allowed_countries"):
                    self.assertIn(c, w["allowed_countries"])
                if w["residency"] == "EU":
                    self.assertTrue(m.zones[slug]["eu_member"])
                if len(w["residency"]) == 2 and w["residency"] != "EU":
                    self.assertEqual(c, w["residency"])

    def test_known_restrictions(self):
        m = model()
        zones = lambda wid: {s for s, _ in m.options(m.workloads[wid])}  # noqa: E731
        self.assertEqual(zones("w-02-ch-reporting"), {"ch-dk-2", "ch-gva-2"})
        self.assertEqual(zones("w-08-ch-imaging"), {"ch-gva-2"})
        self.assertTrue(zones("w-07-eu-training") <= {"de-fra-1", "hr-zag-1"})
        self.assertNotIn("ch-dk-2", zones("w-09-eu-large-model"))
        self.assertNotIn("fr-par-1", zones("w-01-dach-research"))

    def test_illegal_placement_raises(self):
        m = model()
        with self.assertRaises(Illegal):
            m.assert_legal(m.workloads["w-02-ch-reporting"], "de-fra-1", "20000000-0000-4000-8000-000000000003")
        with self.assertRaises(Illegal):
            m.assert_legal(m.workloads["w-08-ch-imaging"], "de-fra-1", "20000000-0000-4000-8000-000000000008")


class PolicyTests(unittest.TestCase):
    def test_quota_fit(self):
        m = model()
        u = Usage()
        mega = m.profiles["20000000-0000-4000-8000-000000000003"]
        for _ in range(10):
            self.assertTrue(u.fits(m, mega))
            u.add(mega)
        self.assertFalse(u.fits(m, mega))                 # 320 vCPU reached

    def test_decide_run_prefers_clean_hours(self):
        clean = [50.0] * 6 + [300.0] * 18
        self.assertEqual(decide_run(10, 90, 1, clean)[0], True)
        self.assertEqual(decide_run(10, 90, 1, [300.0] + clean)[0], False)
        self.assertEqual(decide_run(80, 90, 1, [300.0] + clean), (True, True))   # no slack -> run

    def test_quantile(self):
        self.assertAlmostEqual(quantile([1, 2, 3, 4], 0.5), 2.5)



    def test_gpu_reservation_prefers_shorter_profile_for_clean_window(self):
        from orchestrator.core import parse_ts, rank_options
        m = model()
        w = m.workloads["w-09-eu-large-model"]
        opts = rank_options(m, w, parse_ts("2025-10-01T07:00:00Z"), 0.0, {})
        clean_window = [o for o in opts if o.ratio <= 0.40]
        self.assertTrue(clean_window)
        # A one-card small VM is not a valid reservation for this 46h workload.
        self.assertTrue(all(m.profiles[o.pid]["size"] != "small" for o in clean_window))


    def test_long_gpu_waits_for_a_clean_window_profile_when_quota_tight(self):
        from orchestrator.core import parse_ts
        m=model(); env=FakeEnv(m,WORKLOADS,1); ctl=Controller(env,m,log=lambda *_:None)
        wid="w-07-eu-training"; w=m.workloads[wid]
        # Deliberately occupy quota so only the small profile could fit.
        usage=Usage(); usage.vms=19; usage.vcpus=280
        for family,n in (("gpurtx6000pro",2),): usage.cards[family]=n
        ctl._todo=[wid]; ctl._plans={wid:{"completed":0.0,"laxity":60.0}}
        ctl.usage=lambda: usage
        ctl._with_reservations=lambda wid,now: usage
        before=len(env.vms)
        ctl._create(w, parse_ts("2025-09-30T13:00:00Z"))
        self.assertEqual(len(env.vms),before)

    def test_long_gpu_uses_clean_window_profile_when_quota_available(self):
        from orchestrator.core import parse_ts
        m=model(); env=FakeEnv(m,WORKLOADS,1); ctl=Controller(env,m,log=lambda *_:None)
        wid="w-09-eu-large-model"; w=m.workloads[wid]
        ctl._todo=[wid]; ctl._plans={wid:{"completed":0.0,"laxity":60.0}}
        ctl._with_reservations=lambda wid,now: Usage()
        ctl._create(w, parse_ts("2025-10-01T07:00:00Z"))
        vm=next(iter(env.vms.values()))
        self.assertEqual(m.profiles[vm["pid"]]["size"], "medium")

class EndToEnd(unittest.TestCase):
    def test_all_workloads_meet_deadlines_and_vms_are_deleted(self):
        for seed in (1, 2, 3):
            env, ctl = run_sim(seed)
            self.assertEqual(env.late(), {}, f"seed {seed}")
            self.assertEqual(env.vms, {}, f"seed {seed}: idle VMs left")

    def test_saves_carbon_vs_always_on(self):
        for seed in (1, 2, 3):
            smart, _ = run_sim(seed, True)
            base, _ = run_sim(seed, False)
            self.assertEqual(base.late(), {})
            self.assertLess(smart.carbon, base.carbon, f"seed {seed}")


class PauseValueAndParking(unittest.TestCase):
    def test_excess_and_dirty_stretch(self):
        clean = [50.0] * 6 + [300.0] * 18
        self.assertEqual(excess(10, 90, 1, clean), 0.0)              # clean hour: nothing to gain
        self.assertGreater(excess(10, 90, 1, [300.0] + clean), 1.0)  # far above the run threshold
        self.assertEqual(dirty_run_h(10, 90, 1, [300.0] * 5 + clean), 5)


    def test_only_short_checkpoint_jobs_are_eligible_for_parking(self):
        m=model()
        ctl=Controller(FakeEnv(m,WORKLOADS,1),m,log=lambda *_:None)
        # w-04 and w-14 checkpoint at 15 min; w-05 and w-13 need 30 min.
        for wid in ("w-04-dach-batch", "w-14-bulk-render"):
            w=m.workloads[wid]
            a={"laxity":24.0}
            self.assertTrue(ctl._portable(w,a))
        for wid in ("w-05-eu-render", "w-13-regional-index"):
            w=m.workloads[wid]
            a={"laxity":24.0}
            self.assertFalse(ctl._portable(w,a))

    def test_only_cheap_to_restart_jobs_are_parked_and_restarts_stay_legal(self):
        for seed in (1, 2):
            env, ctl = run_sim(seed)
            parked = {}
            for t, ev, name, zone in env.log:
                if ev == "create" and name != "orch-starter":
                    wid = name[5:].rsplit("-", 2)[0]
                    parked[wid] = parked.get(wid, 0) + 1
            for wid, n in parked.items():
                w = ctl.m.workloads[wid]
                if n > int(w["max_workers"]):        # recreated -> must be a portable job
                    self.assertFalse(w["restart_from_zero"], wid)
                    self.assertLessEqual(w["checkpoint_seconds"], 1800, wid)
                    self.assertLessEqual(w["input_seconds"], 900, wid)
            self.assertEqual(env.late(), {}, f"seed {seed}")


class EndedRun(unittest.TestCase):
    def test_finished_run_is_reported_not_claimed_as_success(self):
        class Done:
            def status(self):
                return {"state": "COMPLETED", "qualification": "QUALIFIED", "virtual_time": "2025-10-05T00:00:00Z",
                        "workloads": [{"final_output_delivered": i < 2} for i in range(15)]}
        msgs = []
        ctl = Controller(Done(), model(), log=msgs.append)
        self.assertEqual(ctl.tick(), "ended")
        self.assertIn("2 of 15", msgs[0])


class QuotaFallback(unittest.TestCase):
    def test_waits_instead_of_taking_a_plan_that_cannot_meet_the_deadline(self):
        from orchestrator.core import parse_ts, pick, rank_options
        m = model()
        w = m.workloads["w-12-late-delivery"]
        opts = rank_options(m, w, parse_ts("2025-10-02T09:36:00Z"), 0.0, {})
        u = Usage()
        u.vms, u.vcpus = 12, 304                      # only 16 vCPU left: just a "huge" would fit
        self.assertIsNone(pick(opts, m, u))           # huge needs 61 h of the 62 h left -> wait for a mega
        u.vcpus = 280                                 # 40 vCPU free: a mega fits
        o = pick(opts, m, u)
        self.assertEqual(m.profiles[o.pid]["size"], "mega")
