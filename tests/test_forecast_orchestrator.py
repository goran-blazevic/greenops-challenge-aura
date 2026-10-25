import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "examples/python/forecast_orchestrator.py"
spec = importlib.util.spec_from_file_location("forecast_orchestrator", SCRIPT)
optimizer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(optimizer)


class ForecastPlanTests(unittest.TestCase):
    def test_all_workloads_fit_public_limits_and_rules(self):
        plan, catalog, workloads, groups, vcpus = optimizer.validate_plan(
            SCRIPT.parents[1] / "forecast-workload-plan.json"
        )
        self.assertEqual(len(plan["placements"]), 15)
        self.assertEqual(set(groups), set(workloads))
        self.assertEqual(vcpus, 304)
        self.assertLessEqual(vcpus, 320)
        self.assertLessEqual(len(plan["placements"]), catalog["max_vms"])
        by_work = {wid: rows for wid, rows in groups.items()}
        self.assertEqual([(p["family"], p["size"]) for p, _ in by_work["w-07-eu-training"]], [("gpurtx6000pro", "small")])
        self.assertEqual([(p["family"], p["size"]) for p, _ in by_work["w-08-ch-imaging"]], [("gpua30", "small")])
        self.assertEqual([(p["family"], p["size"]) for p, _ in by_work["w-10-eu-visual"]], [("gpu3", "small")])


    def test_long_job_tail_uses_same_run_history_and_forecast_risk_proxy(self):
        _, _, workloads, groups, _ = optimizer.validate_plan(
            SCRIPT.parents[1] / "forecast-workload-plan.json"
        )
        task = workloads["w-09-eu-large-model"]
        workers = groups["w-09-eu-large-model"]
        start = datetime(2025, 10, 1, 7, tzinfo=timezone.utc)
        forecast = [(start + optimizer.timedelta(hours=i), float(v)) for i, v in enumerate([100] * 18 + [220] * 6)]
        history = [(start - optimizer.timedelta(hours=24-i), 250.0) for i in range(24)]
        estimate = optimizer.estimate_full_job_emissions(start, forecast, task, workers, 1.2, history)
        self.assertGreater(estimate["history_mean"], estimate["forecast_mean"])
        self.assertEqual(estimate["mean_intensity_proxy"], 250.0)
        self.assertGreater(estimate["extrapolated_hours"], 0)


    def test_zone_choice_does_not_extrapolate_a_short_forecast_dip(self):
        _, _, workloads, groups, _ = optimizer.validate_plan(SCRIPT.parents[1] / "forecast-workload-plan.json")
        wid = "w-09-eu-large-model"
        task = workloads[wid]
        workers = groups[wid]
        zones = {z["slug"]: z for z in optimizer.load_public_data()[0]["zones"]}
        candidates = optimizer.legal_zone_candidates(task, workers, zones)
        now = datetime(2025, 10, 1, 7, tzinfo=timezone.utc)
        hr_forecast = [(now + optimizer.timedelta(hours=i), 80.0) for i in range(24)]
        de_forecast = [(now + optimizer.timedelta(hours=i), 130.0) for i in range(24)]
        hr_history = [(now - optimizer.timedelta(hours=24-i), 260.0) for i in range(24)]
        de_history = [(now - optimizer.timedelta(hours=24-i), 140.0) for i in range(24)]
        forecasts = {
            "HR": {"points": hr_forecast, "history_points": hr_history, "updated_at": "run-local"},
            "DE": {"points": de_forecast, "history_points": de_history, "updated_at": "run-local"},
        }
        pick = optimizer.choose_site_and_time(task, workers, candidates, forecasts, now, 0)
        self.assertEqual(pick["zone"]["slug"], "de-fra-1")

    def test_finalized_run_is_reported_without_cloud_mutation(self):
        status = {"state": "COMPLETED", "workloads": [
            {"id": "a", "final_output_delivered": True},
            {"id": "b", "final_output_delivered": True},
        ]}
        message = optimizer.finalized_run_message(status)
        self.assertIn("2/2 outputs delivered", message)
        self.assertIn("rejects VM deletes after completion", message)


    def test_delete_error_reconciles_already_absent_vm(self):
        class Cloud:
            def delete_instance(self, id):
                raise RuntimeError("simulated ambiguous delete")
            def list_instances(self):
                return {"instances": []}
        class Static:
            def client(self, account, endpoint): return Cloud()
            def save(self, path, state): self.saved = True
        class Work:
            def status(self, account): return {"state": "RUNNING"}
        static = Static()
        state = {"instances": [{"id": "vm-1", "name": "task-vm"}]}
        row = state["instances"][0]
        optimizer.cleanup_delivered_instance(static, Work(), {}, "zone-url", row, state, Path("unused"))
        self.assertEqual(state["instances"], [])
        self.assertTrue(static.saved)

    def test_delete_error_retains_vm_when_still_allocated(self):
        class Cloud:
            def delete_instance(self, id):
                raise RuntimeError("simulated bad request")
            def list_instances(self):
                return {"instances": [{"id": "vm-1"}]}
        class Static:
            def client(self, account, endpoint): return Cloud()
            def save(self, path, state): self.saved = True
        class Work:
            def status(self, account): return {"state": "RUNNING"}
        state = {"instances": [{"id": "vm-1", "name": "task-vm"}]}
        with self.assertRaisesRegex(RuntimeError, "still allocated"):
            optimizer.cleanup_delivered_instance(Static(), Work(), {}, "zone-url", state["instances"][0], state, Path("unused"))
        self.assertEqual(len(state["instances"]), 1)


    def test_carbon_control_pauses_forecast_peak_only_with_deadline_slack(self):
        _, _, workloads, groups, _ = optimizer.validate_plan(
            SCRIPT.parents[1] / "forecast-workload-plan.json"
        )
        task = workloads["w-01-dach-research"]
        base = datetime(2025, 9, 30, 4, tzinfo=timezone.utc)
        points = [(base + optimizer.timedelta(hours=i), v) for i, v in enumerate([80, 82, 85, 90, 95, 100, 110, 120, 130, 140, 160, 180, 200, 220, 240, 260])]
        points = [(base + optimizer.timedelta(hours=i), v) for i, v in enumerate([80, 82, 85, 90, 95, 100, 110, 120, 130, 140, 160, 180, 200, 220, 240, 260, 90, 85, 80, 80, 85, 90, 95, 100])]
        status = {"state": "running", "required_work": "1000", "completed_work": "100.000000", "work_unit": "vcpu_hour", "assignments": [{"state": "running", "vm_id": "vm1"}]}
        peak_time = base + optimizer.timedelta(hours=15)
        self.assertEqual(optimizer.carbon_pause_action(status, task, groups["w-01-dach-research"], points, peak_time), "pause")

    def test_carbon_control_resumes_at_or_below_forecast_median(self):
        _, _, workloads, groups, _ = optimizer.validate_plan(
            SCRIPT.parents[1] / "forecast-workload-plan.json"
        )
        task = workloads["w-01-dach-research"]
        base = datetime(2025, 9, 30, 4, tzinfo=timezone.utc)
        points = [(base + optimizer.timedelta(hours=i), v) for i, v in enumerate([80, 82, 85, 90, 95, 100, 110, 120, 130, 140, 160, 180, 200, 220, 240, 260])]
        status = {"state": "running", "required_work": "1000", "completed_work": "100.000000", "work_unit": "vcpu_hour", "assignments": [{"state": "stopped", "vm_id": "vm1"}]}
        self.assertEqual(optimizer.carbon_pause_action(status, task, groups["w-01-dach-research"], points, base), "resume")

    def test_carbon_control_wont_pause_near_deadline(self):
        _, _, workloads, groups, _ = optimizer.validate_plan(
            SCRIPT.parents[1] / "forecast-workload-plan.json"
        )
        task = dict(workloads["w-01-dach-research"])
        task["deadline_at"] = "2025-09-30T23:00:00Z"
        base = datetime(2025, 9, 30, 4, tzinfo=timezone.utc)
        points = [(base + optimizer.timedelta(hours=i), v) for i, v in enumerate([80, 82, 85, 90, 95, 100, 110, 120, 130, 140, 160, 180, 200, 220, 240, 260])]
        status = {"state": "running", "required_work": "1000", "completed_work": "0.000000", "work_unit": "vcpu_hour", "assignments": [{"state": "running", "vm_id": "vm1"}]}
        self.assertIsNone(optimizer.carbon_pause_action(status, task, groups["w-01-dach-research"], points, base + optimizer.timedelta(hours=15)))

    def test_paused_work_resumes_when_forecast_is_stale(self):
        _, _, workloads, groups, _ = optimizer.validate_plan(SCRIPT.parents[1] / "forecast-workload-plan.json")
        task = workloads["w-03-med-analysis"]
        base = datetime(2025, 10, 2, 3, tzinfo=timezone.utc)
        points = [(base + optimizer.timedelta(hours=i), 200.0) for i in range(24)]
        status = {"state": "running", "required_work": "1600", "completed_work": "900", "work_unit": "vcpu_hour", "assignments": [{"state": "stopped", "vm_id": "vm1"}]}
        later = base + optimizer.timedelta(hours=30)
        self.assertEqual(optimizer.carbon_pause_action(status, task, groups["w-03-med-analysis"], points, later), "resume")

    def test_paused_work_resumes_near_deadline_even_at_peak(self):
        _, _, workloads, groups, _ = optimizer.validate_plan(SCRIPT.parents[1] / "forecast-workload-plan.json")
        task = dict(workloads["w-03-med-analysis"])
        task["deadline_at"] = "2025-10-02T12:00:00Z"
        base = datetime(2025, 10, 2, 3, tzinfo=timezone.utc)
        points = [(base + optimizer.timedelta(hours=i), v) for i, v in enumerate([400] + [100] * 23)]
        status = {"state": "paused", "required_work": "1600", "completed_work": "1500", "work_unit": "vcpu_hour", "assignments": [{"state": "stopped", "vm_id": "vm1"}]}
        self.assertEqual(optimizer.carbon_pause_action(status, task, groups["w-03-med-analysis"], points, base), "resume")

    def test_upsize_never_exceeds_vcpu_quota(self):
        _, catalog, workloads, groups, _ = optimizer.validate_plan(SCRIPT.parents[1] / "forecast-workload-plan.json")
        wid = "w-15-heavy-archive"
        sub = {"placements": [dict(p, zone="at-vie-2") for p, _ in groups[wid]]}
        full = optimizer.upsize_subplan(wid, sub, workloads, dict(groups), catalog, {"instances": []}, set(), set(), 320)
        self.assertEqual(full["placements"][0]["size"], "mega")
        others = set(groups) - {wid}
        freed = optimizer.upsize_subplan(wid, sub, workloads, dict(groups), catalog, {"instances": []}, set(), others, 320)
        self.assertEqual(freed["placements"][0]["size"], "mega")

    def test_delayed_w04_can_upsize_with_three_early_allocations(self):
        _, catalog, workloads, groups, _ = optimizer.validate_plan(SCRIPT.parents[1] / "forecast-workload-plan.json")
        wid = "w-04-dach-batch"
        sub = {"placements": [dict(p, zone="ch-dk-2") for p, _ in groups[wid]]}
        state = {"instances": [
            {"name": "w-01-dach-research-cpu-huge-01"},
            {"name": "w-02-ch-reporting-cpu-huge-01"},
            {"name": "w-08-ch-imaging-gpua30-small-01"},
        ]}
        launched = {"w-01-dach-research", "w-02-ch-reporting", "w-08-ch-imaging"}
        result = optimizer.upsize_subplan(wid, sub, workloads, dict(groups), catalog, state, launched, set(), 320)
        self.assertEqual(result["placements"][0]["size"], "mega")


    def test_late_job_is_immediate_not_fatal(self):
        _, _, workloads, groups, _ = optimizer.validate_plan(
            SCRIPT.parents[1] / "forecast-workload-plan.json"
        )
        wid = "w-04-dach-batch"
        task = workloads[wid]
        zones = {z["slug"]: z for z in optimizer.load_public_data()[0]["zones"]}
        candidates = optimizer.legal_zone_candidates(task, groups[wid], zones)
        now = optimizer.parse_time("2025-09-30T22:50:00Z")
        # Baseline huge is slightly too slow now, but the scheduler must not abort.
        pick = optimizer.choose_site_and_time(task, groups[wid], candidates, {}, now, 12)
        self.assertEqual(pick["start_at"], now)
        self.assertTrue(pick["zone"]["slug"] in task["_eligible_zones"])

    def test_carbon_control_is_opt_in_by_default(self):
        import argparse
        import inspect
        source = inspect.getsource(optimizer)
        self.assertIn('"--carbon-control", action=argparse.BooleanOptionalAction, default=False', source)

    def test_residency_candidates_exclude_switzerland_for_eu(self):
        _, _, workloads, groups, _ = optimizer.validate_plan(
            SCRIPT.parents[1] / "forecast-workload-plan.json"
        )
        zones = {z["slug"]: z for z in optimizer.load_public_data()[0]["zones"]}
        candidates = optimizer.legal_zone_candidates(workloads["w-03-med-analysis"], groups["w-03-med-analysis"], zones)
        self.assertTrue(candidates)
        self.assertTrue(all(z["country"] in {"ES", "IT"} for z in candidates))

    def test_energy_estimator_prefers_lower_forecast_emissions(self):
        _, _, workloads, groups, _ = optimizer.validate_plan(
            SCRIPT.parents[1] / "forecast-workload-plan.json"
        )
        task = workloads["w-01-dach-research"]
        workers = groups["w-01-dach-research"]
        zone = {"slug": "de-fra-1", "electricity_area": "DE", "pue": "1.20"}
        now = datetime(2025, 9, 30, 4, tzinfo=timezone.utc)
        pts_low = [(now + optimizer.timedelta(hours=i), 80.0) for i in range(24)]
        pts_high = [(now + optimizer.timedelta(hours=i), 300.0) for i in range(24)]
        low = optimizer.estimate_full_job_emissions(now, pts_low, task, workers, float(zone["pue"]))
        high = optimizer.estimate_full_job_emissions(now, pts_high, task, workers, float(zone["pue"]))
        self.assertGreater(high["gco2e"], low["gco2e"])
        self.assertGreater(low["estimated_hours"], 6.0)
        self.assertGreater(low["extrapolated_hours"], 0.0)
        self.assertLess(low["extrapolated_hours"], low["estimated_hours"])
        self.assertAlmostEqual(low["extrapolated_hours"], low["estimated_hours"] - low["covered_hours"], places=6)


if __name__ == "__main__":
    unittest.main()
