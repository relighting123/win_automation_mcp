"""
단일 백그라운드 asyncio 이벤트 루프에서 코루틴을 실행합니다.

chatRTD는 sync REPL이지만 MCP stdio 세션은 동일 루프에서 열고 닫아야
종료 시 'asynchronous generator' 오류를 피할 수 있습니다.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Coroutine, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_runner: Optional["AsyncLoopRunner"] = None
_runner_lock = threading.Lock()


class AsyncLoopRunner:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_forever,
            name="chatrtd-async-loop",
            daemon=True,
        )
        self._thread.start()

    def _run_forever(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def shutdown(self, timeout: float = 3.0) -> None:
        if self._loop.is_closed():
            return

        try:
            if self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=timeout)
        except Exception as exc:
            logger.debug("async loop thread join 실패: %s", exc)

        try:
            self._loop.close()
        except Exception as exc:
            logger.debug("async loop close 실패: %s", exc)


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    global _runner
    with _runner_lock:
        if _runner is None:
            _runner = AsyncLoopRunner()
        runner = _runner
    return runner.run(coro)


def shutdown_async_runner(timeout: float = 3.0) -> None:
    global _runner
    with _runner_lock:
        if _runner is None:
            return
        runner = _runner
        _runner = None
    runner.shutdown(timeout=timeout)
