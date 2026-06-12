import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from actions.app_ui_action import AppUIAction


class _Rect:
    def __init__(self, left: int, top: int, width: int, height: int):
        self.left = left
        self.top = top
        self._width = width
        self._height = height

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class _MockWindow:
    def __init__(self, *, title: str, left: int = 0, top: int = 0, width: int = 100, height: int = 80):
        self._title = title
        self._rect = _Rect(left, top, width, height)

    def rectangle(self):
        return self._rect

    def window_text(self):
        return self._title

    def set_focus(self):
        return None

    def draw_outline(self, colour: str = "green"):
        self._last_outline_colour = colour


class _Info:
    def __init__(self, *, title="", automation_id="", control_id="", control_type="Window"):
        self.automation_id = automation_id
        self.control_id = control_id
        self.control_type = control_type
        self.class_name = ""
        self.handle = 1234


class _IdentityWindow:
    def __init__(self, *, title="Find", automation_id="FindDlg"):
        self.element_info = _Info(title=title, automation_id=automation_id, control_id="2000")
        self._title = title

    def window_text(self):
        return self._title


class RgbWindowTargetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock()
        self.session.config = {"timeouts": {"ui_delay": 0.01, "after_focus_delay": 0.01}}
        self.action = AppUIAction(session=self.session)
        self.main = _MockWindow(title="Main", left=10, top=20)
        self.find = _MockWindow(title="Find", left=50, top=60, width=200, height=120)

    def test_legacy_auto_uses_single_pick(self) -> None:
        with patch.object(self.action, "_pick_target_window", return_value=self.main):
            targets = self.action._iter_rgb_search_targets(window_target="auto")
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0][0], "auto->single")
        self.assertEqual(targets[0][2], (6, 16, 108, 88))

    def test_top_iterates_search_roots(self) -> None:
        with patch.object(self.action, "_iter_process_top_windows", return_value=[self.main]):
            with patch.object(
                self.action,
                "_iter_attr_search_roots",
                return_value=[(self.main, "top"), (self.find, "child[0](title=Find)")],
            ):
                targets = self.action._iter_rgb_search_targets(window_target="top")

        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0][2], (6, 16, 108, 88))
        self.assertEqual(targets[1][2], (46, 56, 208, 128))

    def test_format_search_window_log(self) -> None:
        window = _IdentityWindow(title="Find", automation_id="FindDlg")
        label = self.action._format_search_window_log(window)
        self.assertIn("title=Find", label)
        self.assertIn("auto_id=FindDlg", label)
        self.assertIn("control_id=2000", label)

    def test_child_scope_uses_resolve_roots(self) -> None:
        with patch.object(self.action, "_iter_process_top_windows", return_value=[self.main]):
            with patch.object(
                self.action,
                "_iter_attr_search_roots",
                return_value=[(self.find, "child(title=Find)")],
            ) as mock_roots:
                targets = self.action._iter_rgb_search_targets(
                    window_target="child",
                    child_window_title="Find",
                )

        mock_roots.assert_called_once()
        self.assertEqual(len(targets), 1)
        self.assertIs(targets[0][1], self.find)


    def test_get_desktop_region(self) -> None:
        fake_pyautogui = MagicMock()
        fake_pyautogui.size.return_value = MagicMock(width=1920, height=1080)
        region = self.action._get_desktop_region(fake_pyautogui)
        self.assertEqual(region, (0, 0, 1920, 1080))

    def test_find_rgb_position_desktop_scope(self) -> None:
        fake_pyautogui = MagicMock()
        with patch.object(self.action, "_get_pyautogui", return_value=(fake_pyautogui, None)):
            with patch.object(self.action, "_get_desktop_region", return_value=(0, 0, 800, 600)):
                with patch.object(self.action, "_find_rgb_in_region", return_value=(120, 80)):
                    result = self.action.find_rgb_position(
                        rgb=(255, 0, 0),
                        tolerance=0,
                        search_scope="desktop",
                    )

        self.assertTrue(result.is_success)
        self.assertEqual(result.x, 120)
        self.assertEqual(result.y, 80)
        fake_pyautogui.screenshot.assert_called_once_with(region=(0, 0, 800, 600))


class RgbOutlineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock()
        self.session.config = {"timeouts": {"ui_delay": 0.01, "after_focus_delay": 0.01}}
        self.action = AppUIAction(session=self.session)
        self.main = _MockWindow(title="Main", left=10, top=20)
        self.find = _MockWindow(title="Find", left=50, top=60, width=200, height=120)

    def _run_find(self, *, match_on: str = "find", **kwargs):
        defaults = {
            "rgb": (255, 0, 0),
            "tolerance": 0,
            "window_target": "top",
            "draw_outline": True,
            "timeout": 0.1,
        }
        defaults.update(kwargs)
        fake_pyautogui = MagicMock()

        def screenshot_side_effect(*, region):
            if region == (46, 56, 208, 128):
                return MagicMock()
            return MagicMock()

        fake_pyautogui.screenshot.side_effect = screenshot_side_effect

        def find_side_effect(*, region, **_kwargs):
            if match_on == "find" and region == (46, 56, 208, 128):
                return (120, 80)
            if match_on == "main" and region == (6, 16, 108, 88):
                return (50, 40)
            return None

        with patch.object(self.action, "_get_pyautogui", return_value=(fake_pyautogui, None)):
            with patch.object(self.action, "_iter_process_top_windows", return_value=[self.main]):
                with patch.object(
                    self.action,
                    "_iter_attr_search_roots",
                    return_value=[(self.main, "top"), (self.find, "child[0](title=Find)")],
                ):
                    with patch.object(self.action, "_find_rgb_in_region", side_effect=find_side_effect):
                        return self.action.find_rgb_position(**defaults)

    def test_invalid_outline_scope_returns_error(self) -> None:
        fake_pyautogui = MagicMock()
        with patch.object(self.action, "_get_pyautogui", return_value=(fake_pyautogui, None)):
            with patch.object(self.action, "_iter_rgb_search_targets", return_value=[("top", self.main, (0, 0, 10, 10))]):
                result = self.action.find_rgb_position(
                    rgb=(1, 2, 3),
                    draw_outline=True,
                    outline_scope="invalid",
                )
        self.assertEqual(result.result, "error")
        self.assertIn("outline_scope", result.message or "")

    def test_outline_scope_search_highlights_regions_only(self) -> None:
        with patch.object(self.action, "_safe_draw_pixel_marker") as mock_pixel:
            result = self._run_find(outline_scope="search", match_on="find")
        self.assertTrue(result.is_success)
        self.assertEqual(getattr(self.main, "_last_outline_colour", None), "green")
        self.assertEqual(getattr(self.find, "_last_outline_colour", None), "green")
        mock_pixel.assert_not_called()

    def test_outline_scope_target_marks_pixel_only(self) -> None:
        with patch.object(self.action, "_safe_draw_rgb_search_region") as mock_region:
            with patch.object(self.action, "_safe_draw_pixel_marker") as mock_pixel:
                result = self._run_find(outline_scope="target", match_on="find")
        self.assertTrue(result.is_success)
        mock_region.assert_not_called()
        mock_pixel.assert_called_once()
        self.assertEqual(mock_pixel.call_args.kwargs["colour"], "red")
        self.assertEqual(mock_pixel.call_args.kwargs["x"], 120)
        self.assertEqual(mock_pixel.call_args.kwargs["y"], 80)

    def test_outline_scope_all_highlights_region_and_pixel(self) -> None:
        with patch.object(self.action, "_safe_draw_pixel_marker") as mock_pixel:
            result = self._run_find(outline_scope="all", match_on="find")
        self.assertTrue(result.is_success)
        self.assertEqual(getattr(self.main, "_last_outline_colour", None), "green")
        self.assertEqual(getattr(self.find, "_last_outline_colour", None), "green")
        mock_pixel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
