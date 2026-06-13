import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from actions.app_ui_action import AppUIAction, AppUIActionResult


class ClickAtFocusTest(unittest.TestCase):
    def setUp(self) -> None:
        session = MagicMock()
        session.is_connected = True
        session.config = {"timeouts": {"after_focus_delay": 0, "ui_delay": 0}}
        app = MagicMock()
        app.process = 4242
        app.windows.return_value = []
        session.app = app
        self.action = AppUIAction(session=session)
        self.action._launcher = MagicMock()

    def test_right_click_moves_mouse_and_clicks(self) -> None:
        with patch.object(
            self.action,
            "ensure_focus",
            return_value=AppUIActionResult(result="success"),
        ) as ensure_focus:
            with patch.object(
                self.action,
                "_resolve_focus_click_point",
                return_value=(100, 200, {"source": "uia_focused", "process_id": 4242, "hwnd": 5555}),
            ):
                with patch.object(
                    self.action,
                    "click_position",
                    return_value=AppUIActionResult(
                        result="success",
                        x=100,
                        y=200,
                        button="right",
                        message="method=win32_mouse_event",
                    ),
                ) as click_position:
                    result = self.action.click_at_focus()

        self.assertEqual(result.result, "success")
        self.assertEqual(result.x, 100)
        self.assertEqual(result.y, 200)
        ensure_focus.assert_called_once()
        click_position.assert_called_once_with(
            x=100,
            y=200,
            button="right",
            clicks=1,
        )

    def test_left_click_at_focus(self) -> None:
        with patch.object(
            self.action,
            "ensure_focus",
            return_value=AppUIActionResult(result="success"),
        ):
            with patch.object(
                self.action,
                "_resolve_focus_click_point",
                return_value=(80, 90, {"source": "caret", "process_id": 4242}),
            ):
                with patch.object(
                    self.action,
                    "click_position",
                    return_value=AppUIActionResult(
                        result="success",
                        x=80,
                        y=90,
                        button="left",
                        message="method=win32_mouse_event",
                    ),
                ) as click_position:
                    result = self.action.click_at_focus(button="left")

        self.assertEqual(result.result, "success")
        click_position.assert_called_once_with(
            x=80,
            y=90,
            button="left",
            clicks=1,
        )

    def test_fails_when_ensure_focus_fails(self) -> None:
        with patch.object(
            self.action,
            "ensure_focus",
            return_value=AppUIActionResult(result="error", message="포커스 실패"),
        ):
            result = self.action.click_at_focus()

        self.assertEqual(result.result, "error")
        self.assertIn("포커스 실패", result.message or "")

    def test_rejects_foreign_process(self) -> None:
        with patch.object(
            self.action,
            "ensure_focus",
            return_value=AppUIActionResult(result="success"),
        ):
            with patch.object(
                self.action,
                "_resolve_focus_click_point",
                return_value=(50, 60, {"source": "caret", "process_id": 9999}),
            ):
                result = self.action.click_at_focus(require_app_focus=True)

        self.assertEqual(result.result, "error")
        self.assertIn("연결된 애플리케이션이 아닙니다", result.message or "")

    def test_not_found(self) -> None:
        with patch.object(
            self.action,
            "ensure_focus",
            return_value=AppUIActionResult(result="success"),
        ):
            with patch.object(
                self.action,
                "_resolve_focus_click_point",
                return_value=(None, None, {}),
            ):
                result = self.action.click_at_focus()

        self.assertEqual(result.result, "not_found")

    def test_invalid_button(self) -> None:
        result = self.action.click_at_focus(button="invalid")
        self.assertEqual(result.result, "error")

    def test_click_with_offset(self) -> None:
        with patch.object(
            self.action,
            "ensure_focus",
            return_value=AppUIActionResult(result="success"),
        ):
            with patch.object(
                self.action,
                "_resolve_focus_click_point",
                return_value=(100, 200, {"source": "uia_focused", "process_id": 4242}),
            ):
                with patch.object(
                    self.action,
                    "click_position",
                    return_value=AppUIActionResult(
                        result="success",
                        x=105,
                        y=197,
                        button="right",
                        message="method=win32_mouse_event",
                    ),
                ) as click_position:
                    result = self.action.click_at_focus(offset_x=5, offset_y=-3)

        self.assertEqual(result.result, "success")
        self.assertEqual(result.x, 105)
        self.assertEqual(result.y, 197)
        click_position.assert_called_once_with(
            x=105,
            y=197,
            button="right",
            clicks=1,
        )

    def test_click_position_failure_propagates(self) -> None:
        with patch.object(
            self.action,
            "ensure_focus",
            return_value=AppUIActionResult(result="success"),
        ):
            with patch.object(
                self.action,
                "_resolve_focus_click_point",
                return_value=(100, 200, {"source": "uia_focused", "process_id": 4242}),
            ):
                with patch.object(
                    self.action,
                    "click_position",
                    return_value=AppUIActionResult(result="error", message="좌표 클릭 실패: boom"),
                ):
                    result = self.action.click_at_focus()

        self.assertEqual(result.result, "error")
        self.assertIn("좌표 클릭 실패", result.message or "")

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
