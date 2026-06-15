import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.llm_config import get_automation_settings


class AutomationModeConfigTest(unittest.TestCase):
    def test_get_automation_settings_reads_manual_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "app_config.yaml"
            config_path.write_text("automation:\n  mode: manual\n", encoding="utf-8")
            settings = get_automation_settings(str(config_path))
        self.assertEqual(settings["mode"], "manual")

    def test_get_automation_settings_normalizes_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "app_config.yaml"
            config_path.write_text("automation:\n  mode: ' Manual '\n", encoding="utf-8")
            settings = get_automation_settings(str(config_path))
        self.assertEqual(settings["mode"], "manual")

    def test_get_automation_settings_falls_back_to_app_session(self) -> None:
        session = type("Session", (), {"config": {"automation": {"mode": "manual"}}})()
        with patch("core.llm_config.load_app_config", return_value={}):
            with patch("core.app_session.AppSession.get_instance", return_value=session):
                settings = get_automation_settings()
        self.assertEqual(settings["mode"], "manual")


if __name__ == "__main__":
    unittest.main()
