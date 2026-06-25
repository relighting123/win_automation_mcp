import unittest
from unittest.mock import MagicMock, patch

from core.mcp_probe import normalize_mcp_url, parse_mcp_endpoint, probe_mcp_http


class MCPProbeTest(unittest.TestCase):
    def test_normalize_mcp_url_appends_mcp_path(self) -> None:
        self.assertEqual(
            normalize_mcp_url("http://localhost:8000"),
            "http://localhost:8000/mcp",
        )

    def test_parse_mcp_endpoint(self) -> None:
        host, port, path = parse_mcp_endpoint("http://127.0.0.1:9001/custom/mcp")
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 9001)
        self.assertEqual(path, "/custom/mcp")

    def test_probe_mcp_http_requires_initialize_success(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.headers = {"mcp-session-id": "abc"}
        with patch("core.mcp_probe.requests.post", return_value=response):
            self.assertTrue(probe_mcp_http("http://localhost:8000/mcp"))

    def test_probe_mcp_http_rejects_404(self) -> None:
        response = MagicMock()
        response.status_code = 404
        response.text = '{"detail":"Not Found"}'
        response.headers = {}
        with patch("core.mcp_probe.requests.post", return_value=response):
            self.assertFalse(probe_mcp_http("http://localhost:8000/mcp"))


if __name__ == "__main__":
    unittest.main()
