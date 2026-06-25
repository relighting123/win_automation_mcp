import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.mcp_hub import MultiMCPClient, _build_stdio_subprocess_env, _openai_tool_name, _split_tool_name
from core.mcp_server_config import MCPServerConfig, load_mcp_servers


class MCPServerConfigTest(unittest.TestCase):
    def test_load_mcp_servers_includes_primary_http(self) -> None:
        servers = load_mcp_servers(base_url_override="http://localhost:9000/mcp")
        self.assertEqual(servers[0].id, "automation")
        self.assertEqual(servers[0].url, "http://localhost:9000/mcp")

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
                MCPServerConfig(id="automation", transport="http", url="http://localhost:8001/mcp", tool_prefix=False),
                MCPServerConfig(id="extra", transport="stdio", command="npx", args=[], tool_prefix=True),
            ]
        )
        hub._backends = {"automation": automation, "extra": extra}

        await hub.list_tools()
        names = [tool["name"] for tool in await hub.list_tools()]
        self.assertIn("extra/navigate", names)

        result = await hub.call_tool("extra/navigate", {"url": "https://example.com"})
        extra.call_tool.assert_awaited_with("navigate", {"url": "https://example.com"})
        self.assertIn("content", result)

    async def test_has_tool_for_prefixed_name_before_list_tools(self) -> None:
        hub = MultiMCPClient(
            [MCPServerConfig(id="extra", transport="stdio", command="npx", args=[])]
        )
        self.assertTrue(hub.has_tool("extra/navigate"))

    def test_name_helpers(self) -> None:
        self.assertEqual(
            _openai_tool_name("extra", "navigate", use_prefix=True),
            "extra/navigate",
        )
        self.assertEqual(_split_tool_name("extra/read_page"), ("extra", "read_page"))


if __name__ == "__main__":
    unittest.main()
