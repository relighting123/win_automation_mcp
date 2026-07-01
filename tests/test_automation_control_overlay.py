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
    _CHROME_BANNER_TEXT,
    _FONT,
    _GLOW_MARGIN,
    _ICON_FONT,
    AutomationControlOverlay,
    _get_target_rect,
    _lerp_color,
    _round_rect_points,
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

    def test_chrome_banner_text_matches_infobar_message(self) -> None:
        self.assertIn("자동화", _CHROME_BANNER_TEXT)
        self.assertIn("제어", _CHROME_BANNER_TEXT)

    def test_font_tuples_are_valid_tk_specs(self) -> None:
        """Tk 폰트 튜플은 (family:str, size:int[, style:str]) 형식이어야 한다."""
        for spec in (_FONT, _ICON_FONT):
            self.assertGreaterEqual(len(spec), 2)
            self.assertIsInstance(spec[0], str)
            self.assertIsInstance(spec[1], int)
            for style in spec[2:]:
                self.assertIsInstance(style, str)

    def test_border_geom_wraps_target_with_glow_margin(self) -> None:
        bx, by, bw, bh = AutomationControlOverlay._border_geom((100, 200, 800, 600))
        self.assertEqual((bx, by), (100 - _GLOW_MARGIN, 200 - _GLOW_MARGIN))
        self.assertEqual((bw, bh), (800 + _GLOW_MARGIN * 2, 600 + _GLOW_MARGIN * 2))

    def test_lerp_color_interpolates_endpoints_and_midpoint(self) -> None:
        self.assertEqual(_lerp_color("#000000", "#ffffff", 0.0), "#000000")
        self.assertEqual(_lerp_color("#000000", "#ffffff", 1.0), "#ffffff")
        self.assertEqual(_lerp_color("#000000", "#ffffff", 0.5), "#808080")

    def test_round_rect_points_returns_closed_polygon(self) -> None:
        pts = _round_rect_points(0, 0, 100, 40, 10)
        self.assertEqual(len(pts), 24)
        # 모든 좌표가 사각형 경계 안에 있어야 함
        xs = pts[0::2]
        ys = pts[1::2]
        self.assertTrue(all(0 <= x <= 100 for x in xs))
        self.assertTrue(all(0 <= y <= 40 for y in ys))

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
