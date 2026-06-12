import sys
import unittest
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.app_session import AppSession
from skills.sequence_skill import SequenceSkill


class SequenceSkillArgsTest(unittest.TestCase):
    def _make_skill(self, steps):
        skill = SequenceSkill.__new__(SequenceSkill)
        skill.skill_name = "test_skill"
        skill.steps = steps
        skill.description = ""
        skill.instruction = ""
        return skill

    def test_get_steps_with_metadata_handles_null_args(self) -> None:
        skill = self._make_skill(
            [
                {"tool": "launch_application", "args": None},
                {"tool": "close_application"},
            ]
        )
        metadata = skill.get_steps_with_metadata({})
        self.assertEqual(len(metadata), 2)
        self.assertEqual(metadata[0]["tool"], "launch_application")
        self.assertEqual(metadata[0]["args"], {})
        self.assertEqual(metadata[1]["args"], {})

    def test_parse_step_handles_null_args(self) -> None:
        skill = self._make_skill([{"tool": "launch_application", "args": None}])
        parsed = skill._parse_step(skill.steps[0], {})
        self.assertEqual(parsed["tool"], "launch_application")
        self.assertEqual(parsed["args"], {})

    def test_normalize_step_args_rejects_non_dict(self) -> None:
        skill = self._make_skill([])
        with self.assertRaises(ValueError):
            skill._normalize_step_args({"tool": "launch_application", "args": "bad"})

    def test_parse_step_maps_file_path_alias_for_launch(self) -> None:
        skill = self._make_skill(
            [
                {
                    "tool": "launch_application",
                    "args": {
                        "file_path": { "mode": "fixed", "value": r"D:\Rules\assign.rul" },
                    },
                }
            ]
        )
        with patch.object(
            AppSession,
            "get_instance",
            return_value=type(
                "Session",
                (),
                {
                    "config": {
                        "application": {
                            "executable_path": r"C:\Apps\Tool.exe",
                            "connect_path": r"C:\Apps\Tool.exe",
                        }
                    }
                },
            )(),
        ):
            parsed = skill._parse_step(skill.steps[0], {})
        self.assertEqual(parsed["args"]["executable_path"], r"D:\Rules\assign.rul")
        self.assertEqual(parsed["args"]["connect_path"], r"C:\Apps\Tool.exe")


if __name__ == "__main__":
    unittest.main()
