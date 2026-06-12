import sys
import unittest
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

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


if __name__ == "__main__":
    unittest.main()
