import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core import api_config
from tools import api_call_tool


class ApiConfigTest(unittest.TestCase):
    def test_host_pattern_supports_wildcard(self) -> None:
        with patch.object(
            api_config,
            "get_api_access_settings",
            return_value={
                "enabled": True,
                "allowed_hosts": ["*.example.com"],
                "allowed_methods": ["GET"],
                "profiles": {},
                "default_timeout": 30,
                "max_response_chars": 1000,
            },
        ):
            self.assertTrue(api_config.is_host_allowed("api.example.com"))
            self.assertFalse(api_config.is_host_allowed("example.org"))

    def test_build_request_target_rejects_disabled_access(self) -> None:
        with patch.object(
            api_config,
            "get_api_access_settings",
            return_value={
                "enabled": False,
                "allowed_hosts": ["api.example.com"],
                "allowed_methods": ["GET"],
                "profiles": {},
                "default_timeout": 30,
                "max_response_chars": 1000,
            },
        ):
            _, _, err = api_config.build_request_target("https://api.example.com/data")
            self.assertIsNotNone(err)
            self.assertIn("enabled", err or "")

    def test_build_request_target_uses_profile_base_url(self) -> None:
        with patch.object(
            api_config,
            "get_api_access_settings",
            return_value={
                "enabled": True,
                "allowed_hosts": ["api.example.com"],
                "allowed_methods": ["GET"],
                "profiles": {
                    "demo": {
                        "alias": "demo",
                        "base_url": "https://api.example.com/v1/",
                        "headers": {"Authorization": "Bearer token"},
                    }
                },
                "default_timeout": 30,
                "max_response_chars": 1000,
            },
        ), patch.object(
            api_config,
            "get_api_profile",
            return_value={
                "alias": "demo",
                "base_url": "https://api.example.com/v1/",
                "headers": {"Authorization": "Bearer token"},
            },
        ):
            final_url, headers, err = api_config.build_request_target(
                "/users",
                api_alias="demo",
            )
            self.assertIsNone(err)
            self.assertEqual(final_url, "https://api.example.com/v1/users")
            self.assertEqual(headers["Authorization"], "Bearer token")


class HttpRequestToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_http_request_success_json(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.headers = {"content-type": "application/json"}
        response.content = b'{"ok": true}'

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(
            api_call_tool,
            "build_request_target",
            return_value=("https://api.example.com/data", {}, None),
        ), patch.object(
            api_call_tool,
            "get_api_access_settings",
            return_value={"default_timeout": 30, "max_response_chars": 1000},
        ), patch("tools.api_call_tool.httpx.AsyncClient", return_value=mock_client):
            raw = await api_call_tool.http_request("https://api.example.com/data")

        payload = json.loads(raw)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["body"], {"ok": True})

    async def test_http_request_returns_policy_error(self) -> None:
        with patch.object(
            api_call_tool,
            "build_request_target",
            return_value=("", {}, "허용되지 않은 호스트입니다"),
        ):
            raw = await api_call_tool.http_request("https://blocked.example.com")

        payload = json.loads(raw)
        self.assertFalse(payload["success"])
        self.assertIn("호스트", payload["message"])


if __name__ == "__main__":
    unittest.main()
