import unittest

from core.async_loop_runner import run_async, shutdown_async_runner


class AsyncLoopRunnerTest(unittest.TestCase):
    def tearDown(self) -> None:
        shutdown_async_runner()

    async def _async_add(self, a: int, b: int) -> int:
        return a + b

    def test_run_async_on_background_loop(self) -> None:
        result = run_async(self._async_add(2, 3))
        self.assertEqual(result, 5)

    def test_shutdown_and_rerun(self) -> None:
        self.assertEqual(run_async(self._async_add(1, 1)), 2)
        shutdown_async_runner()
        self.assertEqual(run_async(self._async_add(4, 5)), 9)


if __name__ == "__main__":
    unittest.main()
