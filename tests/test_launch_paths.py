import sys
import unittest
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.launch_paths import normalize_launch_path, pick_launch_target, resolve_launch_paths


class LaunchPathsTest(unittest.TestCase):
    def test_pick_launch_target_prefers_file_path(self) -> None:
        target = pick_launch_target(
            {
                "file_path": r"D:\Rules\assign.rul",
                "path": r"C:\Apps\Tool.exe",
            }
        )
        self.assertEqual(target, r"D:\Rules\assign.rul")

    def test_pick_launch_target_uses_path_alias(self) -> None:
        target = pick_launch_target({"file_path": r"D:\Rules\assign.rul"})
        self.assertEqual(target, r"D:\Rules\assign.rul")

    def test_resolve_launch_paths_keeps_skill_rul_with_connect_path(self) -> None:
        target, connect, normalized = resolve_launch_paths(
            {"file_path": r"D:\Rules\assign.rul"},
            config_connect_path=r"C:\Apps\Tool.exe",
        )
        self.assertEqual(target, r"D:\Rules\assign.rul")
        self.assertEqual(connect, r"C:\Apps\Tool.exe")
        self.assertEqual(normalized["file_path"], r"D:\Rules\assign.rul")
        self.assertNotIn("path", normalized)

    def test_resolve_launch_paths_uses_config_connect_path(self) -> None:
        target, connect, _ = resolve_launch_paths(
            {},
            config_connect_path=r"C:\Apps\Tool.exe",
        )
        self.assertEqual(target, "")
        self.assertEqual(connect, r"C:\Apps\Tool.exe")

    def test_resolve_launch_paths_strips_legacy_executable_path_key(self) -> None:
        _, _, normalized = resolve_launch_paths(
            {"executable_path": r"D:\Rules\legacy.rul"},
            config_connect_path=r"C:\Apps\Tool.exe",
        )
        self.assertNotIn("executable_path", normalized)
        self.assertEqual(normalized.get("file_path"), "")

    def test_normalize_launch_path_ignores_case(self) -> None:
        left = normalize_launch_path(r"D:\Rules\assign.rul")
        right = normalize_launch_path(r"d:\rules\assign.rul")
        self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()
