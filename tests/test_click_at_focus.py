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
            "_ensure_connected",
            return_value=AppUIActionResult(result="success"),
        ):
            with patch.object(
                self.action,
                "ensure_focus",
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
        ensure_focus.assert_not_called()
        click_position.assert_called_once_with(
            x=100,
            y=200,
            button="right",
            clicks=1,
        )

    def test_left_click_at_focus(self) -> None:
        with patch.object(
            self.action,
            "_ensure_connected",
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

    def test_fails_when_ensure_window_focus_fails(self) -> None:
        with patch.object(
            self.action,
            "_ensure_connected",
            return_value=AppUIActionResult(result="success"),
        ):
            with patch.object(
                self.action,
                "_resolve_focus_click_point",
                return_value=(100, 200, {"source": "uia_focused", "process_id": 4242}),
            ):
                with patch.object(
                    self.action,
                    "ensure_focus",
                    return_value=AppUIActionResult(result="error", message="포커스 실패"),
                ):
                    result = self.action.click_at_focus(ensure_window_focus=True)

        self.assertEqual(result.result, "error")
        self.assertIn("포커스 실패", result.message or "")

    def test_ensure_window_focus_calls_ensure_focus(self) -> None:
        with patch.object(
            self.action,
            "_ensure_connected",
            return_value=AppUIActionResult(result="success"),
        ):
            with patch.object(
                self.action,
                "_resolve_focus_click_point",
                return_value=(100, 200, {"source": "uia_focused", "process_id": 4242}),
            ):
                with patch.object(
                    self.action,
                    "ensure_focus",
                    return_value=AppUIActionResult(result="success"),
                ) as ensure_focus:
                    with patch.object(
                        self.action,
                        "click_position",
                        return_value=AppUIActionResult(result="success", x=100, y=200, button="right"),
                    ):
                        self.action.click_at_focus(ensure_window_focus=True)

        ensure_focus.assert_called_once()

    def test_ensure_window_focus_brings_active_window_before_resolve(self) -> None:
        """ensure_window_focus=True이면 활성 창(다이얼로그 포함)을 좌표 읽기 전에
        foreground로 가져오고, 성공 시 ensure_focus 폴백은 사용하지 않습니다."""
        call_order: list[str] = []

        def fake_bring(hwnd: int) -> bool:
            call_order.append(f"bring:{hwnd}")
            return True

        def fake_resolve():
            call_order.append("resolve")
            return (100, 200, {"source": "caret", "process_id": 4242, "hwnd": 7777})

        with patch.object(
            self.action,
            "_ensure_connected",
            return_value=AppUIActionResult(result="success"),
        ):
            with patch.object(self.action, "_get_connected_app_top_hwnd", return_value=7777):
                with patch.object(self.action, "_bring_hwnd_to_foreground", side_effect=fake_bring):
                    with patch.object(self.action, "ensure_focus") as ensure_focus:
                        with patch.object(
                            self.action,
                            "_resolve_focus_click_point",
                            side_effect=fake_resolve,
                        ):
                            with patch.object(
                                self.action,
                                "click_position",
                                return_value=AppUIActionResult(
                                    result="success", x=100, y=200, button="right"
                                ),
                            ):
                                result = self.action.click_at_focus(ensure_window_focus=True)

        self.assertEqual(result.result, "success")
        # 창을 앞으로 가져온 뒤에 포커스 좌표를 읽어야 합니다.
        self.assertEqual(call_order, ["bring:7777", "resolve"])
        # foreground 전환에 성공했으므로 ensure_focus 폴백은 호출되지 않습니다.
        ensure_focus.assert_not_called()

    def test_rejects_foreign_process(self) -> None:
        with patch.object(
            self.action,
            "_ensure_connected",
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
            "_ensure_connected",
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
            "_ensure_connected",
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
        self.assertEqual(result.base_x, 100)
        self.assertEqual(result.base_y, 200)
        self.assertEqual(result.offset_x, 5)
        self.assertEqual(result.offset_y, -3)
        click_position.assert_called_once_with(
            x=105,
            y=197,
            button="right",
            clicks=1,
        )

    def test_click_with_string_offset(self) -> None:
        with patch.object(
            self.action,
            "_ensure_connected",
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
                    return_value=AppUIActionResult(result="success", x=120, y=180, button="right"),
                ) as click_position:
                    result = self.action.click_at_focus(offset_x="20", offset_y="-20")

        self.assertEqual(result.result, "success")
        click_position.assert_called_once_with(
            x=120,
            y=180,
            button="right",
            clicks=1,
        )

    def test_click_position_failure_propagates(self) -> None:
        with patch.object(
            self.action,
            "_ensure_connected",
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


class ForegroundFocusTest(unittest.TestCase):
    def setUp(self) -> None:
        session = MagicMock()
        session.is_connected = True
        session.config = {"timeouts": {"after_focus_delay": 0, "ui_delay": 0}}
        session.app = MagicMock()
        session.app.process = 4242
        session.app.windows.return_value = []
        self.action = AppUIAction(session=session)

    def test_is_hwnd_foreground_accepts_same_root(self) -> None:
        fake_win32gui = MagicMock()
        fake_win32gui.GetForegroundWindow.return_value = 2000
        with patch.dict(sys.modules, {"win32gui": fake_win32gui}):
            with patch.object(self.action, "_get_hwnd_root", side_effect=lambda h: 1000 if h == 2000 else h):
                with patch.object(self.action, "_get_connected_process_ids", return_value={4242}):
                    with patch.object(self.action, "_pid_from_hwnd", return_value=4242):
                        self.assertTrue(self.action._is_hwnd_foreground(1000))

    def test_is_hwnd_foreground_accepts_connected_process_pid(self) -> None:
        fake_win32gui = MagicMock()
        fake_win32gui.GetForegroundWindow.return_value = 3000
        with patch.dict(sys.modules, {"win32gui": fake_win32gui}):
            with patch.object(self.action, "_get_hwnd_root", side_effect=lambda h: h):
                with patch.object(self.action, "_get_connected_process_ids", return_value={4242}):
                    with patch.object(self.action, "_pid_from_hwnd", side_effect=lambda h: 4242 if h == 3000 else 9999):
                        self.assertTrue(self.action._is_hwnd_foreground(5000))

    def test_activate_window_prefers_bring_hwnd(self) -> None:
        wrapper = MagicMock()
        wrapper.is_minimized.return_value = False
        with patch.object(self.action, "_get_wrapper_handle", return_value=7777):
            with patch.object(self.action, "_bring_hwnd_to_foreground", return_value=True) as bring:
                activated = self.action._activate_window(wrapper, max_attempts=1)
        self.assertTrue(activated)
        bring.assert_called_once_with(7777)
        wrapper.set_focus.assert_not_called()


if __name__ == "__main__":
    unittest.main()
