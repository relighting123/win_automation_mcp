import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.report_paths import daily_report_path, parse_report_date
from tools import daily_report_tool as daily_tool
from tools import report_file_tool as report_tool


class ReportPathsTest(unittest.TestCase):
    def test_parse_report_date_defaults_today(self) -> None:
        self.assertEqual(parse_report_date(None), parse_report_date(""))

    def test_daily_report_path_format(self) -> None:
        path = daily_report_path(parse_report_date("2026-06-16"))
        self.assertTrue(str(path).endswith("2026-06-16.md"))


class WriteTextFileTest(unittest.IsolatedAsyncioTestCase):
    async def test_write_text_file_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "notes" / "test.md"
            with patch.object(report_tool, "_PROJECT_ROOT", Path(tmp)):
                raw = await report_tool.write_text_file(str(target), "hello")
            payload = json.loads(raw)
            self.assertTrue(payload["success"])
            self.assertEqual(target.read_text(encoding="utf-8"), "hello")


class BuildDailyReportTest(unittest.IsolatedAsyncioTestCase):
    async def test_build_daily_work_report_writes_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "report_config.yaml"
            config_path.write_text(
                "title: 테스트\nurls: []\noracle_queries: []\nsections:\n"
                "  - title: 메모\n    content: ok\n",
                encoding="utf-8",
            )
            with patch.object(daily_tool, "_PROJECT_ROOT", root), patch.object(
                daily_tool, "daily_report_path",
                return_value=root / "reports" / "daily" / "2026-06-16.md",
            ), patch.object(
                daily_tool, "write_text_file",
                new=AsyncMock(side_effect=lambda p, c, append=False: json.dumps({"success": True})),
            ):
                raw = await daily_tool.build_daily_work_report(
                    report_date="2026-06-16",
                    config_path=str(config_path),
                )
            payload = json.loads(raw)
            self.assertTrue(payload["success"])


if __name__ == "__main__":
    unittest.main()
