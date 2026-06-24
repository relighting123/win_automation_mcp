import queue
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

if "tkinter" not in sys.modules:
    fake_tk = types.ModuleType("tkinter")
    fake_ttk = types.ModuleType("tkinter.ttk")
    fake_tk.TclError = Exception
    fake_tk.Tk = MagicMock
    fake_tk.Toplevel = MagicMock
    fake_tk.StringVar = MagicMock
    fake_tk.Canvas = MagicMock
    fake_tk.Frame = MagicMock
    fake_tk.Label = MagicMock
    fake_ttk.Frame = MagicMock
    fake_ttk.Label = MagicMock
    fake_ttk.Button = MagicMock
    sys.modules["tkinter"] = fake_tk
    sys.modules["tkinter.ttk"] = fake_ttk

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.automation_control_overlay_ui import (
    AutomationControlOverlay,
    _get_target_rect,
)


class AutomationControlOverlayTest(unittest.TestCase):
    def test_schedule_update_enqueues_command_without_touching_tk(self) -> None:
        control = MagicMock()
        overlay = AutomationControlOverlay(control)

        with patch("threading.current_thread", return_value=MagicMock()):
            overlay.schedule_update()

        self.assertEqual(overlay._commands.get_nowait(), "update")

    def test_stop_enqueues_stop_command(self) -> None:
        control = MagicMock()
        overlay = AutomationControlOverlay(control)

        with patch("threading.current_thread", return_value=MagicMock()):
            overlay.stop()

        self.assertTrue(overlay._closing)
        self.assertEqual(overlay._commands.get_nowait(), "stop")

    def test_process_commands_destroy_on_stop(self) -> None:
        control = MagicMock()
        overlay = AutomationControlOverlay(control)
        root = MagicMock()
        root.tk.call.return_value = []
        overlay._root = root
        overlay._commands.put("stop")

        overlay._process_commands()

        root.destroy.assert_called_once()
        self.assertTrue(overlay.is_shutdown)

    def test_process_commands_skips_destroy_when_closing_flag_set(self) -> None:
        control = MagicMock()
        overlay = AutomationControlOverlay(control)
        root = MagicMock()
        root.tk.call.return_value = []
        overlay._root = root
        overlay._closing = True

        overlay._process_commands()

        root.destroy.assert_called_once()
        self.assertTrue(overlay.is_shutdown)

    def test_pump_ignores_non_main_thread(self) -> None:
        control = MagicMock()
        overlay = AutomationControlOverlay(control)

        with patch.object(overlay, "_create_ui") as create_ui:
            with patch("threading.current_thread", return_value=MagicMock()):
                overlay.pump()

        create_ui.assert_not_called()

    def test_calc_overlay_pos_docks_to_target_top(self) -> None:
        ov_x, ov_y, ov_w = AutomationControlOverlay._calc_overlay_pos((100, 200, 800, 600))
        self.assertEqual(ov_x, 260)
        self.assertEqual(ov_y, 208)
        self.assertEqual(ov_w, 480)

    def test_get_target_rect_returns_none_when_not_connected(self) -> None:
        session = MagicMock()
        session.is_connected = False
        with patch("core.app_session.AppSession") as app_session:
            app_session.get_instance.return_value = session
            self.assertIsNone(_get_target_rect())

    def test_sync_visibility_hides_without_target(self) -> None:
        control = MagicMock()
        overlay = AutomationControlOverlay(control)
        root = MagicMock()
        overlay._root = root
        overlay._visible = True

        with patch(
            "core.automation_control_overlay_ui._get_target_rect",
            return_value=None,
        ):
            overlay._sync_visibility_and_position()

        root.withdraw.assert_called_once()
        self.assertFalse(overlay._visible)


if __name__ == "__main__":
    unittest.main()
