import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def draw_outline(self, colour: str = "red"):
        self._last_outline_colour = colour

    def set_focus(self):
        return None

    def click_input(self, button="left"):
        return None


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


class ClickAppByAttrOutlineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock()
        self.session.config = {"timeouts": {"ui_delay": 0.01, "after_focus_delay": 0.01}}
        self.action = AppUIAction(session=self.session)
        self.top = _MockMainWithFind()

    def _run_click(self, **kwargs):
        defaults = {
            "auto_id": "Close",
            "window_target": "top",
            "draw_outline": True,
            "timeout": 0.1,
        }
        defaults.update(kwargs)
        with patch.object(self.action, "ensure_focus", return_value=MagicMock(result="success", is_success=True)):
            with patch.object(self.action, "_iter_process_top_windows", return_value=[self.top]):
                return self.action.click_element_by_attr(**defaults)

    def test_invalid_outline_scope_returns_error(self) -> None:
        result = self._run_click(outline_scope="invalid")
        self.assertEqual(result.result, "error")
        self.assertIn("outline_scope", result.message or "")

    def test_outline_scope_search_highlights_roots_only(self) -> None:
        result = self._run_click(outline_scope="search")
        self.assertEqual(result.result, "success")
        self.assertEqual(getattr(self.top, "_last_outline_colour", None), "green")
        close_node = self.top.find._cached_descendants[1]
        self.assertIsNone(getattr(close_node, "_last_outline_colour", None))

    def test_outline_scope_all_highlights_roots_and_target(self) -> None:
        result = self._run_click(outline_scope="all", outline_colour="red", search_outline_colour="green")
        self.assertEqual(result.result, "success")
        self.assertEqual(getattr(self.top, "_last_outline_colour", None), "green")
        close_node = self.top.find._cached_descendants[1]
        self.assertEqual(getattr(close_node, "_last_outline_colour", None), "red")

    def test_outline_scope_target_highlights_matched_element_only(self) -> None:
        result = self._run_click(outline_scope="target")
        self.assertEqual(result.result, "success")
        self.assertIsNone(getattr(self.top, "_last_outline_colour", None))
        close_node = self.top.find._cached_descendants[1]
        self.assertEqual(getattr(close_node, "_last_outline_colour", None), "red")


class ClickAppByAttrPollingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock()
        self.session.config = {"timeouts": {"ui_delay": 0.0, "after_focus_delay": 0.0}}
        self.action = AppUIAction(session=self.session)
        self.top = _MockMainWithFind()

    @staticmethod
    def _poll_sleep_calls(sleep_mock) -> list:
        return [call for call in sleep_mock.call_args_list if call.args and call.args[0] > 0]

    def _run_click(self, **kwargs):
        defaults = {
            "auto_id": "Close",
            "window_target": "top",
            "draw_outline": False,
        }
        defaults.update(kwargs)
        with patch.object(self.action, "ensure_focus", return_value=MagicMock(result="success", is_success=True)):
            with patch.object(self.action, "_iter_process_top_windows", return_value=[self.top]):
                with patch.object(self.action, "_click_with_preferred_action", return_value="click_input"):
                    return self.action.click_element_by_attr(**defaults)

    def test_timeout_none_performs_single_attempt_without_sleep(self) -> None:
        with patch("actions.app_ui_action.time.sleep") as sleep_mock:
            result = self._run_click(timeout=None)
        self.assertEqual(result.result, "success")
        self.assertEqual(self._poll_sleep_calls(sleep_mock), [])

    def test_poll_interval_zero_skips_sleep_between_retries(self) -> None:
        with patch("actions.app_ui_action.time.sleep") as sleep_mock:
            result = self._run_click(timeout=0.1, poll_interval=0)
        self.assertEqual(result.result, "success")
        self.assertEqual(self._poll_sleep_calls(sleep_mock), [])

    def test_poll_interval_null_uses_default_sleep_when_polling(self) -> None:
        close_node = self.top.find._cached_descendants[1]
        with patch("actions.app_ui_action.time.sleep") as sleep_mock:
            with patch.object(
                self.action,
                "_find_first_matching_node",
                side_effect=[None, None, close_node],
            ):
                with patch("actions.app_ui_action.time.monotonic", side_effect=[0.0, 0.0, 0.3]):
                    result = self._run_click(timeout=1.0, poll_interval=None)
        self.assertEqual(result.result, "success")
        self.assertEqual([call.args[0] for call in self._poll_sleep_calls(sleep_mock)], [0.2])

    def test_string_timeout_and_poll_interval_enable_polling(self) -> None:
        with patch("actions.app_ui_action.time.sleep") as sleep_mock:
            result = self._run_click(timeout="20", poll_interval="1")
        self.assertEqual(result.result, "success")
        self.assertEqual(self._poll_sleep_calls(sleep_mock), [])

    def test_focus_failure_continues_polling_until_element_found(self) -> None:
        focus_results = [
            MagicMock(result="error", is_success=False, message="no window"),
            MagicMock(result="success", is_success=True),
        ]
        with patch("actions.app_ui_action.time.sleep") as sleep_mock:
            with patch.object(self.action, "ensure_focus", side_effect=focus_results):
                with patch.object(self.action, "_iter_process_top_windows", return_value=[self.top]):
                    with patch.object(self.action, "_click_with_preferred_action", return_value="click_input"):
                        result = self.action.click_element_by_attr(
                            auto_id="Close",
                            window_target="top",
                            timeout=5.0,
                            poll_interval=1.0,
                        )
        self.assertEqual(result.result, "success")
        self.assertEqual([call.args[0] for call in self._poll_sleep_calls(sleep_mock)], [1.0])

    def test_not_found_polls_until_timeout(self) -> None:
        clock = {"now": 0.0}

        def fake_monotonic() -> float:
            return clock["now"]

        def fake_sleep(seconds: float) -> None:
            clock["now"] += seconds

        with patch("actions.app_ui_action.time.monotonic", side_effect=fake_monotonic):
            with patch("actions.app_ui_action.time.sleep", side_effect=fake_sleep):
                with patch.object(self.action, "_find_first_matching_node", return_value=None):
                    result = self._run_click(auto_id="Missing", timeout=2.0, poll_interval=1.0)
        self.assertEqual(result.result, "error")
        self.assertIn("찾지 못했습니다", result.message or "")


if __name__ == "__main__":
    unittest.main()
