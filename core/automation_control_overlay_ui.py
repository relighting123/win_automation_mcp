"""Windows 화면 상단 always-on-top 자동화 제어 오버레이."""

from __future__ import annotations

import logging
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
    def __init__(self, control: "AutomationRunControl") -> None:
        self._control = control
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._root: tk.Tk | None = None
        self._status_var: tk.StringVar | None = None
        self._pause_btn: ttk.Button | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_ui, name="automation-overlay", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def stop(self) -> None:
        root = self._root
        if root is None:
            return

        def _close() -> None:
            try:
                root.destroy()
            except tk.TclError:
                pass

        try:
            root.after(0, _close)
        except tk.TclError:
            pass
        if self._thread:
            self._thread.join(timeout=2.0)
        self._root = None

    def schedule_update(self) -> None:
        root = self._root
        if root is None:
            return
        try:
            root.after(0, self._refresh_labels)
        except tk.TclError:
            pass

    def _run_ui(self) -> None:
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
            self._ready.set()
            root.mainloop()
        except Exception as exc:
            logger.warning("자동화 오버레이 UI 실행 실패: %s", exc)
            self._ready.set()

    def _on_toggle_pause(self) -> None:
        self._control.toggle_pause()
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        if self._status_var is None:
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
