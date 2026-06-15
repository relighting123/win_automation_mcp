"""semi/manual 자동화 실행 중 사용자 개입(일시정지/중지/스킵) 제어."""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_active_control: Optional["AutomationRunControl"] = None
_active_lock = threading.RLock()


def overlay_supported() -> bool:
    return sys.platform == "win32"


class AutomationRunControl:
    """자동화 그래프 실행 세션의 사용자 제어 상태."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._paused = False
        self._stop_requested = False
        self._skip_skill_requested = False
        self._overlay: Any = None
        self.mode = ""
        self.skill_id = ""
        self.phase = ""
        self.step_index = 0
        self.step_total = 0

    def start_overlay(self) -> None:
        if not overlay_supported():
            logger.info("자동화 오버레이 UI는 Windows에서만 표시됩니다.")
            return
        try:
            from core.automation_control_overlay_ui import AutomationControlOverlay

            self._overlay = AutomationControlOverlay(self)
            self._overlay.start()
        except Exception as exc:
            logger.warning("자동화 오버레이 UI 시작 실패: %s", exc)
            self._overlay = None

    def stop_overlay(self) -> None:
        if self._overlay is not None:
            try:
                self._overlay.stop()
            except Exception as exc:
                logger.debug("오버레이 종료 중 오류: %s", exc)
            self._overlay = None

    def set_context(
        self,
        *,
        skill_id: str = "",
        phase: str = "",
        step_index: int = 0,
        step_total: int = 0,
        mode: str = "",
    ) -> None:
        with self._lock:
            if skill_id:
                self.skill_id = skill_id
            if phase:
                self.phase = phase
            self.step_index = step_index
            self.step_total = step_total
            if mode:
                self.mode = mode
        self._sync_overlay()

    def pause(self) -> None:
        with self._lock:
            self._paused = True
        self._sync_overlay()

    def resume(self) -> None:
        with self._lock:
            self._paused = False
        self._sync_overlay()

    def toggle_pause(self) -> None:
        with self._lock:
            self._paused = not self._paused
        self._sync_overlay()

    def request_stop(self) -> None:
        with self._lock:
            self._stop_requested = True
            self._paused = False
        self._sync_overlay()

    def request_skip_skill(self) -> None:
        with self._lock:
            self._skip_skill_requested = True
            self._paused = False
        self._sync_overlay()

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def peek_stop(self) -> bool:
        with self._lock:
            return self._stop_requested

    def peek_skip_skill(self) -> bool:
        with self._lock:
            return self._skip_skill_requested

    def consume_stop(self) -> bool:
        with self._lock:
            if self._stop_requested:
                self._stop_requested = False
                return True
            return False

    def consume_skip_skill(self) -> bool:
        with self._lock:
            if self._skip_skill_requested:
                self._skip_skill_requested = False
                return True
            return False

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "mode": self.mode,
                "skill_id": self.skill_id,
                "phase": self.phase,
                "step_index": self.step_index,
                "step_total": self.step_total,
                "paused": self._paused,
                "stop_requested": self._stop_requested,
                "skip_skill_requested": self._skip_skill_requested,
            }

    async def wait_if_paused(self) -> None:
        while self.is_paused():
            if self.peek_stop() or self.peek_skip_skill():
                return
            await asyncio.sleep(0.1)

    def _sync_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.schedule_update()


def begin_run_control(mode: str) -> Optional[AutomationRunControl]:
    global _active_control
    normalized = (mode or "").strip().lower()
    if normalized not in {"semi", "manual"}:
        return None

    with _active_lock:
        end_run_control()
        control = AutomationRunControl()
        control.mode = normalized
        control.start_overlay()
        _active_control = control
        logger.info("사용자 개입 컨트롤 시작 (mode=%s)", normalized)
        return control


def end_run_control() -> None:
    global _active_control
    with _active_lock:
        if _active_control is not None:
            _active_control.stop_overlay()
            _active_control = None
            logger.info("사용자 개입 컨트롤 종료")


def get_active_control() -> Optional[AutomationRunControl]:
    return _active_control
