import os
import unittest
from unittest.mock import patch

from core.timing_log import log_timing, timing_enabled


class TimingLogTest(unittest.TestCase):
    def test_timing_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {"MCP_REQUEST_TIMING": ""}, clear=False):
            self.assertFalse(timing_enabled())

    def test_timing_enabled_from_env(self) -> None:
        with patch.dict(os.environ, {"MCP_REQUEST_TIMING": "true"}, clear=False):
            self.assertTrue(timing_enabled())

    def test_log_timing_noop_when_disabled(self) -> None:
        with patch.dict(os.environ, {"MCP_REQUEST_TIMING": ""}, clear=False):
            with log_timing("test.scope"):
                pass


if __name__ == "__main__":
    unittest.main()
