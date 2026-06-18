import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.browser_mcp_connect import (
    ensure_browser_mcp_connected,
    is_browser_mcp_connection_error,
    open_browser_mcp_connect_popup,
)


class BrowserMcpConnectionErrorTest(unittest.TestCase):
    def test_detects_official_no_connection_message(self) -> None:
        text = (
            "No connection to browser extension. In order to proceed, you must first "
            "connect a tab by clicking the Browser MCP extension icon and clicking the "
            "'Connect' button."
        )
        self.assertTrue(is_browser_mcp_connection_error(text))


class EnsureBrowserMcpConnectedTest(unittest.IsolatedAsyncioTestCase):
    async def test_returns_true_when_already_connected(self) -> None:
        hub = AsyncMock()
        hub.call_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "page"}]})

        ok, message = await ensure_browser_mcp_connected(
            hub,
            wait_seconds=0,
            open_popup=False,
        )
        self.assertTrue(ok)
        self.assertIn("이미 연결", message)

    async def test_waits_and_succeeds_after_connect(self) -> None:
        hub = AsyncMock()
        hub.call_tool = AsyncMock(
            side_effect=[
                {"isError": True, "content": [{"type": "text", "text": "No connection to browser extension"}]},
                {"content": [{"type": "text", "text": "page"}]},
            ]
        )

        with patch("core.browser_mcp_connect.open_browser_mcp_connect_popup", return_value=True):
            ok, message = await ensure_browser_mcp_connected(
                hub,
                wait_seconds=1,
                open_popup=True,
            )

        self.assertTrue(ok)
        self.assertIn("연결 완료", message)

    async def test_returns_helpful_message_when_still_disconnected(self) -> None:
        hub = AsyncMock()
        hub.call_tool = AsyncMock(
            return_value={"isError": True, "content": [{"type": "text", "text": "No connection to browser extension"}]}
        )

        with patch("core.browser_mcp_connect.open_browser_mcp_connect_popup", return_value=True):
            ok, message = await ensure_browser_mcp_connected(
                hub,
                wait_seconds=0.6,
                open_popup=True,
            )

        self.assertFalse(ok)
        self.assertIn("Connect", message)


class OpenBrowserMcpPopupTest(unittest.TestCase):
    def test_open_popup_uses_chrome_executable_when_available(self) -> None:
        with patch("core.browser_mcp_connect._chrome_executable_candidates", return_value=[r"C:\Chrome\chrome.exe"]):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("subprocess.Popen") as mock_popen:
                    self.assertTrue(open_browser_mcp_connect_popup())
        mock_popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
