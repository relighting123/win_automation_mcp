import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from actions.app_ui_action import AppUIAction, AppUIActionResult


class RightClickAtFocusTest(unittest.TestCase):
    def setUp(self) -> None:
        session = MagicMock()
        session.is_connected = True
        app = MagicMock()
        app.process = 4242
        app.windows.return_value = []
        session.app = app
        self.action = AppUIAction(session=session)
        self.action._launcher = MagicMock()

    def test_right_click_uses_focus_point_without_ensure_focus(self) -> None:
        with patch.object(self.action, "ensure_focus") as ensure_focus:
            with patch.object(
                self.action,
                "_resolve_focus_click_point",
                return_value=(100, 200, {"source": "uia_focused", "process_id": 4242}),
            ):
                with patch.object(
                    self.action,
                    "_get_pyautogui",
                    return_value=(MagicMock(), None),
                ) as get_pyautogui:
                    result = self.action.right_click_at_focus()

        self.assertEqual(result.result, "success")
        self.assertEqual(result.x, 100)
        self.assertEqual(result.y, 200)
        ensure_focus.assert_not_called()
        pyautogui = get_pyautogui.return_value[0]
        pyautogui.click.assert_called_once_with(x=100, y=200, button="right", clicks=1)

    def test_right_click_rejects_foreign_process(self) -> None:
        with patch.object(
            self.action,
            "_resolve_focus_click_point",
            return_value=(50, 60, {"source": "caret", "process_id": 9999}),
        ):
            result = self.action.right_click_at_focus(require_app_focus=True)

        self.assertEqual(result.result, "error")
        self.assertIn("연결된 애플리케이션이 아닙니다", result.message or "")

    def test_right_click_not_found(self) -> None:
        with patch.object(
            self.action,
            "_resolve_focus_click_point",
            return_value=(None, None, {}),
        ):
            result = self.action.right_click_at_focus()

        self.assertEqual(result.result, "not_found")

    def test_resolve_focus_prefers_caret(self) -> None:
        with patch.object(
            self.action,
            "_get_caret_focus_click_point",
            return_value=(10, 20, {"source": "caret"}),
        ):
            with patch.object(self.action, "_get_uia_focused_click_point") as uia_focus:
                x, y, info = self.action._resolve_focus_click_point()

        self.assertEqual((x, y), (10, 20))
        self.assertEqual(info["source"], "caret")
        uia_focus.assert_not_called()


if __name__ == "__main__":
    unittest.main()
