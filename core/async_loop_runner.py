"""
단일 백그라운드 asyncio 이벤트 루프에서 코루틴을 실행합니다.

chatRTD는 sync REPL이지만 MCP stdio 세션은 동일 루프에서 열고 닫아야
종료 시 'asynchronous generator' 오류를 피할 수 있습니다.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
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
        from core.automation_run_control import drain_overlay_shutdown, pump_overlay

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        while not future.done():
            try:
                pump_overlay()
                future.result(timeout=0.02)
            except FutureTimeoutError:
                continue
            except KeyboardInterrupt:
                if not self._on_keyboard_interrupt(future):
                    raise
                continue
        try:
            return future.result()
        finally:
            drain_overlay_shutdown()

    def _on_keyboard_interrupt(self, future: Any) -> bool:
        """실행 중 Ctrl+C 처리.

        대화형(semi/manual) 자동화가 진행 중이면 종료 대신 일시정지/재개/중지로
        해석합니다. 그런 세션이 없으면 기존처럼 실행을 취소하고 종료를 전파합니다.

        Returns: True면 루프를 계속 유지, False면 KeyboardInterrupt를 다시 전파.
        """
        from core.automation_run_control import get_active_control

        control = get_active_control()
        if control is None:
            # 대화형 자동화가 아니면 코루틴을 취소하고 종료를 전파합니다.
            self._loop.call_soon_threadsafe(future.cancel)
            return False

        # 이미 중지 요청 상태에서 또 Ctrl+C를 눌렀다면 강제 종료 탈출구 제공.
        if control.peek_stop():
            self._loop.call_soon_threadsafe(future.cancel)
            return False

        action = control.on_ctrl_c()
        message = {
            "pause": (
                "\n  ⏸  일시정지됨 · 재개하려면 Ctrl+C, "
                "중지하려면 Ctrl+C를 빠르게 두 번 누르세요."
            ),
            "resume": "\n  ▶  재개됨.",
            "stop": "\n  ■  중지 요청됨. 안전하게 마무리하는 중…",
        }.get(action, "")
        if message:
            try:
                print(message, flush=True)
            except Exception:
                pass
        return True

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
