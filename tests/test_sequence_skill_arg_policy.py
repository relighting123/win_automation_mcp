import tempfile
import textwrap
import unittest
from pathlib import Path

from skills.sequence_skill import SequenceSkill


class TestSequenceSkillArgPolicy(unittest.TestCase):
    def _write_temp_skill_config(self, content: str) -> str:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        config_path = Path(tmp_dir.name) / "skills.yaml"
        config_path.write_text(textwrap.dedent(content), encoding="utf-8")
        return str(config_path)

    def test_fixed_arg_is_not_runtime_rendered(self):
        config_path = self._write_temp_skill_config(
            """
            skills:
              sample_skill:
                tools:
                  - tool: click_app_by_attr
                    args:
                      title: "Save {username}"
                      button: "{button}"
                    arg_policy:
                      title: fixed
                      button: mutable
            """
        )
        skill = SequenceSkill("sample_skill", config_path=config_path, action=object())
        parsed = skill._parse_step(skill.steps[0], {"username": "alice", "button": "right"})

        self.assertEqual(parsed["args"]["title"], "Save {username}")
        self.assertEqual(parsed["args"]["button"], "right")

    def test_default_policy_is_mutable(self):
        config_path = self._write_temp_skill_config(
            """
            skills:
              sample_skill:
                tools:
                  - tool: type_app_text
                    args:
                      text: "hello {username}"
            """
        )
        skill = SequenceSkill("sample_skill", config_path=config_path, action=object())
        parsed = skill._parse_step(skill.steps[0], {"username": "bob"})
        self.assertEqual(parsed["args"]["text"], "hello bob")

    def test_unknown_arg_policy_key_raises(self):
        config_path = self._write_temp_skill_config(
            """
            skills:
              sample_skill:
                tools:
                  - tool: click_app_by_attr
                    args:
                      title: "Save"
                    arg_policy:
                      missing_arg: fixed
            """
        )
        skill = SequenceSkill("sample_skill", config_path=config_path, action=object())
        with self.assertRaises(ValueError):
            skill.get_step_definitions()


if __name__ == "__main__":
    unittest.main()
