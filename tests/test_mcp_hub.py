import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.mcp_hub import MultiMCPClient, _openai_tool_name, _split_tool_name
from core.mcp_server_config import MCPServerConfig, load_mcp_servers


class MCPServerConfigTest(unittest.TestCase):
    def test_load_mcp_servers_includes_primary_http(self) -> None:
        servers = load_mcp_servers(base_url_override="http://localhost:9000/mcp")
        self.assertEqual(servers[0].id, "automation")
        self.assertEqual(servers[0].url, "http://localhost:9000/mcp")

    def test_chrome_devtools_env_server(self) -> None:
        with patch.dict(
            "os.environ",
            {"MCP_CHROME_DEVTOOLS_ENABLED": "true", "MCP_CHROME_DEVTOOLS_AUTO_CONNECT": "true"},
            clear=False,
        ):
            servers = load_mcp_servers(base_url_override="http://localhost:8000/mcp")
        ids = [server.id for server in servers]
        self.assertIn("chrome-devtools", ids)


class MultiMCPClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_routes_prefixed_tool_to_backend(self) -> None:
        automation = MagicMock()
        automation.list_tools = AsyncMock(
            return_value=[{"name": "fetch_url", "description": "http fetch", "inputSchema": {}}]
        )
        automation.call_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})

        chrome = MagicMock()
        chrome.list_tools = AsyncMock(
            return_value=[{"name": "navigate", "description": "go", "inputSchema": {}}]
        )
        chrome.call_tool = AsyncMock(
            return_value={"content": [{"type": "text", "text": "navigated"}], "isError": False}
        )

        hub = MultiMCPClient(
            [
                MCPServerConfig(id="automation", transport="http", url="http://localhost:8000/mcp", tool_prefix=False),
                MCPServerConfig(id="chrome-devtools", transport="stdio", command="npx", args=[], tool_prefix=True),
            ]
        )
        hub._backends = {"automation": automation, "chrome-devtools": chrome}

        tools = await hub.list_tools()
        names = [tool["name"] for tool in tools]
        self.assertIn("fetch_url", names)
        self.assertIn("chrome-devtools/navigate", names)

        result = await hub.call_tool("chrome-devtools/navigate", {"url": "https://example.com"})
        chrome.call_tool.assert_awaited_once_with("navigate", {"url": "https://example.com"})
        self.assertIn("content", result)

    async def test_has_tool_for_prefixed_name_before_list_tools(self) -> None:
        hub = MultiMCPClient(
            [MCPServerConfig(id="chrome-devtools", transport="stdio", command="npx", args=[])]
        )
        self.assertTrue(hub.has_tool("chrome-devtools/navigate"))

    def test_name_helpers(self) -> None:
        self.assertEqual(_openai_tool_name("chrome-devtools", "navigate", use_prefix=True), "chrome-devtools/navigate")
        self.assertEqual(_openai_tool_name("automation", "fetch_url", use_prefix=False), "fetch_url")
        self.assertEqual(_split_tool_name("chrome-devtools/evaluate"), ("chrome-devtools", "evaluate"))


if __name__ == "__main__":
    unittest.main()
