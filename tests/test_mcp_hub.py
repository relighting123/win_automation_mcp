import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.browser_fetch import snapshot_to_text
from core.mcp_hub import MultiMCPClient, _build_stdio_subprocess_env, _openai_tool_name, _split_tool_name
from core.mcp_server_config import MCPServerConfig, load_mcp_servers


class MCPServerConfigTest(unittest.TestCase):
    def test_load_mcp_servers_includes_primary_http(self) -> None:
        servers = load_mcp_servers(base_url_override="http://localhost:9000/mcp")
        self.assertEqual(servers[0].id, "automation")
        self.assertEqual(servers[0].url, "http://localhost:9000/mcp")

    def test_legacy_openchrome_env_logs_warning(self) -> None:
        with patch.dict(
            "os.environ",
            {"MCP_OPENCHROME_ENABLED": "true"},
            clear=False,
        ), patch("core.mcp_server_config.logger") as logger:
            servers = load_mcp_servers(base_url_override="http://localhost:8000/mcp")
        ids = [server.id for server in servers]
        self.assertNotIn("openchrome", ids)
        logger.warning.assert_called()

    def test_build_stdio_subprocess_env_merges_config_env(self) -> None:
        env = _build_stdio_subprocess_env(
            MCPServerConfig(
                id="custom",
                transport="stdio",
                command="npx",
                args=["-y", "some-mcp"],
                env={"FOO": "bar"},
            )
        )
        self.assertEqual(env["FOO"], "bar")


class SnapshotTextTest(unittest.TestCase):
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


class MultiMCPClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_routes_prefixed_tool_to_backend(self) -> None:
        automation = AsyncMock()
        automation.list_tools = AsyncMock(return_value=[{"name": "ping", "description": ""}])
        automation.call_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "pong"}]})

        extra = AsyncMock()
        extra.list_tools = AsyncMock(return_value=[{"name": "navigate", "description": ""}])
        extra.call_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})

        hub = MultiMCPClient(
            [
                MCPServerConfig(id="automation", transport="http", url="http://localhost:8000/mcp", tool_prefix=False),
                MCPServerConfig(id="browser", transport="stdio", command="npx", args=[], tool_prefix=True),
            ]
        )
        hub._backends = {"automation": automation, "browser": extra}

        await hub.list_tools()
        names = [tool["name"] for tool in await hub.list_tools()]
        self.assertIn("browser/navigate", names)

        result = await hub.call_tool("browser/navigate", {"url": "https://example.com"})
        extra.call_tool.assert_awaited_with("navigate", {"url": "https://example.com"})
        self.assertIn("content", result)

    async def test_has_tool_for_prefixed_name_before_list_tools(self) -> None:
        hub = MultiMCPClient(
            [MCPServerConfig(id="browser", transport="stdio", command="npx", args=[])]
        )
        self.assertTrue(hub.has_tool("browser/navigate"))

    def test_name_helpers(self) -> None:
        self.assertEqual(
            _openai_tool_name("browser", "navigate", use_prefix=True),
            "browser/navigate",
        )
        self.assertEqual(_split_tool_name("browser/read_page"), ("browser", "read_page"))


if __name__ == "__main__":
    unittest.main()
