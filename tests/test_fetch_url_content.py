import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from skills.sequence_skill import SequenceSkill
from tools.browser_tool import fetch_url_content


class FetchUrlViaBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_url_content_returns_success_json(self) -> None:
        with patch(
            "tools.browser_tool.fetch_url_via_browser",
            new=AsyncMock(return_value="page body"),
        ):
            raw = await fetch_url_content("https://example.com")

        payload = json.loads(raw)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["text"], "page body")

    async def test_fetch_url_content_requires_url(self) -> None:
        raw = await fetch_url_content("")
        payload = json.loads(raw)
        self.assertFalse(payload["success"])

    async def test_fetch_url_content_propagates_playwright_error(self) -> None:
        with patch(
            "tools.browser_tool.fetch_url_via_browser",
            new=AsyncMock(return_value="[오류] URL 수집 실패: timeout"),
        ):
            raw = await fetch_url_content("https://example.com")

        payload = json.loads(raw)
        self.assertFalse(payload["success"])
        self.assertIn("오류", payload["message"])


class FetchUrlInfoSkillTest(unittest.TestCase):
    def test_skill_uses_single_fetch_url_content_step(self) -> None:
        skill = SequenceSkill(skill_name="fetch_url_info")
        self.assertEqual(len(skill.steps), 1)
        self.assertEqual(skill.steps[0]["tool"], "fetch_url_content")


if __name__ == "__main__":
    unittest.main()
