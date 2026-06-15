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

_parse_dataframe_from_json = _tool._parse_dataframe_from_json
_resolve_json_payload = _tool._resolve_json_payload
_extract_by_records_path = _tool._extract_by_records_path


class JsonDataframeParseTest(unittest.TestCase):
    def test_records_array(self) -> None:
        df, fmt = _parse_dataframe_from_json(
            [{"name": "A", "value": 1}, {"name": "B", "value": 2}]
        )
        self.assertEqual(fmt, "json_records")
        self.assertEqual(df.shape, (2, 2))
        self.assertEqual(list(df.columns), ["name", "value"])

    def test_columns_and_data(self) -> None:
        df, fmt = _parse_dataframe_from_json(
            {"columns": ["x", "y"], "data": [[1, 2], [3, 4]]}
        )
        self.assertEqual(fmt, "json.columns_data")
        self.assertEqual(df.iloc[0]["x"], 1)

    def test_records_path(self) -> None:
        payload = {"result": {"items": [{"id": 10}, {"id": 20}]}}
        target = _extract_by_records_path(payload, "result.items")
        df, _fmt = _parse_dataframe_from_json(target)
        self.assertEqual(df.shape[0], 2)

    def test_resolve_json_text(self) -> None:
        payload = _resolve_json_payload(json_text='{"records":[{"a":1}]}')
        self.assertIn("records", payload)


class LoadJsonAsDataframeToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_load_json_as_dataframe_success(self) -> None:
        with patch.object(_tool, "save_dataset") as mock_save:
            raw = await _tool.load_json_as_dataframe(
                json_data={"records": [{"col": "v1"}, {"col": "v2"}]},
                max_preview_rows=5,
            )
        result = json.loads(raw)
        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "json")
        self.assertEqual(result["shape"]["rows"], 2)
        mock_save.assert_called_once()

    async def test_get_cached_dataset_summary_empty(self) -> None:
        with patch.object(_tool, "load_dataset", return_value=None):
            raw = await _tool.get_cached_dataset_summary()
        result = json.loads(raw)
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
