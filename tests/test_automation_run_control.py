import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.automation_run_control import (
    AutomationRunControl,
    begin_run_control,
    drain_overlay_shutdown,
    end_run_control,
    pump_overlay,
)


class AutomationRunControlTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        end_run_control()

    def test_begin_run_control_for_all_automation_modes(self) -> None:
        for mode in ("auto", "semi", "manual"):
            with self.subTest(mode=mode):
                control = begin_run_control(mode)
                self.assertIsNotNone(control)
                self.assertEqual(control.mode, mode)
                end_run_control()

    def test_begin_run_control_rejects_unknown_mode(self) -> None:
        self.assertIsNone(begin_run_control("invalid"))

    def test_stop_and_skip_flags(self) -> None:
        control = AutomationRunControl()
        control.request_stop()
        self.assertTrue(control.consume_stop())
        self.assertFalse(control.consume_stop())

        control.request_skip_skill()
        self.assertTrue(control.consume_skip_skill())
        self.assertFalse(control.consume_skip_skill())

    def test_on_ctrl_c_first_press_pauses(self) -> None:
        control = AutomationRunControl()
        self.assertEqual(control.on_ctrl_c(), "pause")
        self.assertTrue(control.is_paused())

    def test_on_ctrl_c_second_press_stops(self) -> None:
        control = AutomationRunControl()
        self.assertEqual(control.on_ctrl_c(), "pause")
        # 이미 일시정지 상태에서 다시 누르면 반드시 중지에 도달
        self.assertEqual(control.on_ctrl_c(), "stop")
        self.assertTrue(control.peek_stop())
        self.assertFalse(control.is_paused())

    async def test_wait_if_paused_unblocks_on_resume(self) -> None:
        import asyncio

        control = AutomationRunControl()
        control.pause()
        task = asyncio.create_task(control.wait_if_paused())
        await asyncio.sleep(0.05)
        self.assertFalse(task.done())
        control.resume()
        await task
        self.assertTrue(task.done())

    @patch("core.automation_run_control.overlay_supported", return_value=True)
    def test_pump_overlay_drains_pending_shutdown(self, _supported: MagicMock) -> None:
        control = begin_run_control("semi")
        overlay = control._overlay
        self.assertIsNotNone(overlay)

        with patch.object(overlay, "pump") as pump_mock:
            overlay._shutdown_done.clear()
            overlay.stop()
            end_run_control()
            pump_overlay()
            self.assertGreaterEqual(pump_mock.call_count, 1)

        overlay._shutdown_done.set()
        drain_overlay_shutdown(timeout=0.05, interval=0.01)


if __name__ == "__main__":
    unittest.main()
