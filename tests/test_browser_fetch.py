import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.browser_fetch import (
    _enrich_chrome_missing_message,
    extract_browser_tool_text,
    snapshot_to_text,
)
from core.mcp_server_config import load_mcp_servers


class BrowserFetchTextTest(unittest.TestCase):
    def test_snapshot_to_text_extracts_names(self) -> None:
        snapshot = """
- role: heading
  name: Welcome
- role: button
  name: Login
"""
        text = snapshot_to_text(snapshot)
        self.assertIn("Welcome", text)
        self.assertIn("Login", text)

    def test_extract_browser_tool_text_reads_markdown_json(self) -> None:
        result = {
            "content": [
                {
                    "type": "text",
                    "text": '{"content": "# Title\\nBody text"}',
                }
            ]
        }
        text = extract_browser_tool_text(result)
        self.assertIn("Body text", text)

    def test_extract_browser_tool_text_handles_is_error(self) -> None:
        result = {
            "isError": True,
            "content": [{"type": "text", "text": "navigation failed"}],
        }
        text = extract_browser_tool_text(result)
        self.assertIn("navigation failed", text)

    def test_enrich_chrome_missing_message(self) -> None:
        message = _enrich_chrome_missing_message("[navigate 오류] Chrome executable not found")
        self.assertIn("Chrome", message)
        self.assertIn("CHROME_PATH", message)


class OpenChromeServerConfigTest(unittest.TestCase):
    def test_openchrome_env_server(self) -> None:
        with patch.dict(
            "os.environ",
            {"MCP_OPENCHROME_ENABLED": "true"},
            clear=False,
        ):
            servers = load_mcp_servers(base_url_override="http://localhost:8000/mcp")
        ids = [server.id for server in servers]
        self.assertIn("openchrome", ids)

    def test_legacy_browser_env_does_not_register_browsermcp(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MCP_BROWSER_MCP_ENABLED": "true",
                "MCP_OPENCHROME_ENABLED": "",
            },
            clear=False,
        ):
            servers = load_mcp_servers(base_url_override="http://localhost:8000/mcp")
        ids = [server.id for server in servers]
        self.assertNotIn("browsermcp", ids)


class FetchUrlViaBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_url_via_browser_calls_openchrome_tools(self) -> None:
        from core.browser_fetch import fetch_url_via_browser

        hub = AsyncMock()
        hub.has_tool = lambda name: name == "openchrome/navigate"
        hub.call_tool = AsyncMock(
            side_effect=[
                {"content": [{"type": "text", "text": "Navigated"}]},
                {"content": [{"type": "text", "text": '{"content": "Hello page"}'}]},
            ]
        )

        with patch("core.mcp_client.get_shared_extra_mcp_hub", new=AsyncMock(return_value=hub)):
            with patch("core.browser_fetch.find_chrome_binary", return_value=r"C:\Chrome\chrome.exe"):
                text = await fetch_url_via_browser("https://example.com")

        self.assertIn("Hello page", text)
        hub.call_tool.assert_any_await("openchrome/navigate", {"url": "https://example.com"})
        hub.call_tool.assert_any_await(
            "openchrome/read_page",
            {"mode": "markdown", "onlyMainContent": True},
        )


if __name__ == "__main__":
    unittest.main()
