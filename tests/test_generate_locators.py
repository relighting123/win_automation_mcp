import sys
import unittest
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from scripts.generate_locators import (
    collect_all_descendant_records,
    extract_elements,
    iter_search_nodes,
    node_to_record,
)


class _Info:
    def __init__(self, *, control_type="Button", control_id=1001, automation_id="Close", handle=42):
        self.control_type = control_type
        self.control_id = control_id
        self.automation_id = automation_id
        self.handle = handle


class _MockNode:
    def __init__(self, *, title="", control_type="Button", control_id=1001, automation_id="Close", visible=True):
        self.element_info = _Info(control_type=control_type, control_id=control_id, automation_id=automation_id)
        self._title = title
        self._visible = visible

    def window_text(self):
        return self._title

    def is_visible(self):
        return self._visible

    def descendants(self):
        return []


class _MockTop(_MockNode):
    def descendants(self):
        return [
            _MockNode(title="닫기", control_type="Button", control_id=2001, automation_id="Close"),
            _MockNode(title="", control_type="Pane", control_id=3001, automation_id=""),
            _MockNode(title="OK", control_type="Button", control_id=2002, automation_id="OK"),
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


if __name__ == "__main__":
    unittest.main()
