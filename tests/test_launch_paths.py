import sys
import unittest
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.launch_paths import normalize_launch_path, pick_launch_target, resolve_launch_paths


class LaunchPathsTest(unittest.TestCase):
    def test_pick_launch_target_prefers_executable_path(self) -> None:
        target = pick_launch_target(
            {
                "executable_path": r"C:\Apps\Tool.exe",
                "file_path": r"D:\Rules\assign.rul",
            }
        )
        self.assertEqual(target, r"C:\Apps\Tool.exe")

    def test_pick_launch_target_uses_file_path_alias(self) -> None:
        target = pick_launch_target({"file_path": r"D:\Rules\assign.rul"})
        self.assertEqual(target, r"D:\Rules\assign.rul")

    def test_resolve_launch_paths_keeps_skill_rul_over_config_exe(self) -> None:
        target, connect, normalized = resolve_launch_paths(
            {"file_path": r"D:\Rules\assign.rul"},
            config_executable_path=r"C:\Apps\Tool.exe",
            config_connect_path=r"C:\Apps\Tool.exe",
        )
        self.assertEqual(target, r"D:\Rules\assign.rul")
        self.assertEqual(connect, r"C:\Apps\Tool.exe")
        self.assertEqual(normalized["executable_path"], r"D:\Rules\assign.rul")
        self.assertNotIn("file_path", normalized)

    def test_resolve_launch_paths_falls_back_to_config_when_missing(self) -> None:
        target, connect, _ = resolve_launch_paths(
            {},
            config_executable_path=r"C:\Apps\Tool.exe",
        )
        self.assertEqual(target, r"C:\Apps\Tool.exe")
        self.assertIsNone(connect)

    def test_normalize_launch_path_ignores_case(self) -> None:
        left = normalize_launch_path(r"D:\Rules\assign.rul")
        right = normalize_launch_path(r"d:\rules\assign.rul")
        self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()
