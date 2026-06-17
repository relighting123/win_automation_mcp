"""Windows 화면 상단 always-on-top 자동화 제어 오버레이."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.automation_run_control import AutomationRunControl

logger = logging.getLogger(__name__)

_OVERLAY_WIDTH = 420
_OVERLAY_HEIGHT = 56


class AutomationControlOverlay:
    """
    Tk 오버레이.

    Windows tkinter는 생성·갱신 스레드에서 mainloop/update가 돌아야 합니다.
    별도 daemon 스레드 + after 폴링 대신, 메인 스레드 pump()로 이벤트를 처리합니다.
    """

    def __init__(self, control: "AutomationRunControl") -> None:
        self._control = control
        self._root: tk.Tk | None = None
        self._status_var: tk.StringVar | None = None
        self._pause_btn: ttk.Button | None = None
        self._commands: queue.Queue[str] = queue.Queue()
        self._closing = False
        self._shutdown_done = threading.Event()
        self._ui_thread = threading.main_thread()

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown_done.is_set()

    def start(self) -> None:
        """첫 pump() 호출 시 UI가 생성됩니다."""
        self._closing = False
        self._shutdown_done.clear()

    def stop(self) -> None:
        if self._closing and self._shutdown_done.is_set():
            return
        self._closing = True
        try:
            self._commands.put_nowait("stop")
        except queue.Full:
            self._commands.put("stop")
        if threading.current_thread() is self._ui_thread:
            self.pump()

    def wait_shutdown(self, timeout: float = 5.0) -> None:
        self._shutdown_done.wait(timeout=timeout)

    def schedule_update(self) -> None:
        if self._closing or self._shutdown_done.is_set():
            return
        try:
            self._commands.put_nowait("update")
        except queue.Full:
            pass
        if threading.current_thread() is self._ui_thread and self._root is not None:
            self.pump()

    def pump(self) -> None:
        """메인 스레드에서 주기적으로 호출해 큐 처리 및 Tk update를 수행합니다."""
        if threading.current_thread() is not self._ui_thread:
            return
        if self._shutdown_done.is_set():
            return
        if self._root is None and not self._closing:
            self._create_ui()
        if self._root is None:
            return
        self._process_commands()

    def _create_ui(self) -> None:
        try:
            root = tk.Tk()
            self._root = root
            root.title("chatRTD Control")
            root.attributes("-topmost", True)
            root.overrideredirect(True)
            try:
                root.attributes("-alpha", 0.92)
            except tk.TclError:
                pass

            screen_w = root.winfo_screenwidth()
            x = max(0, (screen_w - _OVERLAY_WIDTH) // 2)
            root.geometry(f"{_OVERLAY_WIDTH}x{_OVERLAY_HEIGHT}+{x}+8")

            frame = ttk.Frame(root, padding=(8, 6))
            frame.pack(fill="both", expand=True)

            self._status_var = tk.StringVar(value="chatRTD 자동화 준비")
            status = ttk.Label(frame, textvariable=self._status_var, width=34)
            status.pack(side="left", padx=(0, 8))

            btn_frame = ttk.Frame(frame)
            btn_frame.pack(side="right")

            self._pause_btn = ttk.Button(
                btn_frame,
                text="⏸",
                width=3,
                command=self._on_toggle_pause,
            )
            self._pause_btn.pack(side="left", padx=2)

            ttk.Button(
                btn_frame,
                text="⏭",
                width=3,
                command=self._control.request_skip_skill,
            ).pack(side="left", padx=2)

            ttk.Button(
                btn_frame,
                text="⏹",
                width=3,
                command=self._control.request_stop,
            ).pack(side="left", padx=2)

            self._refresh_labels()
            root.update_idletasks()
        except Exception as exc:
            logger.warning("자동화 오버레이 UI 생성 실패: %s", exc)
            self._root = None
            self._shutdown_done.set()

    def _shutdown_ui(self, root: tk.Tk) -> None:
        try:
            for after_id in root.tk.call("after", "info"):
                try:
                    root.after_cancel(after_id)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass
        self._root = None
        self._status_var = None
        self._pause_btn = None

    def _process_commands(self) -> None:
        root = self._root
        if root is None:
            return

        should_stop = False
        try:
            while True:
                command = self._commands.get_nowait()
                if command == "stop":
                    should_stop = True
                    break
                if command == "update" and not self._closing:
                    self._refresh_labels()
        except queue.Empty:
            pass

        try:
            if should_stop or self._closing:
                self._shutdown_ui(root)
                self._shutdown_done.set()
                return

            root.update()
        except RuntimeError as exc:
            if "main loop" in str(exc).lower():
                logger.debug("오버레이 update 중 mainloop 종료 감지: %s", exc)
                self._shutdown_ui(root)
                self._shutdown_done.set()
            else:
                raise
        except tk.TclError as exc:
            logger.debug("오버레이 update 중 Tcl 오류 (무시): %s", exc)
            self._shutdown_ui(root)
            self._shutdown_done.set()

    def _on_toggle_pause(self) -> None:
        self._control.toggle_pause()
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        if self._status_var is None or self._root is None:
            return
        snap = self._control.snapshot()
        skill = snap.get("skill_id") or "-"
        phase = snap.get("phase") or "ready"
        step_index = int(snap.get("step_index") or 0)
        step_total = int(snap.get("step_total") or 0)
        mode = snap.get("mode") or ""

        if step_total > 0:
            progress = f"{step_index}/{step_total}"
        else:
            progress = "-"

        paused = "일시정지" if snap.get("paused") else "실행중"
        text = f"[{mode}] {skill} | {phase} {progress} | {paused}"
        self._status_var.set(text[:70])

        if self._pause_btn is not None:
            self._pause_btn.configure(text="▶" if snap.get("paused") else "⏸")
