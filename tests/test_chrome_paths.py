import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.chrome_paths import (
    chrome_missing_help_message,
    find_chrome_binary,
    is_chrome_missing_error,
)
from core.mcp_server_config import load_mcp_servers


class ChromePathsTest(unittest.TestCase):
    def test_is_chrome_missing_error(self) -> None:
        self.assertTrue(is_chrome_missing_error("Chrome executable not found on this system"))
        self.assertTrue(is_chrome_missing_error("Install Google Chrome"))
        self.assertFalse(is_chrome_missing_error("navigation timeout"))

    def test_chrome_missing_help_message_mentions_install(self) -> None:
        message = chrome_missing_help_message()
        self.assertIn("Chrome", message)

    def test_find_chrome_binary_respects_env(self) -> None:
        with patch.dict(
            os.environ,
            {"CHROME_PATH": r"C:\Custom\chrome.exe"},
            clear=False,
        ):
            with patch("core.chrome_paths.Path.is_file", return_value=True):
                self.assertEqual(find_chrome_binary(), r"C:\Custom\chrome.exe")

    def test_openchrome_server_passes_chrome_path_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_OPENCHROME_ENABLED": "true",
                "CHROME_PATH": r"C:\Edge\msedge.exe",
            },
            clear=False,
        ):
            with patch("core.chrome_paths.Path.is_file", return_value=True):
                servers = load_mcp_servers(base_url_override="http://localhost:8000/mcp")

        openchrome = next(server for server in servers if server.id == "openchrome")
        self.assertEqual(openchrome.env.get("CHROME_PATH"), r"C:\Edge\msedge.exe")


if __name__ == "__main__":
    unittest.main()
