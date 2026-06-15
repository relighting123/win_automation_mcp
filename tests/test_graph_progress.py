import importlib.util
import sys
import unittest
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

_progress_path = project_root / "graph" / "progress.py"
_spec = importlib.util.spec_from_file_location("graph_progress", _progress_path)
assert _spec and _spec.loader
_progress_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_progress_module)
format_graph_progress_event = _progress_module.format_graph_progress_event


class GraphProgressFormatTest(unittest.TestCase):
    def test_plan_shows_skill_ids(self) -> None:
        lines = format_graph_progress_event(
            "plan",
            {"skill_ids": ["login_skill", "open_data"]},
            context={},
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("login_skill", lines[0])
        self.assertIn("open_data", lines[0])

    def test_run_shows_only_new_history_entries(self) -> None:
        context = {"history_len": 0}
        lines = format_graph_progress_event(
            "run",
            {
                "history": [
                    {
                        "skill": "login_skill",
                        "tool": "launch_application",
                        "output": {"success": True, "message": "ok"},
                    },
                    {
                        "skill": "login_skill",
                        "tool": "click_app_by_attr",
                        "output": {"success": False, "message": "not found"},
                    },
                ]
            },
            context=context,
        )
        self.assertEqual(len(lines), 2)
        self.assertIn("launch_application", lines[0])
        self.assertTrue(lines[0].endswith("|ok"))
        self.assertIn("click_app_by_attr", lines[1])
        self.assertTrue(lines[1].endswith("|err"))
        self.assertEqual(context["history_len"], 2)

        more = format_graph_progress_event(
            "run",
            {
                "history": [
                    {
                        "skill": "login_skill",
                        "tool": "launch_application",
                        "output": {"success": True},
                    },
                    {
                        "skill": "login_skill",
                        "tool": "click_app_by_attr",
                        "output": {"success": False},
                    },
                    {
                        "skill": "login_skill",
                        "tool": "wait",
                        "output": {"success": True},
                    },
                ]
            },
            context=context,
        )
        self.assertEqual(len(more), 1)
        self.assertIn("wait", more[0])


if __name__ == "__main__":
    unittest.main()
