import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from graph.nodes import GraphNodes


class GraphLaunchArgsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.nodes = GraphNodes(mcp=MagicMock(), execution_llm=MagicMock())

    def test_apply_step_arg_constraints_uses_yaml_default_when_llm_returns_empty_file_path(self) -> None:
        args = self.nodes._apply_step_arg_constraints(
            {"file_path": ""},
            {
                "file_path": {
                    "mode": "ai",
                    "value": r"D:\Rules\assign.rul",
                }
            },
        )
        self.assertEqual(args["file_path"], r"D:\Rules\assign.rul")

    def test_apply_step_arg_constraints_maps_legacy_executable_path(self) -> None:
        args = self.nodes._apply_step_arg_constraints(
            {"executable_path": r"D:\Rules\legacy.rul"},
            {
                "file_path": {
                    "mode": "fixed",
                    "value": r"D:\Rules\assign.rul",
                }
            },
        )
        self.assertEqual(args["file_path"], r"D:\Rules\assign.rul")

    def test_build_calls_from_steps_keeps_fixed_file_path_without_llm(self) -> None:
        calls = self.nodes._build_calls_from_steps(
            [
                {
                    "tool": "launch_application",
                    "args": {
                        "file_path": {
                            "mode": "fixed",
                            "value": r"D:\Rules\assign.rul",
                        }
                    },
                }
            ],
            llm_calls=[],
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args.get("file_path"), r"D:\Rules\assign.rul")


if __name__ == "__main__":
    unittest.main()
