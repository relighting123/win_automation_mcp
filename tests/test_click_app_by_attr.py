import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from actions.app_ui_action import AppUIAction


_handle_counter = 0


class _Info:
    def __init__(self, *, control_type="Button", control_id=1001, automation_id="Close", handle=None):
        global _handle_counter
        _handle_counter += 1
        self.control_type = control_type
        self.control_id = control_id
        self.automation_id = automation_id
        self.handle = handle if handle is not None else 1000 + _handle_counter
        self.runtime_id = (self.handle,)
        self.name = ""
        self.rich_text = ""
        self.class_name = ""


class _MockNode:
    def __init__(self, *, title="", control_type="Button", control_id=1001, automation_id="Close", visible=True):
        self.element_info = _Info(control_type=control_type, control_id=control_id, automation_id=automation_id)
        self._title = title
        self._visible = visible

    def window_text(self):
        return self._title

    def is_visible(self):
        return self._visible

    def exists(self):
        return True

    def descendants(self):
        return []

    def children(self):
        return []

    def wrapper_object(self):
        return self


class _MockFind(_MockNode):
    def __init__(self):
        super().__init__(title="Find", control_type="Window", control_id=2000, automation_id="FindDlg")
        self._cached_descendants = [
            _MockNode(title="Next", control_type="Button", control_id=2001, automation_id="btnNext"),
            _MockNode(title="닫기", control_type="Button", control_id=2002, automation_id="Close"),
        ]

    def descendants(self):
        return self._cached_descendants


class _MockMainWithFind(_MockNode):
    def __init__(self):
        super().__init__(title="", control_type="Window", control_id=1, automation_id="MainWnd")
        self.find = _MockFind()

    def children(self):
        return [self.find]

    def descendants(self):
        return [
            _MockNode(title="Next", control_type="Button", control_id=3001, automation_id="btnNext"),
            self.find,
        ]


class ClickAppByAttrChildRootsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.action = AppUIAction(session=MagicMock())
        self.top = _MockMainWithFind()

    def _find_by_auto_id(self, *, auto_id: str, window_target: str = "top", child_window_title=None):
        for search_root, _info in self.action._iter_attr_search_roots(
            window_target=window_target,
            child_window_title=child_window_title,
            child_window_auto_id=None,
            child_window_match_mode="contains",
            case_sensitive=False,
            top_window_override=self.top,
        ):
            if search_root is None:
                continue
            matched = self.action._find_first_matching_node(
                root=search_root,
                auto_id=auto_id,
                control_type=None,
                title=None,
                title_match_mode="exact",
                legacy_value=None,
                legacy_match_mode="exact",
                case_sensitive=False,
            )
            if matched is not None:
                return matched
        return None

    def test_iter_attr_search_roots_top_includes_child_window(self) -> None:
        roots = self.action._iter_attr_search_roots(
            window_target="top",
            child_window_title=None,
            child_window_auto_id=None,
            child_window_match_mode="contains",
            case_sensitive=False,
            top_window_override=self.top,
        )
        labels = [label for _root, label in roots]
        self.assertEqual(labels[0], "top")
        self.assertTrue(any("Find" in label for label in labels[1:]))

    def test_find_btnnext_on_top_descendants(self) -> None:
        matched = self._find_by_auto_id(auto_id="btnNext")
        self.assertIsNotNone(matched)
        self.assertEqual(matched.element_info.automation_id, "btnNext")

    def test_find_close_only_under_find_child_root(self) -> None:
        top_only = self.action._find_first_matching_node(
            root=self.top,
            auto_id="Close",
            control_type=None,
            title=None,
            title_match_mode="exact",
            legacy_value=None,
            legacy_match_mode="exact",
            case_sensitive=False,
        )
        self.assertIsNone(top_only)

        matched = self._find_by_auto_id(auto_id="Close")
        self.assertIsNotNone(matched)
        self.assertEqual(matched.element_info.automation_id, "Close")

    def test_child_scoped_search_uses_single_root(self) -> None:
        roots = self.action._iter_attr_search_roots(
            window_target="child",
            child_window_title="Find",
            child_window_auto_id=None,
            child_window_match_mode="contains",
            case_sensitive=False,
            top_window_override=self.top,
        )
        self.assertEqual(len(roots), 1)
        root, label = roots[0]
        self.assertIsNotNone(root)
        self.assertIn("child", label)


if __name__ == "__main__":
    unittest.main()
