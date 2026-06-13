import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from actions.app_ui_action import AppUIAction


class _Info:
    def __init__(self, *, control_type="Window", control_id=2000, automation_id="FindDlg", handle=4242):
        self.control_type = control_type
        self.control_id = control_id
        self.automation_id = automation_id
        self.handle = handle
        self.runtime_id = (handle,)
        self.name = ""
        self.rich_text = ""
        self.class_name = ""


class _MockWindow:
    def __init__(self, *, title="Find", automation_id="FindDlg", handle=4242, exists=True):
        self.element_info = _Info(
            control_type="Window",
            control_id=2000,
            automation_id=automation_id,
            handle=handle,
        )
        self.handle = handle
        self._title = title
        self._exists = exists
        self.close_called = False

    def window_text(self):
        return self._title

    def is_visible(self):
        return True

    def exists(self):
        return self._exists

    def descendants(self):
        return []

    def children(self):
        return []

    def wrapper_object(self):
        return self

    def close(self):
        self.close_called = True
        self._exists = False


class _MockMain(_MockWindow):
    def __init__(self):
        super().__init__(title="Main", automation_id="MainWnd", handle=1111)
        self.find = _MockWindow(title="Find", automation_id="FindDlg", handle=4242)

    def children(self):
        return [self.find]

    def descendants(self):
        return [self.find]


class CloseWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        session = MagicMock()
        session.is_connected = True
        launcher = MagicMock()
        self.action = AppUIAction(session=session)
        self.action._launcher = launcher
        self.top = _MockMain()

    def test_close_find_child_via_wrapper_close(self) -> None:
        with patch.object(self.action, "_pick_target_window", return_value=self.top):
            result = self.action.close_window(
                window_target="child",
                child_window_title="Find",
                wait_for_close=False,
            )

        self.assertEqual(result.result, "success")
        self.assertTrue(self.top.find.close_called)

    def test_close_find_child_not_found(self) -> None:
        with patch.object(self.action, "_pick_target_window", return_value=self.top):
            result = self.action.close_window(
                window_target="child",
                child_window_title="MissingDialog",
                wait_for_close=False,
            )

        self.assertEqual(result.result, "not_found")
        self.assertIn("child_not_found", result.message or "")

    def test_close_window_wm_close_fallback(self) -> None:
        class _NoCloseWrapper(_MockWindow):
            def close(self):
                raise RuntimeError("close not supported")

        broken = _NoCloseWrapper(title="Find", automation_id="FindDlg", handle=9999)
        main = _MockMain()
        main.find = broken

        mock_win32gui = MagicMock()
        mock_win32gui.IsWindow.return_value = False

        with patch.object(self.action, "_pick_target_window", return_value=main):
            with patch.dict(sys.modules, {"win32gui": mock_win32gui}):
                result = self.action.close_window(
                    window_target="child",
                    child_window_title="Find",
                    timeout=0.2,
                )

        self.assertEqual(result.result, "success")
        mock_win32gui.PostMessage.assert_called_once_with(9999, 0x0010, 0, 0)

    def test_close_window_invalid_target(self) -> None:
        result = self.action.close_window(window_target="invalid")
        self.assertEqual(result.result, "error")
        self.assertIn("window_target", result.message or "")


if __name__ == "__main__":
    unittest.main()
