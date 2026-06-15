import json
import sys
import time as time_lib
import unittest
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from skills.sequence_skill import SequenceSkill
from tools.app_control_tool import wait


class WaitToolTest(unittest.TestCase):
    def test_wait_tool_blocks_for_requested_seconds(self) -> None:
        started = time_lib.monotonic()
        payload = json.loads(wait(seconds=0.15))
        elapsed = time_lib.monotonic() - started
        self.assertTrue(payload["success"])
        self.assertGreaterEqual(elapsed, 0.14)
        self.assertGreaterEqual(payload["elapsed"], 0.14)

    def test_wait_tool_accepts_string_seconds(self) -> None:
        with patch("tools.app_control_tool.time_lib.sleep") as sleep_mock:
            payload = json.loads(wait(seconds="2"))
        sleep_mock.assert_called_once_with(2.0)
        self.assertTrue(payload["success"])

    def test_wait_tool_accepts_duration_alias(self) -> None:
        with patch("tools.app_control_tool.time_lib.sleep") as sleep_mock:
            payload = json.loads(wait(duration=1.5))
        sleep_mock.assert_called_once_with(1.5)
        self.assertTrue(payload["success"])

    def test_wait_tool_defaults_to_one_second(self) -> None:
        with patch("tools.app_control_tool.time_lib.sleep") as sleep_mock:
            payload = json.loads(wait())
        sleep_mock.assert_called_once_with(1.0)
        self.assertTrue(payload["success"])

    def test_wait_tool_rejects_invalid_seconds(self) -> None:
        payload = json.loads(wait(seconds="bad"))
        self.assertFalse(payload["success"])


class WaitToolAsyncSequenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_sequence_skill_executes_wait_step(self) -> None:
        skill = SequenceSkill.__new__(SequenceSkill)
        skill.skill_name = "test_skill"
        skill.steps = [{"tool": "wait", "args": {"seconds": 0.05}}]
        skill.description = ""
        skill.instruction = ""

        with patch("tools.app_control_tool.time_lib.sleep") as sleep_mock:
            with patch("skills.sequence_skill.get_skill_tool_registry", return_value={"wait": wait}):
                result = await skill.execute()
        sleep_mock.assert_called_once_with(0.05)
        self.assertTrue(result["success"])
        self.assertEqual(result["steps"][0]["tool"], "wait")
        self.assertTrue(result["steps"][0]["result"]["success"])


if __name__ == "__main__":
    unittest.main()
