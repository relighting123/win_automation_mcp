import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tools import url_fetch_tool as _tool


class FetchUrlToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_url_returns_text_body(self) -> None:
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200
        mock_response.url = "https://example.com/"
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_response.text = "<html>hello</html>"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(_tool.httpx, "AsyncClient", return_value=mock_client):
            raw = await _tool.fetch_url(url="https://example.com/")

        payload = json.loads(raw)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["text"], "<html>hello</html>")

    async def test_fetch_url_requires_url(self) -> None:
        raw = await _tool.fetch_url(url="")
        payload = json.loads(raw)
        self.assertFalse(payload["success"])


if __name__ == "__main__":
    unittest.main()
