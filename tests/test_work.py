import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples/python"))
import work

class WorkTests(unittest.TestCase):
    def test_scoped_signed_status(self):
        response=Mock(status_code=200)
        response.json.return_value={"state":"RUNNING"}
        with patch.object(work.requests,"get",return_value=response) as get:
            self.assertEqual(work.status({"endpoint":"http://localhost/runs/a/cloud/v2","key":"key","secret":"secret"})["state"],"RUNNING")
            args,kwargs=get.call_args
            self.assertEqual(args[0],"http://localhost/runs/a/work/v1/status")
            self.assertIn("credential=key",kwargs["headers"]["Authorization"])
            self.assertFalse(kwargs["allow_redirects"])
    def test_rate_limit_backoff(self):
        response=Mock(status_code=429,headers={"Retry-After":"2"})
        with patch.object(work.requests,"get",return_value=response),patch.object(work.time,"sleep") as sleep:
            self.assertIsNone(work.status({"endpoint":"http://localhost/runs/a/cloud/v2","key":"key","secret":"secret"}))
            sleep.assert_called_once_with(2)
