import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.app_launcher import AppLauncher
from core.app_session import AppSession, SessionState


class AppSessionLaunchTest(unittest.TestCase):
    def setUp(self) -> None:
        AppSession.reset_instance()
        self.session = AppSession()
        self.session._config = {
            "application": {
                "connect_path": r"C:\Apps\Tool.exe",
                "startup_timeout": 5,
            },
            "timeouts": {"after_focus_delay": 0.01},
        }

    def tearDown(self) -> None:
        AppSession.reset_instance()

    def test_resolve_connect_executable_path_prefers_connect_path(self) -> None:
        resolved = self.session._resolve_connect_executable_path(r"D:\Other\Tool.exe")
        self.assertEqual(resolved, r"D:\Other\Tool.exe")

    def test_resolve_connect_executable_path_uses_config_connect_path(self) -> None:
        resolved = self.session._resolve_connect_executable_path()
        self.assertEqual(resolved, r"C:\Apps\Tool.exe")

    def test_start_data_file_uses_startfile_and_connect_exe(self) -> None:
        data_file = r"D:\Rules\assign.rul"
        fake_app = MagicMock()
        fake_app.windows.return_value = [MagicMock()]
        mock_pywinauto = MagicMock()
        mock_pywinauto.Application.return_value = fake_app
        with patch.dict(sys.modules, {"pywinauto": mock_pywinauto}):
            with patch("os.startfile", create=True) as mock_startfile:
                with patch.object(self.session, "_try_connect", return_value=True) as mock_connect:
                    with patch("core.wait_utils.wait_until", side_effect=lambda condition, **_: condition()):
                        self.session.start(path=data_file, connect_path=r"C:\Apps\Tool.exe")

        mock_startfile.assert_called_once_with(data_file)
        mock_connect.assert_called()
        self.assertEqual(mock_connect.call_args.kwargs.get("path"), r"C:\Apps\Tool.exe")
        self.assertEqual(self.session.state, SessionState.CONNECTED)

    def test_start_data_file_requires_connect_path(self) -> None:
        self.session._config["application"].pop("connect_path", None)

        from errors.automation_error import ConnectionError

        mock_pywinauto = MagicMock()
        with patch.dict(sys.modules, {"pywinauto": mock_pywinauto}):
            with self.assertRaises(ConnectionError):
                self.session.start(path=r"D:\Rules\assign.rul")

    def test_open_associated_file_calls_startfile_when_connected(self) -> None:
        self.session._state = SessionState.CONNECTED
        self.session._app = MagicMock()
        with patch("os.startfile", create=True) as mock_startfile:
            with patch.object(self.session, "_bring_to_front") as mock_focus:
                self.session.open_associated_file(r"D:\Rules\report.rul")
        mock_startfile.assert_called_once_with(r"D:\Rules\report.rul")
        mock_focus.assert_called_once()
        self.assertFalse(self.session._skipped_data_file_reopen)

    def test_open_associated_file_skips_reopen_for_same_data_file(self) -> None:
        self.session._state = SessionState.CONNECTED
        self.session._app = MagicMock()
        self.session._last_opened_data_file = self.session._normalize_data_file_path(
            r"D:\Rules\report.rul"
        )
        with patch("os.startfile", create=True) as mock_startfile:
            with patch.object(self.session, "_bring_to_front") as mock_focus:
                self.session.open_associated_file(r"D:\Rules\report.rul")
        mock_startfile.assert_not_called()
        mock_focus.assert_called_once()
        self.assertTrue(self.session._skipped_data_file_reopen)

    def test_open_associated_file_force_reopens_same_data_file(self) -> None:
        self.session._state = SessionState.CONNECTED
        self.session._app = MagicMock()
        self.session._last_opened_data_file = self.session._normalize_data_file_path(
            r"D:\Rules\report.rul"
        )
        with patch("os.startfile", create=True) as mock_startfile:
            with patch.object(self.session, "_bring_to_front"):
                self.session.open_associated_file(r"D:\Rules\report.rul", force=True)
        mock_startfile.assert_called_once_with(r"D:\Rules\report.rul")
        self.assertFalse(self.session._skipped_data_file_reopen)

    def test_launcher_reopens_data_file_when_already_connected(self) -> None:
        launcher = AppLauncher(session=self.session)
        self.session._state = SessionState.CONNECTED
        self.session._app = MagicMock()
        with patch.object(self.session, "open_associated_file", return_value=self.session) as mock_open:
            result = launcher.launch(path=r"D:\Rules\report.rul")
        mock_open.assert_called_once()
        self.assertFalse(mock_open.call_args.kwargs.get("force"))
        self.assertIs(result, self.session)

    def test_launcher_can_force_reopen_data_file_when_already_connected(self) -> None:
        launcher = AppLauncher(session=self.session)
        self.session._state = SessionState.CONNECTED
        self.session._app = MagicMock()
        with patch.object(self.session, "open_associated_file", return_value=self.session) as mock_open:
            launcher.launch(path=r"D:\Rules\report.rul", reopen_data_file=True)
        self.assertTrue(mock_open.call_args.kwargs.get("force"))


if __name__ == "__main__":
    unittest.main()
