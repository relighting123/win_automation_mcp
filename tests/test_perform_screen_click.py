import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from actions.app_ui_action import AppUIAction


class PerformScreenClickTest(unittest.TestCase):
    def setUp(self) -> None:
        session = MagicMock()
        session.is_connected = True
        session.config = {"timeouts": {"ui_delay": 0}}
        self.action = AppUIAction(session=session)
        self.action._launcher = MagicMock()

    def test_mouse_click_uses_pyautogui_with_target_coordinates(self) -> None:
        pyautogui = MagicMock()
        with patch.object(self.action, "_get_pyautogui", return_value=(pyautogui, None)):
            with patch.object(self.action, "_get_cursor_pos", side_effect=[(0, 0), (120, 80)]):
                method = self.action._perform_screen_click(
                    120,
                    80,
                    button="right",
                    click_method="mouse",
                )

        self.assertEqual(method, "pyautogui")
        pyautogui.click.assert_called_once_with(x=120, y=80, button="right", clicks=1)


if __name__ == "__main__":
    unittest.main()
