"""Windows 자동화 제어 오버레이 — 대상 앱 상단에 표시되는 Chrome 스타일 HUD."""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
import tkinter as tk
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple

if TYPE_CHECKING:
    from core.automation_run_control import AutomationRunControl

logger = logging.getLogger(__name__)

# ── Chrome-inspired design tokens ──────────────────────────────────────────
_BG = "#303134"
_SURFACE = "#3c4043"
_SURFACE_HOVER = "#5f6368"
_BORDER = "#5f6368"
_TEXT = "#e8eaed"
_TEXT_DIM = "#9aa0a6"
_ACCENT = "#8ab4f8"
_TRANSPARENT_KEY = "#000002"

_OVERLAY_HEIGHT = 40
_OVERLAY_MAX_WIDTH = 480
_OVERLAY_MIN_WIDTH = 300
_OVERLAY_TOP_INSET = 8
_BORDER_PX = 2

_FONT = ("Roboto", "Segoe UI", "Helvetica Neue", "Arial", 9)

_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080


# ── Target window helpers ───────────────────────────────────────────────────

def _safe_call(fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception:
        return default


def _pick_overlay_target_window(session: Any) -> Optional[Any]:
    """연결된 앱에서 오버레이를 붙일 대상 윈도우를 선택합니다."""
    if not session.is_connected:
        return None

    target_pid = getattr(session.app, "process", None)

    # Foreground window owned by connected app
    try:
        import win32gui
        import win32process

        fg_hwnd = win32gui.GetForegroundWindow()
        if fg_hwnd and target_pid:
            _, fg_pid = win32process.GetWindowThreadProcessId(fg_hwnd)
            if fg_pid == target_pid:
                from pywinauto.controls.hwndwrapper import HwndWrapper

                wrapper = HwndWrapper(fg_hwnd)
                if _safe_call(lambda: wrapper.is_visible(), False):
                    return wrapper
    except Exception as exc:
        logger.debug("Foreground window 체크 실패: %s", exc)

    cached = getattr(session, "cached_window", None)
    if cached:
        if _safe_call(lambda: cached.exists(), False):
            if _safe_call(lambda: cached.is_visible(), False) or _safe_call(
                lambda: cached.is_minimized(), False
            ):
                return cached
        session.cached_window = None

    try:
        top = session.app.top_window()
        if _safe_call(lambda: top.exists(), False):
            if _safe_call(lambda: top.is_visible(), False) or _safe_call(
                lambda: top.is_minimized(), False
            ):
                return top
    except Exception as exc:
        logger.debug("top_window 조회 실패: %s", exc)

    try:
        for window in session.app.windows():
            wrapper = _safe_call(lambda: window.wrapper_object(), None) or window
            if _safe_call(lambda: wrapper.is_visible(), False) or _safe_call(
                lambda: wrapper.is_minimized(), False
            ):
                return wrapper
    except Exception as exc:
        logger.debug("app.windows() 조회 실패: %s", exc)

    return None


def _get_target_rect() -> Optional[Tuple[int, int, int, int]]:
    """연결된 앱 대상 윈도우의 (left, top, width, height)를 반환합니다."""
    try:
        from core.app_session import AppSession

        session = AppSession.get_instance()
        wrapper = _pick_overlay_target_window(session)
        if wrapper is None:
            return None

        if _safe_call(lambda: wrapper.is_minimized(), False):
            return None
        if not _safe_call(lambda: wrapper.is_visible(), False):
            return None

        rect = wrapper.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        if width < 80 or height < 80:
            return None
        return (int(rect.left), int(rect.top), width, height)
    except Exception as exc:
        logger.debug("대상 앱 윈도우 위치 획득 실패: %s", exc)
        return None


def _apply_no_activate(hwnd: int) -> None:
    """WS_EX_NOACTIVATE — 클릭/단축키 입력 시 포커스를 훔치지 않음."""
    try:
        style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd,
            _GWL_EXSTYLE,
            style | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW,
        )
    except Exception as exc:
        logger.debug("WS_EX_NOACTIVATE 설정 실패: %s", exc)


class _ChromeIconButton(tk.Canvas):
    """Chrome 툴바 스타일의 둥근 아이콘 버튼."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        icon: str,
        command: Callable[[], None],
        width: int = 30,
        height: int = 26,
    ) -> None:
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=_SURFACE,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._icon = icon
        self._command = command
        self._hover = False
        self._enabled = True
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._redraw()

    def configure_icon(self, icon: str) -> None:
        self._icon = icon
        self._redraw()

    def _on_click(self, _event: tk.Event) -> None:
        if self._enabled:
            self._command()

    def _on_enter(self, _event: tk.Event) -> None:
        self._hover = True
        self._redraw()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hover = False
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        w = int(self.cget("width"))
        h = int(self.cget("height"))
        pad = 2
        fill = _SURFACE_HOVER if self._hover else _SURFACE
        self.create_round_rect(
            pad,
            pad,
            w - pad,
            h - pad,
            radius=6,
            fill=fill,
            outline="",
        )
        self.create_text(
            w // 2,
            h // 2,
            text=self._icon,
            fill=_TEXT,
            font=("Segoe UI Symbol", 10),
        )

    def create_round_rect(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        radius: int = 8,
        **kwargs: Any,
    ) -> int:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)


# ── 메인 클래스 ─────────────────────────────────────────────────────────────

class AutomationControlOverlay:
    """
    Tk 오버레이.

    Windows tkinter는 생성·갱신 스레드에서 mainloop/update가 돌아야 합니다.
    별도 daemon 스레드 + after 폴링 대신, 메인 스레드 pump()로 이벤트를 처리합니다.
    """

    def __init__(self, control: "AutomationRunControl") -> None:
        self._control = control
        self._root: tk.Tk | None = None
        self._border: tk.Toplevel | None = None
        self._status_var: tk.StringVar | None = None
        self._pause_btn: _ChromeIconButton | None = None
        self._commands: queue.Queue[str] = queue.Queue()
        self._closing = False
        self._shutdown_done = threading.Event()
        self._ui_thread = threading.main_thread()
        self._visible = False

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown_done.is_set()

    def start(self) -> None:
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

    # ── UI 생성 ─────────────────────────────────────────────────────────────

    def _create_ui(self) -> None:
        try:
            root = tk.Tk()
            self._root = root
            root.title("chatRTD Control")
            root.attributes("-topmost", True)
            root.overrideredirect(True)
            try:
                root.attributes("-alpha", 0.97)
            except tk.TclError:
                pass

            root.configure(bg=_BG)
            root.withdraw()

            self._build_hud(root)
            self._build_border_overlay()

            root.update_idletasks()
            try:
                _apply_no_activate(root.winfo_id())
            except Exception:
                pass

            self._refresh_labels()
            self._sync_visibility_and_position()
            root.update_idletasks()
        except Exception as exc:
            logger.warning("자동화 오버레이 UI 생성 실패: %s", exc)
            self._root = None
            self._shutdown_done.set()

    def _build_hud(self, root: tk.Tk) -> None:
        """Chrome 툴바 스타일 HUD 위젯을 구성합니다."""
        shell = tk.Frame(root, bg=_BG, padx=8, pady=6)
        shell.pack(fill="both", expand=True)

        tk.Frame(shell, height=1, bg=_BORDER).pack(fill="x", side="bottom")

        body = tk.Frame(shell, bg=_BG)
        body.pack(fill="both", expand=True)

        self._status_var = tk.StringVar(value="자동화 준비중")
        tk.Label(
            body,
            textvariable=self._status_var,
            bg=_BG,
            fg=_TEXT,
            font=_FONT,
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(2, 10))

        btn_row = tk.Frame(body, bg=_SURFACE, padx=4, pady=3)
        btn_row.pack(side="right")

        self._pause_btn = _ChromeIconButton(
            btn_row,
            icon="⏸",
            command=self._on_toggle_pause,
        )
        self._pause_btn.pack(side="left", padx=1)
        _ChromeIconButton(
            btn_row,
            icon="⏭",
            command=self._control.request_skip_skill,
        ).pack(side="left", padx=1)
        _ChromeIconButton(
            btn_row,
            icon="■",
            command=self._control.request_stop,
        ).pack(side="left", padx=1)

    def _build_border_overlay(self) -> None:
        """대상 앱 주위에 Chrome DevTools 스타일 테두리를 그립니다."""
        rect = _get_target_rect()
        if rect is None:
            return
        bx, by, bw, bh = self._border_geom(rect)

        try:
            border = tk.Toplevel(self._root)
            self._border = border
            border.overrideredirect(True)
            border.attributes("-topmost", True)
            border.attributes("-transparentcolor", _TRANSPARENT_KEY)
            try:
                border.attributes("-alpha", 0.85)
            except tk.TclError:
                pass
            border.geometry(f"{bw}x{bh}+{bx}+{by}")
            border.withdraw()

            canvas = tk.Canvas(border, bg=_TRANSPARENT_KEY, highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            canvas.create_rectangle(0, 0, bw - 1, bh - 1, outline="#5f6368", width=1, fill="")
            canvas.create_rectangle(1, 1, bw - 2, bh - 2, outline=_ACCENT, width=_BORDER_PX, fill="")

            border.update_idletasks()
            try:
                _apply_no_activate(border.winfo_id())
            except Exception:
                pass
        except Exception as exc:
            logger.debug("테두리 오버레이 생성 실패: %s", exc)
            self._border = None

    # ── 위치 계산 ───────────────────────────────────────────────────────────

    @staticmethod
    def _calc_overlay_pos(rect: Tuple[int, int, int, int]) -> Tuple[int, int, int]:
        """(x, y, width)를 반환합니다."""
        t_left, t_top, t_w, _ = rect
        ov_w = max(_OVERLAY_MIN_WIDTH, min(t_w - 24, _OVERLAY_MAX_WIDTH))
        ov_x = t_left + (t_w - ov_w) // 2
        ov_y = t_top + _OVERLAY_TOP_INSET
        return (ov_x, ov_y, ov_w)

    @staticmethod
    def _border_geom(rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """테두리 창 (x, y, w, h)를 계산합니다."""
        pad = _BORDER_PX + 2
        t_l, t_t, t_w, t_h = rect
        return (t_l - pad, t_t - pad, t_w + pad * 2, t_h + pad * 2)

    def _reposition(self, rect: Tuple[int, int, int, int]) -> None:
        """대상 앱이 이동/리사이즈되면 오버레이 위치를 갱신합니다."""
        root = self._root
        if root is None:
            return

        try:
            ov_x, ov_y, ov_w = self._calc_overlay_pos(rect)
            root.geometry(f"{ov_w}x{_OVERLAY_HEIGHT}+{ov_x}+{ov_y}")
        except Exception as exc:
            logger.debug("오버레이 위치 갱신 실패: %s", exc)

        if self._border is not None:
            try:
                bx, by, bw, bh = self._border_geom(rect)
                self._border.geometry(f"{bw}x{bh}+{bx}+{by}")
            except Exception as exc:
                logger.debug("테두리 오버레이 위치 갱신 실패: %s", exc)

    def _ensure_border(self, rect: Tuple[int, int, int, int]) -> None:
        if self._border is not None:
            return
        self._build_border_overlay()
        if self._border is not None and not self._visible:
            self._border.withdraw()

    def _sync_visibility_and_position(self) -> None:
        """대상 앱이 없으면 숨기고, 있으면 대상 창 상단에 붙입니다."""
        root = self._root
        if root is None:
            return

        rect = _get_target_rect()
        if rect is None:
            if self._visible:
                root.withdraw()
                if self._border is not None:
                    self._border.withdraw()
                self._visible = False
            return

        self._ensure_border(rect)
        self._reposition(rect)

        if not self._visible:
            root.deiconify()
            if self._border is not None:
                self._border.deiconify()
            self._visible = True

    # ── 종료 ────────────────────────────────────────────────────────────────

    def _shutdown_ui(self, root: tk.Tk) -> None:
        if self._border is not None:
            try:
                self._border.destroy()
            except tk.TclError:
                pass
            self._border = None

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
        self._visible = False

    def _process_commands(self) -> None:
        root = self._root
        if root is None:
            return

        should_stop = False
        try:
            while True:
                cmd = self._commands.get_nowait()
                if cmd == "stop":
                    should_stop = True
                    break
                if cmd == "update" and not self._closing:
                    self._refresh_labels()
        except queue.Empty:
            pass

        if not should_stop and not self._closing:
            self._sync_visibility_and_position()

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

    # ── 레이블 갱신 ─────────────────────────────────────────────────────────

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

        progress = f"{step_index}/{step_total}" if step_total > 0 else "-"
        paused = "일시정지" if snap.get("paused") else "실행중"
        text = f"{mode} · {skill} · {phase} · {progress} · {paused}"
        self._status_var.set(text[:72])

        if self._pause_btn is not None:
            self._pause_btn.configure_icon("▶" if snap.get("paused") else "⏸")
