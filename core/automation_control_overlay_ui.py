"""Windows 자동화 제어 오버레이 — 대상 앱 위에 표시되는 플랫 디자인 HUD."""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
import tkinter as tk
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from core.automation_run_control import AutomationRunControl

logger = logging.getLogger(__name__)

# ── Design tokens ──────────────────────────────────────────────────────────
_BG = "#111827"
_ACCENT = "#06b6d4"
_TEXT = "#f9fafb"
_TEXT_DIM = "#9ca3af"
_BTN_BG = "#1f2937"
_BTN_HOVER = "#374151"
_TRANSPARENT_KEY = "#000002"   # transparentcolor로 쓸 near-black (순수 검정 제외)

_OVERLAY_HEIGHT = 44
_OVERLAY_MAX_WIDTH = 460
_OVERLAY_MIN_WIDTH = 280
_OVERLAY_GAP = 6               # 대상 창 위쪽 여백(px)
_BORDER_PX = 2                 # 테두리 두께

_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080


# ── 헬퍼 ───────────────────────────────────────────────────────────────────

def _apply_no_activate(hwnd: int) -> None:
    """WS_EX_NOACTIVATE — 클릭/단축키 입력 시 포커스를 훔치지 않음."""
    try:
        style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, _GWL_EXSTYLE,
            style | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW,
        )
    except Exception as exc:
        logger.debug("WS_EX_NOACTIVATE 설정 실패: %s", exc)


def _get_target_rect() -> Optional[Tuple[int, int, int, int]]:
    """연결된 앱 메인 윈도우의 (left, top, width, height)를 반환합니다."""
    try:
        from core.app_session import AppSession
        session = AppSession.get_instance()
        if not session.is_connected:
            return None
        windows = session.app.windows()
        if not windows:
            return None
        r = windows[0].rectangle()
        return (int(r.left), int(r.top), int(r.width()), int(r.height()))
    except Exception as exc:
        logger.debug("대상 앱 윈도우 위치 획득 실패: %s", exc)
        return None


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
        self._pause_btn: tk.Button | None = None
        self._commands: queue.Queue[str] = queue.Queue()
        self._closing = False
        self._shutdown_done = threading.Event()
        self._ui_thread = threading.main_thread()
        self._last_target_rect: Optional[Tuple[int, int, int, int]] = None

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
                root.attributes("-alpha", 0.96)
            except tk.TclError:
                pass

            ov_x, ov_y, ov_w = self._calc_overlay_pos()
            root.geometry(f"{ov_w}x{_OVERLAY_HEIGHT}+{ov_x}+{ov_y}")
            root.configure(bg=_BG)

            self._build_hud(root, ov_w)
            self._build_border_overlay()

            root.update_idletasks()
            try:
                _apply_no_activate(root.winfo_id())
            except Exception:
                pass

            self._refresh_labels()
            root.update_idletasks()
        except Exception as exc:
            logger.warning("자동화 오버레이 UI 생성 실패: %s", exc)
            self._root = None
            self._shutdown_done.set()

    def _build_hud(self, root: tk.Tk, ov_w: int) -> None:
        """플랫 디자인 HUD 위젯을 구성합니다."""
        # Accent bar (상단 2px 강조선)
        tk.Canvas(root, height=2, bg=_ACCENT, highlightthickness=0).pack(fill="x", side="top")

        body = tk.Frame(root, bg=_BG, padx=10, pady=7)
        body.pack(fill="both", expand=True)

        self._status_var = tk.StringVar(value="자동화 준비중")
        tk.Label(
            body,
            textvariable=self._status_var,
            bg=_BG,
            fg=_TEXT,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        btn_kw = dict(
            bg=_BTN_BG, fg=_TEXT,
            activebackground=_BTN_HOVER, activeforeground=_TEXT,
            relief="flat", bd=0,
            font=("Segoe UI", 11),
            cursor="hand2",
            width=2,
            takefocus=0,   # Tab 포커스 차단 → 단축키 오발사 방지
        )
        btn_row = tk.Frame(body, bg=_BG)
        btn_row.pack(side="right")

        self._pause_btn = tk.Button(btn_row, text="⏸", command=self._on_toggle_pause, **btn_kw)
        self._pause_btn.pack(side="left", padx=2)
        tk.Button(btn_row, text="⏭", command=self._control.request_skip_skill, **btn_kw).pack(side="left", padx=2)
        tk.Button(btn_row, text="⏹", command=self._control.request_stop, **btn_kw).pack(side="left", padx=2)

    def _build_border_overlay(self) -> None:
        """대상 앱 주위에 Chrome DevTools 스타일 테두리를 그립니다."""
        rect = _get_target_rect()
        if rect is None:
            return
        self._last_target_rect = rect
        bx, by, bw, bh = self._border_geom(rect)

        try:
            border = tk.Toplevel(self._root)
            self._border = border
            border.overrideredirect(True)
            border.attributes("-topmost", True)
            # near-black을 투명색으로 지정 → 배경만 투과, 테두리선 표시
            border.attributes("-transparentcolor", _TRANSPARENT_KEY)
            try:
                border.attributes("-alpha", 0.80)
            except tk.TclError:
                pass
            border.geometry(f"{bw}x{bh}+{bx}+{by}")

            c = tk.Canvas(border, bg=_TRANSPARENT_KEY, highlightthickness=0)
            c.pack(fill="both", expand=True)
            # 외곽 glow 효과 (옅은 선 2겹)
            c.create_rectangle(0, 0, bw - 1, bh - 1, outline="#0891b2", width=1, fill="")
            c.create_rectangle(1, 1, bw - 2, bh - 2, outline=_ACCENT, width=_BORDER_PX, fill="")

            border.update_idletasks()
            try:
                _apply_no_activate(border.winfo_id())
            except Exception:
                pass
        except Exception as exc:
            logger.debug("테두리 오버레이 생성 실패: %s", exc)
            self._border = None

    # ── 위치 계산 ───────────────────────────────────────────────────────────

    def _calc_overlay_pos(self) -> Tuple[int, int, int]:
        """(x, y, width)를 반환합니다."""
        root = self._root
        screen_w = root.winfo_screenwidth() if root else 1920

        rect = _get_target_rect()
        if rect:
            t_left, t_top, t_w, _ = rect
            ov_w = max(_OVERLAY_MIN_WIDTH, min(t_w, _OVERLAY_MAX_WIDTH))
            ov_x = t_left + (t_w - ov_w) // 2
            ov_y = max(0, t_top - _OVERLAY_HEIGHT - _OVERLAY_GAP)
        else:
            ov_w = _OVERLAY_MAX_WIDTH
            ov_x = max(0, (screen_w - ov_w) // 2)
            ov_y = 8
        return (ov_x, ov_y, ov_w)

    @staticmethod
    def _border_geom(rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """테두리 창 (x, y, w, h)를 계산합니다."""
        pad = _BORDER_PX + 2
        t_l, t_t, t_w, t_h = rect
        return (t_l - pad, t_t - pad, t_w + pad * 2, t_h + pad * 2)

    def _reposition(self) -> None:
        """대상 앱이 이동/리사이즈되면 오버레이 위치를 갱신합니다."""
        root = self._root
        if root is None:
            return
        rect = _get_target_rect()

        # 오버레이 위치 갱신
        try:
            ov_x, ov_y, ov_w = self._calc_overlay_pos()
            root.geometry(f"{ov_w}x{_OVERLAY_HEIGHT}+{ov_x}+{ov_y}")
        except Exception as exc:
            logger.debug("오버레이 위치 갱신 실패: %s", exc)

        # 테두리 위치 갱신
        if rect and self._border is not None:
            try:
                bx, by, bw, bh = self._border_geom(rect)
                self._border.geometry(f"{bw}x{bh}+{bx}+{by}")
            except Exception as exc:
                logger.debug("테두리 오버레이 위치 갱신 실패: %s", exc)

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
                    self._reposition()
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
        text = f"[{mode}] {skill}  {phase} {progress}  {paused}"
        self._status_var.set(text[:70])

        if self._pause_btn is not None:
            self._pause_btn.configure(text="▶" if snap.get("paused") else "⏸")
