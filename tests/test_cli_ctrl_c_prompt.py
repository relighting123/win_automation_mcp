import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from chatrtd_cli import ChatRTDCLI
from core.automation_run_control import begin_run_control, end_run_control


class PromptCtrlCTest(unittest.TestCase):
    def _make_cli(self) -> ChatRTDCLI:
        # __init__(OpenAI 클라이언트 등)을 건너뛰고 필요한 속성만 세팅
        cli = ChatRTDCLI.__new__(ChatRTDCLI)
        cli._busy = False
        return cli

    def tearDown(self) -> None:
        end_run_control()

    def test_no_active_work_when_idle(self) -> None:
        cli = self._make_cli()
        self.assertFalse(cli._has_active_work())

    def test_busy_flag_marks_active_work(self) -> None:
        cli = self._make_cli()
        cli._busy = True
        self.assertTrue(cli._has_active_work())

    def test_active_automation_marks_active_work(self) -> None:
        cli = self._make_cli()
        control = begin_run_control("semi")
        self.assertIsNotNone(control)
        self.assertTrue(cli._has_active_work())

    def test_stop_active_work_requests_stop(self) -> None:
        cli = self._make_cli()
        control = begin_run_control("semi")
        cli._stop_active_work()
        self.assertTrue(control.peek_stop())

    def test_stop_active_work_is_safe_when_idle(self) -> None:
        cli = self._make_cli()
        # 활성 작업이 없어도 예외 없이 동작해야 함
        cli._stop_active_work()


if __name__ == "__main__":
    unittest.main()
