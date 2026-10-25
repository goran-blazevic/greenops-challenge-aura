import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples" / "python"))

# CloudEnv only needs static helpers during API calls. Keep this connection-pool
# unit test independent of the optional Exoscale SDK.
static_stub = types.ModuleType("static")
static_stub.check_endpoint = lambda value, reference=None: value
static_stub.client = lambda *args, **kwargs: None
static_stub.discover = lambda *args, **kwargs: {}
static_stub.save = lambda *args, **kwargs: None
sys.modules["static"] = static_stub

from orchestrator.cloud import CloudEnv  # noqa: E402


class HttpSessionTests(unittest.TestCase):
    def test_grid_reuses_one_session_per_area_and_closes_it(self):
        env = CloudEnv(
            {"endpoint": "https://example.test/runs/test/cloud/v2"},
            "https://example.test/runs/test/grid/v4",
            "test-secret",
        )
        first = env._grid_session("DE")
        self.assertIs(first, env._grid_session("DE"))
        self.assertIsNot(first, env._grid_session("FR"))
        env.close()
        self.assertEqual(env._grid_sessions, {})
