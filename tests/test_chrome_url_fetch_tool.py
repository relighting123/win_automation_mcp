import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from tools import chrome_url_fetch_tool as _tool


def _build_playwright_mocks(*, page_url: str, page_title: str, body_text: str):
    mock_page = AsyncMock()
    mock_page.url = page_url
    mock_page.title = AsyncMock(return_value=page_title)
    mock_page.inner_text = AsyncMock(return_value=body_text)
    mock_page.content = AsyncMock(return_value=f"<html>{body_text}</html>")
    mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
    mock_page.wait_for_timeout = AsyncMock()

    mock_context = AsyncMock()
    mock_context.pages = [mock_page]
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_chromium = MagicMock()
    mock_chromium.launch_persistent_context = AsyncMock(return_value=mock_context)

    mock_playwright = MagicMock()
    mock_playwright.chromium = mock_chromium
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock(return_value=False)

    return mock_playwright, mock_context


class FetchUrlChromeToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_url_chrome_returns_text_body(self) -> None:
        mock_playwright, mock_context = _build_playwright_mocks(
            page_url="https://example.com/dashboard",
            page_title="Dashboard",
            body_text="hello from chrome",
        )

        with patch.object(_tool, "async_playwright", MagicMock(return_value=mock_playwright)), patch.object(
            _tool, "_resolve_profile_dir", return_value=Path("/tmp/chrome-test")
        ):
            raw = await _tool.fetch_url_chrome(url="https://example.com/")

        payload = json.loads(raw)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["text"], "hello from chrome")
        self.assertEqual(payload["status_code"], 200)
        self.assertFalse(payload["login_like"])
        mock_context.close.assert_awaited_once()

    async def test_fetch_url_chrome_detects_login_page(self) -> None:
        mock_playwright, _mock_context = _build_playwright_mocks(
            page_url="https://login.microsoftonline.com/common/oauth2/authorize",
            page_title="Sign in to your account",
            body_text="Sign in",
        )

        with patch.object(_tool, "async_playwright", MagicMock(return_value=mock_playwright)), patch.object(
            _tool, "_resolve_profile_dir", return_value=Path("/tmp/chrome-test")
        ):
            raw = await _tool.fetch_url_chrome(url="https://internal.example.com/")

        payload = json.loads(raw)
        self.assertFalse(payload["success"])
        self.assertTrue(payload["login_like"])

    async def test_fetch_url_chrome_requires_url(self) -> None:
        raw = await _tool.fetch_url_chrome(url="")
        payload = json.loads(raw)
        self.assertFalse(payload["success"])

    async def test_fetch_url_chrome_without_playwright(self) -> None:
        with patch.object(_tool, "async_playwright", None):
            raw = await _tool.fetch_url_chrome(url="https://example.com/")

        payload = json.loads(raw)
        self.assertFalse(payload["success"])
        self.assertIn("playwright", payload["message"])


if __name__ == "__main__":
    unittest.main()
