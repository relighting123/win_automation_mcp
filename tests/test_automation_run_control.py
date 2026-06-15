import asyncio
import sys
import unittest
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.automation_run_control import (
    AutomationRunControl,
    begin_run_control,
    end_run_control,
    get_active_control,
)


class AutomationRunControlTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        end_run_control()

    def test_begin_run_control_only_for_semi_manual(self) -> None:
        self.assertIsNone(begin_run_control("auto"))
        control = begin_run_control("semi")
        self.assertIsNotNone(control)
        self.assertIs(control, get_active_control())
        end_run_control()
        self.assertIsNone(get_active_control())

    async def test_wait_if_paused_unblocks_on_resume(self) -> None:
        control = AutomationRunControl()
        control.pause()

        async def _resume_later() -> None:
            await asyncio.sleep(0.05)
            control.resume()

        waiter = asyncio.create_task(control.wait_if_paused())
        resumer = asyncio.create_task(_resume_later())
        await asyncio.wait_for(waiter, timeout=1.0)
        await resumer

    def test_stop_and_skip_flags(self) -> None:
        control = AutomationRunControl()
        control.request_stop()
        self.assertTrue(control.consume_stop())
        self.assertFalse(control.consume_stop())

        control.request_skip_skill()
        self.assertTrue(control.consume_skip_skill())


if __name__ == "__main__":
    unittest.main()
