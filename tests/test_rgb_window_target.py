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


class RgbWindowTargetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.action = AppUIAction(session=MagicMock())
        self.main = _MockWindow(title="Main", left=10, top=20)
        self.find = _MockWindow(title="Find", left=50, top=60, width=200, height=120)

    def test_legacy_auto_uses_single_pick(self) -> None:
        with patch.object(self.action, "_pick_target_window", return_value=self.main):
            targets = self.action._iter_rgb_search_targets(window_target="auto")
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0][0], "auto->single")
        self.assertEqual(targets[0][2], (10, 20, 100, 80))

    def test_top_iterates_search_roots(self) -> None:
        with patch.object(self.action, "_iter_process_top_windows", return_value=[self.main]):
            with patch.object(
                self.action,
                "_iter_attr_search_roots",
                return_value=[(self.main, "top"), (self.find, "child[0](title=Find)")],
            ):
                targets = self.action._iter_rgb_search_targets(window_target="top")

        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0][2], (10, 20, 100, 80))
        self.assertEqual(targets[1][2], (50, 60, 200, 120))

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


if __name__ == "__main__":
    unittest.main()
