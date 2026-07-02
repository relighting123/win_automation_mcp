import unittest
from unittest.mock import MagicMock, patch

from core.async_loop_runner import AsyncLoopRunner, run_async, shutdown_async_runner


class AsyncLoopRunnerTest(unittest.TestCase):
    def tearDown(self) -> None:
        shutdown_async_runner()

    async def _async_add(self, a: int, b: int) -> int:
        return a + b

    def test_run_async_on_background_loop(self) -> None:
        result = run_async(self._async_add(2, 3))
        self.assertEqual(result, 5)

    def test_shutdown_and_rerun(self) -> None:
        self.assertEqual(run_async(self._async_add(1, 1)), 2)
        shutdown_async_runner()
        self.assertEqual(run_async(self._async_add(4, 5)), 9)


class AsyncLoopRunnerCtrlCTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = AsyncLoopRunner()

    def tearDown(self) -> None:
        self.runner.shutdown()

    def test_ctrl_c_without_active_control_propagates(self) -> None:
        future = MagicMock()
        with patch("core.automation_run_control.get_active_control", return_value=None):
            keep_running = self.runner._on_keyboard_interrupt(future)
        self.assertFalse(keep_running)

    def test_ctrl_c_with_active_control_pauses_and_keeps_running(self) -> None:
        control = MagicMock()
        control.peek_stop.return_value = False
        control.on_ctrl_c.return_value = "pause"
        future = MagicMock()
        with patch(
            "core.automation_run_control.get_active_control", return_value=control
        ):
            keep_running = self.runner._on_keyboard_interrupt(future)
        self.assertTrue(keep_running)
        control.on_ctrl_c.assert_called_once()

    def test_ctrl_c_after_stop_already_requested_force_quits(self) -> None:
        control = MagicMock()
        control.peek_stop.return_value = True
        future = MagicMock()
        with patch(
            "core.automation_run_control.get_active_control", return_value=control
        ):
            keep_running = self.runner._on_keyboard_interrupt(future)
        self.assertFalse(keep_running)
        control.on_ctrl_c.assert_not_called()


if __name__ == "__main__":
    unittest.main()
