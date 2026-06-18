import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.mcp_result_utils import normalize_mcp_tool_result
from skills.sequence_skill import SequenceSkill


class NormalizeMcpToolResultTest(unittest.TestCase):
    def test_is_error_with_text_is_failure(self) -> None:
        normalized = normalize_mcp_tool_result(
            {
                "isError": True,
                "content": [{"type": "text", "text": "navigation failed"}],
            }
        )
        self.assertFalse(normalized.get("success", True))
        self.assertIn("navigation failed", normalized["message"])

    def test_success_text_response(self) -> None:
        normalized = normalize_mcp_tool_result(
            {"content": [{"type": "text", "text": "Navigated to https://example.com"}]}
        )
        self.assertEqual(normalized.get("text"), "Navigated to https://example.com")


class SequenceSkillExtraHubTest(unittest.IsolatedAsyncioTestCase):
    def _skill_with_extra_tool(self) -> SequenceSkill:
        skill = SequenceSkill.__new__(SequenceSkill)
        skill.skill_name = "demo"
        skill.steps = [{"tool": "extra/ping", "args": {}}]
        skill.description = ""
        skill.instruction = ""
        return skill

    async def test_extra_hub_tool_single_call(self) -> None:
        skill = self._skill_with_extra_tool()
        hub = AsyncMock()
        hub.call_tool = AsyncMock(
            return_value={"content": [{"type": "text", "text": "pong"}]},
        )

        _raw, normalized = await skill._call_extra_hub_tool(hub, "extra/ping", {})

        self.assertEqual(hub.call_tool.await_count, 1)
        self.assertEqual(normalized.get("text"), "pong")


if __name__ == "__main__":
    unittest.main()
