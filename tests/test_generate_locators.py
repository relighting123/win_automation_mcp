import sys
import unittest
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from scripts.generate_locators import (
    _build_click_app_by_attr_args,
    build_locator_tree,
    collect_all_descendant_records,
    count_tree_elements,
    extract_elements,
    flatten_tree_elements,
    iter_search_nodes,
    make_locator_key,
    node_to_record,
    resolve_target_windows,
)


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


class _MockTop(_MockNode):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._cached_descendants: list[_MockNode] | None = None

    def descendants(self):
        if self._cached_descendants is None:
            self._cached_descendants = [
                _MockNode(title="닫기", control_type="Button", control_id=2001, automation_id="Close"),
                _MockNode(title="", control_type="Pane", control_id=3001, automation_id=""),
                _MockNode(title="OK", control_type="Button", control_id=2002, automation_id="OK"),
            ]
        return self._cached_descendants


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


class GenerateLocatorsTest(unittest.TestCase):
    def test_iter_search_nodes_includes_root_and_descendants(self):
        top = _MockTop(title="Login", control_type="Window", control_id=1, automation_id="LoginWnd")
        nodes = iter_search_nodes(top, include_root=True)
        self.assertEqual(len(nodes), 4)
        self.assertIs(nodes[0], top)
        self.assertEqual(len(top.descendants()), 3)

    def test_collect_all_descendant_records(self):
        top = _MockTop(title="Login", control_type="Window", control_id=1, automation_id="LoginWnd")
        records = collect_all_descendant_records(top, include_root=True)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["auto_id"], "LoginWnd")
        self.assertEqual(records[0]["control_id"], "1")
        auto_ids = {record["auto_id"] for record in records}
        self.assertIn("Close", auto_ids)
        self.assertIn("OK", auto_ids)

    def test_node_to_record_uses_control_id_not_control_type_call(self):
        node = _MockNode(control_type="Button", control_id=999, automation_id="Btn1")
        record = node_to_record(node, index=0)
        self.assertEqual(record["control_id"], "999")
        self.assertEqual(record["uia_control_type"], "Button")
        self.assertNotIn("control_type", record)

    def test_build_locator_tree_flat_top(self):
        top = _MockTop(title="Login", control_type="Window", control_id=1, automation_id="LoginWnd")
        tree = build_locator_tree(top)
        self.assertEqual(tree["window"]["auto_id"], "LoginWnd")
        self.assertEqual(tree["scope"], "top")
        self.assertEqual(tree["window_target"], "top")
        self.assertIn("close", tree["elements"])
        self.assertEqual(tree["elements"]["close"]["scope"], "top")
        self.assertEqual(tree["elements"]["close"]["window_target"], "top")
        self.assertNotIn("child_windows", tree)

    def test_build_locator_tree_includes_child_windows(self):
        top = _MockMainWithFind()
        tree = build_locator_tree(top)
        self.assertIn("btnnext", tree["elements"])
        self.assertEqual(tree["elements"]["btnnext"]["scope"], "top")
        self.assertIn("find", tree["child_windows"])
        find_tree = tree["child_windows"]["find"]
        self.assertEqual(find_tree["scope"], "child")
        self.assertEqual(find_tree["window_target"], "child")
        self.assertEqual(find_tree["window"]["title"], "Find")
        self.assertIn("close", find_tree["elements"])
        self.assertEqual(find_tree["elements"]["close"]["scope"], "child")
        self.assertEqual(find_tree["elements"]["close"]["window_target"], "child")
        self.assertEqual(find_tree["elements"]["close"]["child_window_title"], "Find")
        self.assertEqual(find_tree["elements"]["close"]["path"], "top/child_windows/find")
        close_click = find_tree["elements"]["close"]["click_app_by_attr"]
        self.assertEqual(close_click["window_target"], "child")
        self.assertEqual(close_click["auto_id"], "Close")
        self.assertEqual(close_click["child_window_title"], "Find")
        self.assertTrue(close_click["allow_invisible_children"])
        self.assertEqual(
            find_tree["elements"]["close"]["click_skill_step"],
            {"tool": "click_app_by_attr", "args": close_click},
        )

    def test_build_click_app_by_attr_args_top_scope(self) -> None:
        args = _build_click_app_by_attr_args(
            scope="top",
            auto_id="btnnext",
            title="Next",
            uia_type="Button",
        )
        self.assertEqual(args["window_target"], "top")
        self.assertEqual(args["auto_id"], "btnnext")
        self.assertNotIn("allow_invisible_children", args)

    def test_build_click_app_by_attr_args_child_scope(self) -> None:
        args = _build_click_app_by_attr_args(
            scope="child",
            auto_id="buttonlogin",
            title="Login",
            uia_type="Button",
            child_window_title="ezDFS2 Login",
            child_window_auto_id="LoginDlg",
        )
        self.assertEqual(args["window_target"], "child")
        self.assertEqual(args["child_window_title"], "ezDFS2 Login")
        self.assertEqual(args["child_window_auto_id"], "LoginDlg")
        self.assertTrue(args["allow_invisible_children"])

    def test_extract_elements_flatten_includes_child_controls(self):
        top = _MockMainWithFind()
        elements = extract_elements(top)
        self.assertIn("btnnext", elements)
        self.assertIn("find__close", elements)

    def test_extract_elements_all_types(self):
        top = _MockTop()
        elements = extract_elements(top, all_types=True, include_without_auto_id=True)
        self.assertEqual(len(elements), 2)

    def test_count_tree_elements(self):
        top = _MockMainWithFind()
        tree = build_locator_tree(top)
        self.assertEqual(count_tree_elements(tree), 3)

    def test_flatten_tree_elements(self):
        top = _MockMainWithFind()
        tree = build_locator_tree(top)
        flat = flatten_tree_elements(tree)
        self.assertIn("find__close", flat)
        self.assertEqual(flat["find__close"]["auto_id"], "Close")
        self.assertEqual(flat["find__close"]["scope"], "child")
        self.assertEqual(flat["find__close"]["window_target"], "child")

    def test_make_locator_key_from_title(self):
        top = _MockTop(title="ezDFS2 Login", control_type="Window", control_id=1, automation_id="LoginWnd")
        self.assertEqual(make_locator_key(top, 0), "ezdfs2_login")

    def test_resolve_target_windows_default_all(self):
        wins = [_MockTop(title="Main"), _MockTop(title="Login")]
        resolved = resolve_target_windows(wins, window_index=None, title_contains=None, single_window=False)
        self.assertEqual(len(resolved), 2)

    def test_resolve_target_windows_single_mode(self):
        wins = [_MockTop(title="Main"), _MockTop(title="Login")]
        resolved = resolve_target_windows(wins, window_index=None, title_contains=None, single_window=True)
        self.assertEqual(len(resolved), 1)


if __name__ == "__main__":
    unittest.main()
