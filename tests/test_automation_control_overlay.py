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
    fake_tk.StringVar = MagicMock
    fake_ttk.Frame = MagicMock
    fake_ttk.Label = MagicMock
    fake_ttk.Button = MagicMock
    sys.modules["tkinter"] = fake_tk
    sys.modules["tkinter.ttk"] = fake_ttk

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.automation_control_overlay_ui import AutomationControlOverlay


class AutomationControlOverlayTest(unittest.TestCase):
    def test_schedule_update_enqueues_command_without_calling_after(self) -> None:
        control = MagicMock()
        overlay = AutomationControlOverlay(control)
        overlay._root = MagicMock()
        overlay._closing = False

        with patch.object(overlay._root, "after") as after_mock:
            overlay.schedule_update()

        after_mock.assert_not_called()
        self.assertEqual(overlay._commands.get_nowait(), "update")

    def test_stop_enqueues_stop_command_without_calling_after(self) -> None:
        control = MagicMock()
        overlay = AutomationControlOverlay(control)
        overlay._root = MagicMock()
        overlay._thread = MagicMock()
        overlay._thread.is_alive.return_value = False

        with patch.object(overlay._root, "after") as after_mock:
            overlay.stop()

        after_mock.assert_not_called()
        self.assertEqual(overlay._commands.get_nowait(), "stop")

    def test_process_commands_destroy_runs_on_ui_side(self) -> None:
        control = MagicMock()
        overlay = AutomationControlOverlay(control)
        root = MagicMock()
        overlay._root = root
        overlay._commands.put("stop")

        overlay._process_commands()

        root.quit.assert_called_once()
        root.destroy.assert_called_once()
        root.after.assert_not_called()


if __name__ == "__main__":
    unittest.main()
