"""Windows 자동화 제어 오버레이 — 대상 앱을 감싸는 둥근 글로우 테두리 + 제어 HUD.

크롬의 "자동화 소프트웨어가 제어 중" 배너나 Claude Desktop 제어 오버레이처럼,
대상 프로그램(PID) 윈도우 주변에 부드러운 음영(글로우) 테두리를 그리고,
상단에는 둥근 알약(pill) 형태의 일시정지/스킵/중지 컨트롤을 띄웁니다.
"""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
import tkinter as tk
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple

if TYPE_CHECKING:
    from core.automation_run_control import AutomationRunControl

logger = logging.getLogger(__name__)

# Chrome "자동화 소프트웨어가 제어 중" 인포바 느낌의 배너 문구
_CHROME_BANNER_TEXT = "자동화 소프트웨어가 제어 중"
_CHROME_INFO_BG = "#e8f0fe"
# ── Design tokens (Chrome automated-test infobar + dark pill controls) ───────
_BG = "#1f2023"
_SURFACE = "#2a2c31"
_SURFACE_HOVER = "#3a3d44"
_BORDER = "#42454d"
_TEXT = "#ececf1"
_TEXT_DIM = "#9aa0a6"
_ACCENT = "#8ab4f8"
_ACCENT_STRONG = "#b3ccff"
_STOP = "#f28b82"
_SHADOW = "#15161a"
# 대상 윈도우를 감싸는 글로우의 안쪽(밝음)/바깥쪽(어두움) 색
_GLOW_INNER = "#9fc1ff"
_GLOW_OUTER = "#0a1730"
# transparentcolor 키 — 이 색 픽셀은 완전히 투명(클릭 통과)해집니다.
_TRANSPARENT_KEY = "#010203"

_OVERLAY_HEIGHT = 44
_OVERLAY_MAX_WIDTH = 480
_OVERLAY_MIN_WIDTH = 300
_OVERLAY_TOP_INSET = 8
_HUD_RADIUS = 18
_SHADOW_PAD = 8

_GLOW_MARGIN = 16
_GLOW_RADIUS = 18
_BORDER_PX = 2

# Tk 폰트 튜플은 (family, size[, style]) 형식이어야 합니다.
# 여러 패밀리를 나열하면 두 번째 값이 크기(정수)로 해석되어 오류가 납니다.
_FONT = ("Segoe UI", 9)
_ICON_FONT = ("Segoe UI Symbol", 10)

_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080


# ── 색/도형 헬퍼 ──────────────────────────────────────────────────────────────

def _hex_to_rgb(value: str) -> Tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _lerp_color(c1: str, c2: str, t: float) -> str:
    """두 색 사이를 t(0~1)로 선형 보간합니다."""
    t = max(0.0, min(1.0, t))
    a = _hex_to_rgb(c1)
    b = _hex_to_rgb(c2)
    r = round(a[0] + (b[0] - a[0]) * t)
    g = round(a[1] + (b[1] - a[1]) * t)
    bl = round(a[2] + (b[2] - a[2]) * t)
    return f"#{r:02x}{g:02x}{bl:02x}"


def _round_rect_points(x1: int, y1: int, x2: int, y2: int, radius: int) -> List[int]:
    """smooth 폴리곤으로 둥근 사각형을 그리기 위한 좌표 리스트를 만듭니다."""
    r = max(0, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
    return [
        x1 + r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y1 + r, x1, y1,
    ]


# ── Target window helpers ───────────────────────────────────────────────────

def _safe_call(fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception:
        return default


def _main_window_wrapper_for_pid(pid: int) -> Optional[Any]:
    """대상 PID가 소유한 보이는 최상위 윈도우 중 가장 큰 것을 선택합니다.

    foreground 창은 사용자가 다른 창(콘솔 등)을 클릭하면 바뀌므로,
    "프로그램을 감싸는" 오버레이의 기준 창으로는 메인 윈도우가 더 안정적입니다.
    """
    try:
        import win32gui
        import win32process
        from pywinauto.controls.hwndwrapper import HwndWrapper
    except Exception:
        return None

    best = {"area": 0, "hwnd": None}

    def _cb(hwnd: int, _extra: Any) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            if win32gui.GetWindowText(hwnd) == "" and win32gui.GetWindow(hwnd, 4):
                # 보이지만 제목 없는 도구/소유 창은 건너뜀 (GW_OWNER=4)
                return True
            _, wpid = win32process.GetWindowThreadProcessId(hwnd)
            if wpid != pid:
                return True
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            area = max(0, right - left) * max(0, bottom - top)
            if area > best["area"]:
                best["area"] = area
                best["hwnd"] = hwnd
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        return None

    if best["hwnd"] is None:
        return None
    return _safe_call(lambda: HwndWrapper(best["hwnd"]), None)


def _pick_overlay_target_window(session: Any) -> Optional[Any]:
    """연결된 앱에서 오버레이를 붙일 대상 윈도우를 선택합니다."""
    if not session.is_connected:
        return None

    target_pid = getattr(session.app, "process", None)

    # 1) 대상 PID가 소유한 메인(가장 큰 보이는 최상위) 윈도우 — 가장 안정적
    if target_pid:
        main_wrapper = _main_window_wrapper_for_pid(int(target_pid))
        if main_wrapper is not None and _safe_call(lambda: main_wrapper.is_visible(), False):
            return main_wrapper

    # 2) 대상 앱이 소유한 foreground 윈도우 (모달/대화상자 추적용)
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
    """둥근 아이콘 버튼 (호버 시 배경 강조)."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        icon: str,
        command: Callable[[], None],
        width: int = 30,
        height: int = 26,
        accent: Optional[str] = None,
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
        self._accent = accent
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
        self.create_round_rect(pad, pad, w - pad, h - pad, radius=8, fill=fill, outline="")
        self.create_text(
            w // 2,
            h // 2,
            text=self._icon,
            fill=(self._accent or _TEXT),
            font=_ICON_FONT,
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
        return self.create_polygon(
            _round_rect_points(x1, y1, x2, y2, radius), smooth=True, **kwargs
        )


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
        self._border_canvas: tk.Canvas | None = None
        self._hud_canvas: tk.Canvas | None = None
        self._hud_content: tk.Frame | None = None
        self._hud_window_id: int | None = None
        self._detail_var: tk.StringVar | None = None
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
            root.configure(bg=_TRANSPARENT_KEY)
            try:
                root.attributes("-transparentcolor", _TRANSPARENT_KEY)
            except tk.TclError:
                pass
            try:
                root.attributes("-alpha", 0.97)
            except tk.TclError:
                pass

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
        """둥근 알약(pill) 형태의 제어 HUD를 구성합니다."""
        canvas = tk.Canvas(root, bg=_TRANSPARENT_KEY, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        self._hud_canvas = canvas

        content = tk.Frame(canvas, bg=_SURFACE)
        self._hud_content = content

        self._detail_var = tk.StringVar(value="준비 중")

        banner = tk.Frame(content, bg=_CHROME_INFO_BG)
        banner.pack(side="top", fill="x", padx=1, pady=(1, 0))
        tk.Label(
            banner,
            text=_CHROME_BANNER_TEXT,
            bg=_CHROME_INFO_BG,
            fg=_CHROME_INFO_FG,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(10, 6), pady=2)

        body = tk.Frame(content, bg=_SURFACE)
        body.pack(side="top", fill="both", expand=True)

        tk.Label(
            body,
            textvariable=self._detail_var,
            bg=_SURFACE,
            fg=_TEXT_DIM,
            font=_FONT,
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(12, 8), pady=2)

        btn_row = tk.Frame(body, bg=_SURFACE)
        btn_row.pack(side="right", padx=(0, 8))

        self._pause_btn = _ChromeIconButton(
            btn_row,
            icon="⏸",
            command=self._on_toggle_pause,
        )
        self._pause_btn.pack(side="left", padx=2)
        _ChromeIconButton(
            btn_row,
            icon="⏭",
            command=self._control.request_skip_skill,
        ).pack(side="left", padx=2)
        _ChromeIconButton(
            btn_row,
            icon="■",
            command=self._control.request_stop,
            accent=_STOP,
        ).pack(side="left", padx=2)

    def _draw_hud_pill(self, width: int, height: int) -> None:
        """HUD 배경(그림자 + 둥근 알약)을 그리고 컨텐츠 프레임을 배치합니다."""
        canvas = self._hud_canvas
        if canvas is None:
            return
        try:
            canvas.delete("hud_bg")
            # 부드러운 그림자 (약간 오프셋된 어두운 둥근 사각형)
            canvas.create_polygon(
                _round_rect_points(4, 5, width + 4, height + 4, _HUD_RADIUS),
                smooth=True,
                fill=_SHADOW,
                outline="",
                tags="hud_bg",
            )
            # 알약 본체
            canvas.create_polygon(
                _round_rect_points(2, 1, width + 1, height, _HUD_RADIUS),
                smooth=True,
                fill=_SURFACE,
                outline=_BORDER,
                width=1,
                tags="hud_bg",
            )
            canvas.tag_lower("hud_bg")

            content = self._hud_content
            if content is not None:
                cw = max(40, width - 8)
                ch = max(20, height - 6)
                if self._hud_window_id is None:
                    self._hud_window_id = canvas.create_window(
                        4, 3, anchor="nw", window=content, width=cw, height=ch
                    )
                else:
                    canvas.coords(self._hud_window_id, 4, 3)
                    canvas.itemconfigure(self._hud_window_id, width=cw, height=ch)
        except Exception as exc:
            logger.debug("HUD 알약 그리기 실패: %s", exc)

    def _build_border_overlay(self) -> None:
        """대상 앱 주위에 둥근 글로우(음영) 테두리를 그립니다."""
        rect = _get_target_rect()
        if rect is None:
            return
        bx, by, bw, bh = self._border_geom(rect)

        try:
            border = tk.Toplevel(self._root)
            self._border = border
            border.overrideredirect(True)
            border.attributes("-topmost", True)
            border.configure(bg=_TRANSPARENT_KEY)
            border.attributes("-transparentcolor", _TRANSPARENT_KEY)
            try:
                border.attributes("-alpha", 0.9)
            except tk.TclError:
                pass
            border.geometry(f"{bw}x{bh}+{bx}+{by}")
            border.withdraw()

            canvas = tk.Canvas(border, bg=_TRANSPARENT_KEY, highlightthickness=0, bd=0)
            canvas.pack(fill="both", expand=True)
            self._border_canvas = canvas
            self._draw_glow_border(canvas, bw, bh)

            border.update_idletasks()
            try:
                _apply_no_activate(border.winfo_id())
            except Exception:
                pass
        except Exception as exc:
            logger.debug("테두리 오버레이 생성 실패: %s", exc)
            self._border = None
            self._border_canvas = None

    def _draw_glow_border(self, canvas: tk.Canvas, w: int, h: int) -> None:
        """창 가장자리에서 바깥으로 퍼지는 둥근 글로우 링들을 그립니다."""
        try:
            canvas.delete("glow")
            margin = _GLOW_MARGIN
            # 바깥(어두움) → 안쪽(밝음) 순으로 그려 안쪽 링이 위에 오도록 함
            for offset in range(margin, 0, -1):
                t = 1.0 - (offset / margin)  # offset=0 안쪽(밝음), margin 바깥(어두움)
                color = _lerp_color(_GLOW_OUTER, _GLOW_INNER, t * t)
                x1 = margin - offset
                y1 = margin - offset
                x2 = w - (margin - offset)
                y2 = h - (margin - offset)
                canvas.create_polygon(
                    _round_rect_points(x1, y1, x2, y2, _GLOW_RADIUS + offset),
                    smooth=True,
                    outline=color,
                    fill="",
                    width=2,
                    tags="glow",
                )
            # 창 가장자리에 닿는 또렷한 강조 링
            canvas.create_polygon(
                _round_rect_points(margin, margin, w - margin, h - margin, _GLOW_RADIUS),
                smooth=True,
                outline=_ACCENT_STRONG,
                fill="",
                width=_BORDER_PX,
                tags="glow",
            )
        except Exception as exc:
            logger.debug("글로우 테두리 그리기 실패: %s", exc)

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
        """테두리 창 (x, y, w, h)를 계산합니다 (글로우 여백 포함)."""
        pad = _GLOW_MARGIN
        t_l, t_t, t_w, t_h = rect
        return (t_l - pad, t_t - pad, t_w + pad * 2, t_h + pad * 2)

    def _reposition(self, rect: Tuple[int, int, int, int]) -> None:
        """대상 앱이 이동/리사이즈되면 오버레이 위치를 갱신합니다."""
        root = self._root
        if root is None:
            return

        try:
            ov_x, ov_y, ov_w = self._calc_overlay_pos(rect)
            root.geometry(
                f"{ov_w + _SHADOW_PAD}x{_OVERLAY_HEIGHT + _SHADOW_PAD}+{ov_x}+{ov_y}"
            )
            self._draw_hud_pill(ov_w, _OVERLAY_HEIGHT)
        except Exception as exc:
            logger.debug("오버레이 위치 갱신 실패: %s", exc)

        if self._border is not None:
            try:
                bx, by, bw, bh = self._border_geom(rect)
                self._border.geometry(f"{bw}x{bh}+{bx}+{by}")
                if self._border_canvas is not None:
                    self._draw_glow_border(self._border_canvas, bw, bh)
            except Exception as exc:
                logger.debug("테두리 오버레이 위치 갱신 실패: %s", exc)

    def _ensure_border(self, rect: Tuple[int, int, int, int]) -> None:
        if self._border is not None:
            return
        self._build_border_overlay()
        if self._border is not None and not self._visible:
            self._border.withdraw()

    def _sync_visibility_and_position(self) -> None:
        """대상 앱이 없으면 숨기고, 있으면 대상 창을 감싸도록 배치합니다."""
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
        self._border_canvas = None

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
        self._detail_var = None
        self._pause_btn = None
        self._hud_canvas = None
        self._hud_content = None
        self._hud_window_id = None
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
        if self._detail_var is None or self._root is None:
            return
        snap = self._control.snapshot()
        skill = snap.get("skill_id") or "-"
        phase = snap.get("phase") or "ready"
        step_index = int(snap.get("step_index") or 0)
        step_total = int(snap.get("step_total") or 0)
        mode = snap.get("mode") or ""

        progress = f"{step_index}/{step_total}" if step_total > 0 else "-"
        paused = "일시정지" if snap.get("paused") else "실행 중"
        text = f"{mode} · {skill} · {phase} · {progress} · {paused}"
        self._detail_var.set(text[:72])

        if self._pause_btn is not None:
            self._pause_btn.configure_icon("▶" if snap.get("paused") else "⏸")
