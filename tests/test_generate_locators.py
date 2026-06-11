import sys
import unittest
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from scripts.generate_locators import (
    collect_all_descendant_records,
    extract_elements,
    iter_search_nodes,
    iter_search_roots,
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

    def descendants(self):
        return [
            _MockNode(title="Next", control_type="Button", control_id=2001, automation_id="btnNext"),
            _MockNode(title="닫기", control_type="Button", control_id=2002, automation_id="Close"),
        ]


class _MockMainWithFind(_MockNode):
    def __init__(self):
        super().__init__(title="", control_type="Window", control_id=1, automation_id="MainWnd")
        self.find = _MockFind()

    def children(self):
        return [self.find]

    def descendants(self):
        # top.descendants()에는 Find 내부 Close가 빠지는 케이스를 재현
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
        self.assertEqual(len(records), 4)
        self.assertEqual(records[0]["auto_id"], "LoginWnd")
        self.assertEqual(records[0]["control_id"], "1")
        self.assertEqual(records[1]["auto_id"], "Close")
        self.assertEqual(records[1]["control_id"], "2001")

    def test_node_to_record_uses_control_id_not_control_type_call(self):
        node = _MockNode(control_type="Button", control_id=999, automation_id="Btn1")
        record = node_to_record(node, index=0)
        self.assertEqual(record["control_id"], "999")
        self.assertEqual(record["uia_control_type"], "Button")
        self.assertNotIn("control_type", record)

    def test_extract_elements_filters_by_target_types(self):
        top = _MockTop()
        elements = extract_elements(top)
        self.assertEqual(len(elements), 2)
        self.assertEqual(elements["close"]["control_id"], "2001")
        self.assertEqual(elements["close"]["auto_id"], "Close")

    def test_extract_elements_all_types(self):
        top = _MockTop()
        elements = extract_elements(top, all_types=True, include_without_auto_id=True)
        self.assertEqual(len(elements), 3)

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

    def test_iter_search_roots_includes_child_window(self):
        top = _MockMainWithFind()
        roots = iter_search_roots(top)
        self.assertGreaterEqual(len(roots), 2)
        self.assertTrue(any("Find" in label for label, _ in roots))

    def test_collect_includes_controls_under_child_window(self):
        top = _MockMainWithFind()
        records = collect_all_descendant_records(top, include_root=True)
        auto_ids = {record["auto_id"] for record in records}
        self.assertIn("btnNext", auto_ids)
        self.assertIn("Close", auto_ids)
        close_records = [record for record in records if record["auto_id"] == "Close"]
        self.assertTrue(
            any("Find" in record["search_root"] for record in close_records),
            f"Close should be collected under Find child root, got: {close_records}",
        )

    def test_extract_elements_includes_close_from_child_window(self):
        top = _MockMainWithFind()
        elements = extract_elements(top)
        self.assertIn("btnnext", elements)
        self.assertIn("close", elements)


if __name__ == "__main__":
    unittest.main()
