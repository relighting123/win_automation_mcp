import unittest
from unittest.mock import MagicMock, patch

from core import windows_scheduler as sched


class WindowsSchedulerTest(unittest.TestCase):
    def test_validate_time(self) -> None:
        self.assertTrue(sched._validate_time_hhmm("18:00"))
        self.assertFalse(sched._validate_time_hhmm("25:00"))

    @patch.object(sched, "is_windows_scheduler_available", return_value=False)
    def test_register_not_windows(self, _mock: MagicMock) -> None:
        result = sched.register_preset_task("daily", time_hhmm="18:00")
        self.assertFalse(result["success"])

    @patch.object(sched, "_run_schtasks")
    @patch.object(sched, "is_windows_scheduler_available", return_value=True)
    @patch.object(sched, "_build_tr_command", return_value='cmd /c echo test')
    def test_register_daily(self, _tr: MagicMock, _win: MagicMock, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = sched.register_preset_task("daily", time_hhmm="18:00")
        self.assertTrue(result["success"])
        self.assertEqual(result["task_name"], "chatRTD-DailySummary")


if __name__ == "__main__":
    unittest.main()
