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


class SequenceSkillBrowserStepTest(unittest.IsolatedAsyncioTestCase):
    def _browser_skill(self) -> SequenceSkill:
        skill = SequenceSkill.__new__(SequenceSkill)
        skill.skill_name = "fetch_url_info"
        skill.steps = [
            {"tool": "openchrome/navigate", "args": {"url": {"mode": "ai"}}},
            {"tool": "openchrome/read_page", "args": {"mode": {"mode": "fixed", "value": "markdown"}}},
        ]
        skill.description = ""
        skill.instruction = ""
        return skill

    def test_missing_required_url_raises_clear_error(self) -> None:
        skill = self._browser_skill()
        with self.assertRaisesRegex(ValueError, "필수 인자가 없습니다: url"):
            skill._validate_parsed_step(
                skill.steps[0],
                {"tool": "openchrome/navigate", "args": {"url": None}},
            )

    async def test_browser_step_retries_after_transient_error(self) -> None:
        skill = self._browser_skill()
        hub = AsyncMock()
        hub.call_tool = AsyncMock(
            side_effect=[
                {
                    "isError": True,
                    "content": [{"type": "text", "text": "navigation timeout"}],
                },
                {"content": [{"type": "text", "text": "Navigated to https://example.com"}]},
            ]
        )

        _raw, normalized = await skill._call_extra_hub_tool(
            hub,
            "openchrome/navigate",
            {"url": "https://example.com"},
            max_attempts=2,
        )

        self.assertNotEqual(normalized.get("success"), False)
        self.assertEqual(hub.call_tool.await_count, 2)


if __name__ == "__main__":
    unittest.main()
