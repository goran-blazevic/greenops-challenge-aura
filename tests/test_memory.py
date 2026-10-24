import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orchestrator.memory import RunMemory


class RunMemoryTests(unittest.TestCase):
    def test_learning_uses_only_observed_past_and_adjusts_later_forecasts(self):
        with tempfile.TemporaryDirectory() as td:
            db = RunMemory(Path(td) / "run.sqlite3", "https://example.test/runs/run-a/cloud/v2")
            t0 = datetime(2025, 9, 30, 0, tzinfo=timezone.utc)
            # Four observations from this run, each predicted low and later published high.
            for i in range(4):
                fetched = t0 + timedelta(hours=i)
                valid = fetched + timedelta(hours=6)
                db.record_forecast("DE", fetched, [(valid, 100.0)])
                # Observation is only recorded after that valid hour has passed.
                seen = valid + timedelta(hours=2)
                db.record_history("DE", seen, [(valid, 200.0)])
            factor, n, bucket = db.correction("DE", 6)
            self.assertGreater(n, 0)
            self.assertEqual(bucket, 1)
            self.assertGreater(factor, 1.0)
            now = t0 + timedelta(hours=20)
            raw = [(now + timedelta(hours=6), 100.0)]
            adjusted = db.calibrate("DE", now, raw)
            self.assertGreater(adjusted[0][1], 100.0)
            db.close()

    def test_observations_not_yet_published_are_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            db = RunMemory(Path(td) / "run.sqlite3", "https://example.test/runs/run-a/cloud/v2")
            now = datetime(2025, 9, 30, 5, tzinfo=timezone.utc)
            inserted = db.record_history("DE", now, [(now + timedelta(hours=1), 999.0)])
            self.assertEqual(inserted, 0)
            self.assertEqual(db.stats()["observations"], 0)
            db.close()

    def test_database_refuses_reuse_for_another_run(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "run.sqlite3"
            db = RunMemory(path, "https://example.test/runs/run-a/cloud/v2")
            db.close()
            with self.assertRaisesRegex(ValueError, "another simulation run"):
                RunMemory(path, "https://example.test/runs/run-b/cloud/v2")


    def test_sqlite_enabled_controller_still_completes_all_workloads(self):
        import sys
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(root / "tests"))
        from fake_env import FakeEnv
        from orchestrator.core import Model
        from orchestrator.controller import Controller
        import json
        catalog = json.loads((root / "challenge/catalog.json").read_text())
        workloads = json.loads((root / "challenge/workloads.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            memory = RunMemory(Path(td) / "run.sqlite3", "https://example.test/runs/fake-a/cloud/v2")
            model = Model(catalog, workloads)
            env = FakeEnv(model, workloads, 3)
            ctl = Controller(env, model, memory=memory, log=lambda *_: None)
            ctl.tick()
            for _ in range(120 * 5):
                result = ctl.tick()
                env.advance(720)
                if result == "done":
                    break
            self.assertEqual(env.late(), {})
            self.assertEqual(env.vms, {})
            stats = memory.stats()
            self.assertGreater(stats["status_samples"], 0)
            self.assertGreater(stats["forecast_points"], 0)
            memory.close()

    def test_status_and_events_are_stored_without_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            db = RunMemory(Path(td) / "run.sqlite3", "https://example.test/runs/run-a/cloud/v2")
            db.record_status({"virtual_time":"2025-09-30T00:00:00Z", "state":"RUNNING", "qualification":"QUALIFIED", "workloads":[{"id":"w1", "final_output_delivered":False, "completed_work":"4.000000"}]})
            db.event(datetime(2025,9,30,tzinfo=timezone.utc), "placement", "w1", zone="de-fra-1")
            self.assertEqual(db.stats()["status_samples"], 1)
            self.assertEqual(db.stats()["events"], 1)
            db.close()


if __name__ == "__main__":
    unittest.main()
