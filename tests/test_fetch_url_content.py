import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.browser_fetch import (
    extract_browser_tool_text,
    extract_openchrome_tab_id,
    fetch_url_via_browser,
    _openchrome_remediation,
)
from core.mcp_result_utils import normalize_mcp_tool_result
from skills.sequence_skill import SequenceSkill
from tools.browser_tool import fetch_url_content


class NormalizeErrorTextTest(unittest.TestCase):
    def test_error_prefix_text_is_failure(self) -> None:
        normalized = normalize_mcp_tool_result(
            {"content": [{"type": "text", "text": "Error: url is required"}]}
        )
        self.assertFalse(normalized.get("success", True))

    def test_extract_browser_tool_text_includes_message(self) -> None:
        text = extract_browser_tool_text(
            {"isError": True, "content": [{"type": "text", "text": "navigation failed"}]}
        )
        self.assertIn("navigation failed", text)

    def test_openchrome_remediation_for_owner_conflict(self) -> None:
        hint = _openchrome_remediation("pid 12345 already owns Chrome on port 9222")
        self.assertIn("chatRTD", hint)
        self.assertIn("locks", hint)


class ExtractTabIdTest(unittest.TestCase):
    def test_extract_openchrome_tab_id_from_json(self) -> None:
        result = {
            "content": [
                {
                    "type": "text",
                    "text": '{"action":"navigate","tabId":"tab_123","url":"https://example.com"}',
                }
            ]
        }
        self.assertEqual(extract_openchrome_tab_id(result), "tab_123")


class FetchUrlViaBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_url_uses_tab_id_and_wait_for(self) -> None:
        hub = AsyncMock()
        hub.has_tool = lambda name: name in {
            "openchrome/navigate",
            "openchrome/wait_for",
            "openchrome/read_page",
        }
        hub.call_tool = AsyncMock(
            side_effect=[
                {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"action":"navigate","tabId":"tab_9","url":"https://example.com"}',
                        }
                    ]
                },
                {"content": [{"type": "text", "text": "ready"}]},
                {"content": [{"type": "text", "text": '{"content": "Hello page"}'}]},
            ]
        )

        with patch("core.mcp_client.get_shared_extra_mcp_hub", new=AsyncMock(return_value=hub)):
            with patch("core.browser_fetch.asyncio.sleep", new=AsyncMock()):
                text = await fetch_url_via_browser("https://example.com")

        self.assertIn("Hello page", text)
        hub.call_tool.assert_any_await(
            "openchrome/wait_for",
            {"tabId": "tab_9", "type": "navigation", "timeout": 30000},
        )
        hub.call_tool.assert_any_await(
            "openchrome/read_page",
            {"mode": "markdown", "onlyMainContent": True, "tabId": "tab_9"},
        )

    async def test_fetch_url_retries_after_stale_session_error(self) -> None:
        hub = AsyncMock()
        hub.has_tool = lambda name: name == "openchrome/navigate"
        hub.call_tool = AsyncMock(
            side_effect=[
                {"error": "Connection closed / broken pipe"},
                {"content": [{"type": "text", "text": "Navigated"}]},
                {"content": [{"type": "text", "text": '{"content": "Recovered"}'}]},
            ]
        )
        reset_mock = AsyncMock()

        with patch("core.mcp_client.get_shared_extra_mcp_hub", new=AsyncMock(return_value=hub)):
            with patch("core.mcp_client.reset_shared_extra_mcp_hub", new=reset_mock):
                with patch("core.browser_fetch.asyncio.sleep", new=AsyncMock()):
                    text = await fetch_url_via_browser("https://example.com")

        self.assertIn("Recovered", text)
        reset_mock.assert_awaited_once()


class FetchUrlContentToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_url_content_returns_success_json(self) -> None:
        with patch(
            "tools.browser_tool.fetch_url_via_browser",
            new=AsyncMock(return_value="page body"),
        ):
            raw = await fetch_url_content("https://example.com")

        import json

        payload = json.loads(raw)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["text"], "page body")

    async def test_fetch_url_content_requires_url(self) -> None:
        import json

        raw = await fetch_url_content("")
        payload = json.loads(raw)
        self.assertFalse(payload["success"])


class FetchUrlInfoSkillTest(unittest.TestCase):
    def test_skill_uses_single_fetch_url_content_step(self) -> None:
        skill = SequenceSkill(skill_name="fetch_url_info")
        self.assertEqual(len(skill.steps), 1)
        self.assertEqual(skill.steps[0]["tool"], "fetch_url_content")


if __name__ == "__main__":
    unittest.main()
