import inspect
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from skills.sequence_skill import SequenceSkill
from tools.app_control_tool import wait


class WaitToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_wait_tool_sleeps_and_returns_success(self) -> None:
        with patch("tools.app_control_tool.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            payload = json.loads(await wait(seconds=1.5))
        sleep_mock.assert_awaited_once_with(1.5)
        self.assertTrue(payload["success"])
        self.assertIn("1.5", payload["message"])

    async def test_wait_tool_rejects_negative_seconds(self) -> None:
        payload = json.loads(await wait(seconds=-1))
        self.assertFalse(payload["success"])

    def test_wait_is_async_tool(self) -> None:
        self.assertTrue(inspect.iscoroutinefunction(wait))

    async def test_sequence_skill_executes_wait_step(self) -> None:
        skill = SequenceSkill.__new__(SequenceSkill)
        skill.skill_name = "test_skill"
        skill.steps = [{"tool": "wait", "args": {"seconds": 0.25}}]
        skill.description = ""
        skill.instruction = ""

        mock_wait = AsyncMock(
            return_value=json.dumps({"success": True, "message": "0.25초 대기 완료"})
        )
        with patch("skills.sequence_skill.get_skill_tool_registry", return_value={"wait": mock_wait}):
            result = await skill.execute()
        mock_wait.assert_awaited_once_with(seconds=0.25)
        self.assertTrue(result["success"])
        self.assertEqual(result["steps"][0]["tool"], "wait")
        self.assertTrue(result["steps"][0]["result"]["success"])


if __name__ == "__main__":
    unittest.main()
