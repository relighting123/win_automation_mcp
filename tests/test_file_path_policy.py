import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.file_path_policy import (
    ALLOWED_PATHS_ENV,
    get_allowed_file_roots,
    get_file_access_settings,
    is_path_allowed,
    resolve_allowed_file,
)


class FilePathPolicyTest(unittest.TestCase):
    def test_resolve_allowed_file_under_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            target = workspace / "src" / "demo.txt"
            target.parent.mkdir(parents=True)
            target.write_text("hello", encoding="utf-8")

            with patch(
                "core.file_path_policy.get_file_access_settings",
                return_value={"allow_workspace": True, "allowed_paths": []},
            ):
                resolved = resolve_allowed_file("src/demo.txt", workspace=workspace)

            self.assertEqual(resolved, target.resolve())

    def test_resolve_allowed_file_under_configured_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            allowed_root = Path(tmp).resolve() / "rules"
            allowed_root.mkdir()
            target = allowed_root / "assign.rul"
            target.write_text("rule", encoding="utf-8")
            workspace = Path(tmp).resolve() / "project"
            workspace.mkdir()

            with patch(
                "core.file_path_policy.get_file_access_settings",
                return_value={
                    "allow_workspace": False,
                    "allowed_paths": [str(allowed_root)],
                },
            ):
                resolved = resolve_allowed_file(str(target), workspace=workspace)

            self.assertEqual(resolved, target.resolve())

    def test_resolve_allowed_file_rejects_outside_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve() / "project"
            workspace.mkdir()
            outside = Path(tmp).resolve() / "outside.txt"
            outside.write_text("x", encoding="utf-8")

            with patch(
                "core.file_path_policy.get_file_access_settings",
                return_value={"allow_workspace": True, "allowed_paths": []},
            ):
                with self.assertRaises(ValueError):
                    resolve_allowed_file(str(outside), workspace=workspace)

    def test_get_allowed_file_roots_includes_workspace_and_config_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve() / "ws"
            workspace.mkdir()
            extra = Path(tmp).resolve() / "extra"
            extra.mkdir()

            with patch(
                "core.file_path_policy.get_file_access_settings",
                return_value={
                    "allow_workspace": True,
                    "allowed_paths": [str(extra)],
                },
            ):
                roots = get_allowed_file_roots(workspace=workspace)

            self.assertIn(workspace.resolve(), roots)
            self.assertIn(extra.resolve(), roots)

    def test_env_var_adds_exception_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve() / "project"
            workspace.mkdir()
            exception_dir = Path(tmp).resolve() / "rules"
            exception_dir.mkdir()
            target = exception_dir / "assign.rul"
            target.write_text("rule", encoding="utf-8")

            # 설정에는 예외 경로가 없지만 환경변수로 지정하면 허용되어야 함
            with patch(
                "core.file_path_policy.load_app_config",
                return_value={"file_access": {"allow_workspace": True, "allowed_paths": []}},
            ):
                with patch.dict(os.environ, {ALLOWED_PATHS_ENV: str(exception_dir)}):
                    settings = get_file_access_settings()
                    self.assertIn(str(exception_dir), settings["allowed_paths"])
                    resolved = resolve_allowed_file(str(target), workspace=workspace)
                    self.assertEqual(resolved, target.resolve())

    def test_env_var_supports_multiple_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp).resolve() / "a"
            second = Path(tmp).resolve() / "b"
            joined = os.pathsep.join([str(first), str(second)])
            with patch(
                "core.file_path_policy.load_app_config",
                return_value={"file_access": {"allow_workspace": True, "allowed_paths": []}},
            ):
                with patch.dict(os.environ, {ALLOWED_PATHS_ENV: joined}):
                    settings = get_file_access_settings()
            self.assertIn(str(first), settings["allowed_paths"])
            self.assertIn(str(second), settings["allowed_paths"])

    def test_is_path_allowed_uses_relative_to_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "root"
            root.mkdir()
            child = root / "child.txt"
            child.write_text("x", encoding="utf-8")
            sibling = Path(tmp).resolve() / "root_extra"
            sibling.mkdir()

            self.assertTrue(is_path_allowed(child, roots=[root]))
            self.assertFalse(is_path_allowed(sibling, roots=[root]))


if __name__ == "__main__":
    unittest.main()
