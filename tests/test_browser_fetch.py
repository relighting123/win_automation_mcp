import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.browser_fetch import (
    fetch_url_via_browser,
    resolve_browser_profile_dir,
    resolve_headless,
    snapshot_to_text,
)


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

    def test_resolve_browser_profile_dir_default(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            profile = resolve_browser_profile_dir()
        self.assertTrue(str(profile).endswith(".chatrtd/browser-profile"))

    def test_resolve_headless_defaults_false(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            self.assertFalse(resolve_headless())


class FetchUrlViaBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_url_via_browser_uses_playwright(self) -> None:
        page = AsyncMock()
        page.inner_text = AsyncMock(return_value="Hello page")
        page.title = AsyncMock(return_value="Example")
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()

        context = AsyncMock()
        context.pages = [page]
        context.new_page = AsyncMock(return_value=page)
        context.close = AsyncMock()

        chromium = MagicMock()
        chromium.launch_persistent_context = AsyncMock(return_value=context)

        playwright = MagicMock()
        playwright.chromium = chromium
        playwright.__aenter__ = AsyncMock(return_value=playwright)
        playwright.__aexit__ = AsyncMock(return_value=None)

        with patch("playwright.async_api.async_playwright", return_value=playwright):
            text = await fetch_url_via_browser("https://example.com")

        self.assertEqual(text, "Hello page")
        page.goto.assert_awaited_once()

    async def test_fetch_url_reports_missing_playwright(self) -> None:
        with patch.dict(sys.modules, {"playwright": None, "playwright.async_api": None}):
            text = await fetch_url_via_browser("https://example.com")

        self.assertIn("Playwright 미설치", text)


if __name__ == "__main__":
    unittest.main()
