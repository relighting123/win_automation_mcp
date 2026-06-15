import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

_tool_path = project_root / "tools" / "data_analysis_tool.py"
_spec = importlib.util.spec_from_file_location("data_analysis_tool", _tool_path)
assert _spec and _spec.loader
_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tool)


class ReadClipboardSaveJsonTest(unittest.IsolatedAsyncioTestCase):
    async def test_save_json_false_by_default(self) -> None:
        tab_text = "name\tvalue\nA\t1\nB\t2\n"
        with patch.object(_tool, "_read_clipboard_text", return_value=tab_text):
            raw = await _tool.read_clipboard_as_dataframe(save_json=False)
        result = json.loads(raw)
        self.assertTrue(result["success"])
        self.assertFalse(result["json_saved"])
        self.assertNotIn("json_path", result)

    async def test_save_json_writes_file(self) -> None:
        tab_text = "name\tvalue\nA\t1\nB\t2\n"
        with patch.object(_tool, "_read_clipboard_text", return_value=tab_text):
            with patch.object(_tool, "save_dataframe_json", return_value="/tmp/test.json") as mock_save:
                raw = await _tool.read_clipboard_as_dataframe(save_json=True)
        result = json.loads(raw)
        self.assertTrue(result["success"])
        self.assertTrue(result["json_saved"])
        self.assertEqual(result["json_path"], "/tmp/test.json")
        self.assertEqual(result["json_record_count"], 2)
        mock_save.assert_called_once()
        saved_records = mock_save.call_args.args[0]
        self.assertEqual(len(saved_records), 2)


if __name__ == "__main__":
    unittest.main()
