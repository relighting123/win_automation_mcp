#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chatRTD — Windows Automation Scheduler CLI"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from openai import OpenAI
from rich.align import Align
from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import ANSI

    _HAS_PROMPT_TOOLKIT = True
except ImportError:
    _HAS_PROMPT_TOOLKIT = False

    class Completer:  # type: ignore[no-redef]
        pass

    Completion = PromptSession = ANSI = None  # type: ignore[misc, assignment]

# ── Project root on sys.path ─────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.llm_config import get_llm_settings, get_mcp_settings

# ── Version ───────────────────────────────────────────────────────────────────
VERSION = "0.1.0"

# ── opencode color palette ────────────────────────────────────────────────────
# https://github.com/opencode-ai/opencode  (MIT)  dark theme
_C = {
    "primary":   "#fab283",   # warm orange  — brand / highlight
    "secondary": "#5c9cf5",   # blue         — secondary info
    "accent":    "#9d7cd8",   # purple       — accent
    "text":      "#e0e0e0",   # light        — normal text
    "muted":     "#6a6a6a",   # mid-gray     — dim / labels
    "border":    "#4b4c5c",   # dark-gray    — borders / rules
    "surface":   "#222228",   # input bar bg — opencode-style strip
    "logo_dim":  "#3a3a3a",   # logo shadow
    "logo_mid":  "#8a8a8a",   # logo mid-tone
    "logo_hi":   "#d4d4d4",   # logo highlight
    "success":   "#7fd88f",   # green
    "error":     "#e06c75",   # red
    "warning":   "#f5a742",   # amber
}

_HEADER_W = 64

_LOGO_CHAT = [
    " ██████╗ ██╗  ██╗ █████╗ ████████╗",
    " ██╔════╝ ██║  ██║██╔══██╗╚══██╔══╝",
    " ██║      ███████║███████║   ██║   ",
    " ██║      ██╔══██║██╔══██║   ██║   ",
    " ╚██████╗ ██║  ██║██║  ██║   ██║   ",
    "  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ",
]
_LOGO_RTD = [
    " ██████╗ ████████╗ ██████╗ ",
    " ██╔══██╗╚══██╔══╝██╔══██╗",
    " ██████╔╝   ██║   ██║  ██║",
    " ██╔══██╗   ██║   ██║  ██║",
    " ██║  ██║   ██║   ██████╔╝",
    " ╚═╝  ╚═╝   ╚═╝   ╚═════╝ ",
]
_LOGO_GAP = "   "
_LOGO_SPLIT = len(_LOGO_CHAT[0]) + len(_LOGO_GAP)
_LOGO_ART = [c + _LOGO_GAP + r for c, r in zip(_LOGO_CHAT, _LOGO_RTD)]

_THEME = Theme({
    "primary":   _C["primary"],
    "secondary": _C["secondary"],
    "accent":    _C["accent"],
    "muted":     _C["muted"],
    "ok":        _C["success"],
    "err":       _C["error"],
    "warn":      _C["warning"],
    "border":    _C["border"],
    "tool":      _C["secondary"],
})

# ANSI-styled input prompt (rich can't colour input() directly)
_PROMPT = f"\033[38;2;92;156;245m▌\033[0m "   # blue bar — matches status strip

# ── Config paths ──────────────────────────────────────────────────────────────
CONFIG_DIR  = Path.home() / ".chatRTD"
CONFIG_FILE = CONFIG_DIR / "config.json"

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "당신은 Windows 자동화 스케줄링 에이전트입니다.\n"
    "사용자의 요청을 분석하여 필요한 도구들을 순서대로 호출하세요.\n"
    "각 도구 실행 결과를 바탕으로 다음 단계를 결정하고,\n"
    "모든 작업이 완료되면 한국어로 최종 결과를 간결하게 보고하세요."
)

# ── Help text ─────────────────────────────────────────────────────────────────
HELP_TEXT = f"""
[primary]chatRTD[/primary] [muted]Automation Scheduler v{VERSION}[/muted]

[secondary]Commands[/secondary]
  [text]/help[/text]              이 도움말
  [text]/exit  /quit[/text]       종료
  [text]/clear[/text]             대화 기록 초기화

[secondary]Tools & Skills[/secondary]
  [text]/tools[/text]             사용 가능한 도구 목록
  [text]/skills[/text]            스킬 목록
  [text]/skill <id>[/text]        스킬 직접 실행

[secondary]Model Management[/secondary]
  [text]/models[/text]                                                   등록된 모델 목록
  [text]/models add <name> --api-key <k> --base-url <u> --model <m>[/text]  모델 등록
  [text]/models select <name>[/text]                                     활성 모델 전환
  [text]/models remove <name>[/text]                                     모델 삭제

[secondary]Analyze (automation graph)[/secondary]
  [text]/analyze <query>[/text]                    semi 모드로 실행 (기본)
  [text]/analyze auto <query>[/text]               auto 모드 — graph가 스킬 자동 선택
  [text]/analyze semi <query>[/text]               semi 모드 — 스킬 순서 고정, AI가 인자 추출
  [text]/analyze manual <skill_id> [query][/text]  manual 모드 — 스킬 고정 실행

[secondary]Config[/secondary]
  [text]/config[/text]                   현재 설정 확인
  [text]/config set mcp-url <url>[/text] MCP 서버 URL 변경
"""

_SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/help",           "이 도움말"),
    ("/exit",           "종료"),
    ("/quit",           "종료"),
    ("/clear",          "대화 기록 초기화"),
    ("/tools",          "사용 가능한 도구 목록"),
    ("/skills",         "스킬 목록"),
    ("/skill",          "스킬 직접 실행  (/skill <id>)"),
    ("/models",         "등록된 모델 목록"),
    ("/models add",     "모델 등록"),
    ("/models select",  "활성 모델 전환"),
    ("/models remove",  "모델 삭제"),
    ("/analyze",        "자동화 실행 (semi 모드)"),
    ("/analyze auto",   "auto 모드 — 스킬 자동 선택"),
    ("/analyze semi",   "semi 모드 — 스킬 순서 고정"),
    ("/analyze manual", "manual 모드 — 스킬 고정 실행"),
    ("/config",         "현재 설정 확인"),
    ("/config set",     "설정 변경  (/config set mcp-url <url>)"),
]


class _SlashCommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for cmd, desc in _SLASH_COMMANDS:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text), display_meta=desc)


# ── Config helpers ────────────────────────────────────────────────────────────

def load_cli_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cli_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_active_settings(cli_config: dict, overrides: Optional[dict] = None) -> dict:
    overrides = overrides or {}
    app = get_llm_settings()
    mcp = get_mcp_settings()
    active_name = cli_config.get("active_model", "")
    active_cfg  = cli_config.get("models", {}).get(active_name, {}) if active_name else {}
    return {
        "api_key":     overrides.get("api_key")   or active_cfg.get("api_key")   or app.get("api_key", ""),
        "base_url":    overrides.get("base_url")  or active_cfg.get("base_url")  or app.get("base_url", ""),
        "model":       overrides.get("model")     or active_cfg.get("model")     or app.get("model", ""),
        "mcp_url":     overrides.get("mcp_url")   or cli_config.get("mcp_url")   or mcp.get("base_url", "http://localhost:8000/mcp"),
        "active_name": active_name,
    }


# ── MCP helpers ───────────────────────────────────────────────────────────────

def _mcp_headers() -> dict:
    return {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _mcp_init(mcp_url: str, headers: dict) -> Optional[str]:
    payload = {
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "chatRTD-cli", "version": VERSION},
        },
    }
    try:
        res = requests.post(mcp_url, json=payload, headers=headers, timeout=15)
        return res.headers.get("mcp-session-id")
    except Exception:
        return None


def _parse_sse_result(res: requests.Response) -> Optional[dict]:
    for line in res.iter_lines():
        if line:
            decoded = line.decode("utf-8") if isinstance(line, bytes) else line
            if decoded.startswith("data: "):
                data = json.loads(decoded[6:])
                if "result" in data:
                    return data["result"]
    return None


def fetch_mcp_tools(mcp_url: str) -> list:
    headers = _mcp_headers()
    sid = _mcp_init(mcp_url, headers)
    if not sid:
        return []
    headers["mcp-session-id"] = sid
    try:
        res = requests.post(
            mcp_url, json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers=headers, timeout=15,
        )
        if res.status_code == 200:
            result = _parse_sse_result(res)
            if result and "tools" in result:
                return [
                    {"type": "function", "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {}),
                    }}
                    for t in result["tools"]
                ]
    except Exception:
        pass
    return []


def call_mcp_tool(mcp_url: str, name: str, arguments: dict) -> dict:
    headers = _mcp_headers()
    sid = _mcp_init(mcp_url, headers)
    if not sid:
        return {"error": "MCP 서버에 연결할 수 없습니다"}
    headers["mcp-session-id"] = sid
    try:
        requests.post(mcp_url, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                      headers=headers, timeout=2)
        payload = {
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
            "id": int(time.time() * 1000),
        }
        res = requests.post(mcp_url, json=payload, headers=headers, timeout=60, stream=True)
        if res.status_code == 200:
            result = _parse_sse_result(res)
            if result is not None:
                return result
        return {"error": f"HTTP {res.status_code}"}
    except Exception as e:
        return {"error": str(e)}


# ── Server subprocess ─────────────────────────────────────────────────────────

def _is_mcp_running(mcp_url: str) -> bool:
    """MCP 서버가 이미 실행 중인지 확인."""
    try:
        requests.get(mcp_url.rstrip("/mcp").rstrip("/"), timeout=2)
        return True
    except Exception:
        return False


def start_mcp_server(port: int = 8000) -> Optional[subprocess.Popen]:
    script = _PROJECT_ROOT / "mcp_server.py"
    if not script.exists():
        return None
    proc = subprocess.Popen(
        [sys.executable, str(script), "--transport", "http", "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(15):
        time.sleep(1)
        try:
            requests.get(f"http://localhost:{port}/", timeout=1)
            return proc
        except Exception:
            pass
    return proc


# ── Misc helpers ──────────────────────────────────────────────────────────────

def _parse_flags(args: list) -> dict:
    result: dict = {}
    i = 0
    while i < len(args):
        if args[i].startswith("--") and i + 1 < len(args):
            result[args[i][2:]] = args[i + 1]
            i += 2
        else:
            i += 1
    return result


def _tool_ok(result: dict) -> bool:
    if "error" in result:
        return False
    for item in result.get("content", []):
        if isinstance(item, dict):
            try:
                parsed = json.loads(item.get("text", "{}"))
                if isinstance(parsed, dict) and parsed.get("success") is False:
                    return False
            except Exception:
                pass
    return True


# ── Main CLI class ─────────────────────────────────────────────────────────────

class ChatRTDCLI:
    def __init__(self, settings: dict, cli_config: dict) -> None:
        self.console     = Console(force_terminal=True, theme=_THEME)
        self.settings    = settings
        self.cli_config  = cli_config
        self.mcp_url: str = settings["mcp_url"]
        self.tools: list  = []
        self.messages: list = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._init_llm_client()

    def _init_llm_client(self) -> None:
        self.model  = self.settings["model"]
        self.client = OpenAI(
            api_key  = self.settings["api_key"] or "nokey",
            base_url = self.settings["base_url"],
        )

    # ── Header (openCODE-style) ───────────────────────────────────────────────

    @staticmethod
    def _block_logo() -> Align:
        """openCODE-style embossed block wordmark (chat + RTD, split at letter boundary)."""
        logo = Text()
        for i, line in enumerate(_LOGO_ART):
            tone = _C["logo_dim"] if i < 2 else _C["logo_mid"] if i < 4 else _C["logo_hi"]
            logo.append(line[:_LOGO_SPLIT], style=tone)
            logo.append(line[_LOGO_SPLIT:] + "\n", style=_C["secondary"] if i >= 3 else tone)
        return Align.center(logo)

    def _status_strip(self) -> Table:
        active_name   = self.settings.get("active_name", "")
        model_label   = active_name or self.model.split("/")[-1]
        tool_count    = len(self.tools)
        mcp_host      = self.mcp_url.replace("http://", "").replace("https://", "")

        body = Text()
        body.append("▌ ", style=f"bold {_C['secondary']}")
        body.append("무엇이든 지시하세요… ", style=_C["muted"])
        body.append('"메모장에 hello 써줘"', style=_C["border"])
        body.append("\n  ", style="")
        body.append("Schedule", style=f"bold {_C['secondary']}")
        body.append("  ", style="")
        body.append(model_label, style=_C["text"])
        body.append("  ", style="")
        if tool_count:
            body.append(f"{tool_count} tools", style=_C["muted"])
            body.append("  ", style="")
            body.append(mcp_host, style=_C["muted"])
        else:
            body.append("MCP offline", style=_C["warning"])
        body.append("  ", style="")
        body.append(f"v{VERSION}", style=_C["muted"])

        strip = Table(show_header=False, box=None, pad_edge=False,
                      padding=(1, 2), width=_HEADER_W, style=f"on {_C['surface']}")
        strip.add_row(body)
        return strip

    @staticmethod
    def _shortcut_footer() -> Text:
        foot = Text()
        foot.append("/help", style=_C["text"])
        foot.append(" help     ", style=_C["muted"])
        foot.append("/models", style=_C["text"])
        foot.append(" models     ", style=_C["muted"])
        foot.append("/tools", style=_C["text"])
        foot.append(" tools     ", style=_C["muted"])
        foot.append("ctrl+c", style=_C["text"])
        foot.append(" exit", style=_C["muted"])
        return foot

    def print_header(self) -> None:
        c = self.console
        c.print()
        c.print(Align.center(self._block_logo()))
        c.print()
        c.print(Align.center(self._status_strip()))
        c.print()
        c.print(Align.right(self._shortcut_footer(), width=_HEADER_W))
        c.print()

    # ── Tool loading ──────────────────────────────────────────────────────────

    def load_tools(self) -> None:
        with self.console.status(
            f"[muted]connecting to MCP server...[/muted]", spinner="dots",
            spinner_style=f"bold {_C['primary']}",
        ):
            self.tools = fetch_mcp_tools(self.mcp_url)
        if not self.tools:
            self.console.print(
                f"  [warn]⚠[/warn]  [muted]도구를 가져오지 못했습니다. MCP 서버가 실행 중인지 확인하세요.[/muted]\n"
            )

    # ── Chat / tool-calling loop ───────────────────────────────────────────────

    def chat(self, user_message: str) -> None:
        c = self.console

        # ── user message header ──────────────────────────────────────────────
        c.print()
        c.print(f"  [muted]You[/muted]  [border]{'─' * 50}[/border]")
        c.print(f"  {user_message}")
        c.print()

        self.messages.append({"role": "user", "content": user_message})
        step_count       = 0
        execution_shown  = False

        while True:
            # ── LLM call ────────────────────────────────────────────────────
            with c.status(
                f"[muted]working...[/muted]", spinner="dots",
                spinner_style=f"bold {_C['primary']}",
            ):
                try:
                    response = self.client.chat.completions.create(
                        model    = self.model,
                        messages = self.messages,
                        tools    = self.tools or None,
                    )
                except Exception as e:
                    c.print(f"  [err]✗  LLM error:[/err] {e}\n")
                    self.messages.pop()
                    return

            msg = response.choices[0].message

            if msg.tool_calls:
                self.messages.append(msg)

                if not execution_shown:
                    c.print(f"  [border]{'─' * 53}[/border]")
                    execution_shown = True

                for tc in msg.tool_calls:
                    step_count += 1
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    t0     = time.time()
                    result = call_mcp_tool(self.mcp_url, tc.function.name, args)
                    elapsed = time.time() - t0

                    if _tool_ok(result):
                        status = f"[ok]✓[/ok]  [muted]{elapsed:.2f}s[/muted]"
                    else:
                        err = str(result.get("error", result))[:80]
                        status = f"[err]✗[/err]  [muted]{err}[/muted]"

                    name_col = f"[tool]◆[/tool]  [secondary]{tc.function.name}[/secondary]"
                    c.print(f"  {name_col:<52}{status}")

                    self.messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "content":      json.dumps(result, ensure_ascii=False),
                    })

            else:
                # ── agent response ───────────────────────────────────────────
                if execution_shown:
                    c.print(f"  [border]{'─' * 53}[/border]")

                content = (msg.content or "").strip()
                c.print()
                c.print(f"  [primary]chatRTD[/primary]  [border]{'─' * 46}[/border]")
                c.print(f"  {content}")
                c.print()

                self.messages.append({"role": "assistant", "content": content})
                break

    # ── Slash command dispatcher ──────────────────────────────────────────────

    def _handle_command(self, cmd: str) -> None:
        parts   = cmd.strip().split()
        command = parts[0].lower()

        if command in ("/exit", "/quit"):
            self.console.print(f"\n  [muted]bye.[/muted]\n")
            sys.exit(0)

        elif command == "/help":
            self.console.print(HELP_TEXT)

        elif command == "/clear":
            self.messages = [self.messages[0]]
            self.console.print(f"  [ok]✓[/ok]  [muted]conversation cleared[/muted]\n")

        elif command == "/tools":
            self._cmd_tools()

        elif command == "/skills":
            self._cmd_skills()

        elif command == "/skill":
            sid = parts[1] if len(parts) > 1 else ""
            if sid:
                self.chat(f"스킬 '{sid}'를 실행해줘")
            else:
                self.console.print(f"  [err]usage:[/err] /skill <skill_id>\n")

        elif command == "/analyze":
            self._cmd_analyze(parts[1:])

        elif command == "/models":
            sub = parts[1].lower() if len(parts) > 1 else ""
            if sub == "add":
                self._cmd_models_add(parts[2:])
            elif sub == "select":
                self._cmd_models_select(parts[2] if len(parts) > 2 else "")
            elif sub == "remove":
                self._cmd_models_remove(parts[2] if len(parts) > 2 else "")
            else:
                self._cmd_models_list()

        elif command == "/config":
            if len(parts) >= 4 and parts[1].lower() == "set":
                self._cmd_config_set(parts[2].lower(), parts[3])
            else:
                self._cmd_config_show()

        else:
            self.console.print(
                f"  [err]unknown command:[/err] {command}  [muted](try /help)[/muted]\n"
            )

    # ── /tools ────────────────────────────────────────────────────────────────

    def _cmd_tools(self) -> None:
        if not self.tools:
            self.console.print(f"  [muted]no tools loaded[/muted]\n")
            return
        t = Table(show_header=True, header_style=f"bold {_C['muted']}",
                  border_style=_C["border"], show_edge=False, pad_edge=True)
        t.add_column("tool", style=_C["secondary"], min_width=30)
        t.add_column("description", style=_C["text"])
        for tool in self.tools:
            fn = tool["function"]
            t.add_row(fn["name"], (fn.get("description") or "")[:72])
        self.console.print(t)
        self.console.print()

    # ── /skills ───────────────────────────────────────────────────────────────

    def _cmd_skills(self) -> None:
        skills = [t for t in self.tools if "skill" in t["function"]["name"].lower()]
        if not skills:
            self.console.print(f"  [muted]no skills found — try /tools[/muted]\n")
            return
        t = Table(show_header=True, header_style=f"bold {_C['muted']}",
                  border_style=_C["border"], show_edge=False, pad_edge=True)
        t.add_column("skill", style=_C["secondary"], min_width=30)
        t.add_column("description", style=_C["text"])
        for tool in skills:
            fn = tool["function"]
            t.add_row(fn["name"], (fn.get("description") or "")[:72])
        self.console.print(t)
        self.console.print()

    # ── /analyze ──────────────────────────────────────────────────────────────

    def _cmd_analyze(self, args: list) -> None:
        """automation graph 실행. 모드 선택 가능 (기본: semi)"""
        _MODES = {"auto", "semi", "manual"}

        if not args:
            self.console.print(
                f"  [err]usage:[/err] /analyze [auto|semi|manual] <query>\n"
            )
            return

        # 첫 번째 토큰이 모드명이면 분리, 아니면 semi 기본값
        if args[0].lower() in _MODES:
            mode  = args[0].lower()
            rest  = args[1:]
        else:
            mode  = "semi"
            rest  = args

        # manual 모드: 첫 토큰을 skill_id로 사용
        if mode == "manual":
            if not rest:
                self.console.print(
                    f"  [err]usage:[/err] /analyze manual <skill_id> [query]\n"
                )
                return
            skill_ids = [rest[0]]
            query     = " ".join(rest[1:]) or rest[0]
        else:
            skill_ids = []
            query     = " ".join(rest)

        if not query:
            self.console.print(f"  [err]✗[/err]  [muted]query가 비어 있습니다.[/muted]\n")
            return

        c = self.console
        c.print()
        c.print(f"  [muted]Analyze[/muted]  [border]{'─' * 48}[/border]")
        c.print(f"  [muted]mode :[/muted]  [secondary]{mode}[/secondary]")
        c.print(f"  [muted]query:[/muted]  {query}")
        c.print()

        try:
            from graph.automation_graph import run_automation
            from mcp_client import MCPClient
        except ImportError as e:
            c.print(f"  [err]✗  import error:[/err] {e}\n")
            return

        async def _run():
            mcp = MCPClient(self.mcp_url)
            return await run_automation(
                mcp       = mcp,
                query     = query,
                skill_ids = skill_ids,
                mode      = mode,
            )

        with c.status(
            f"[muted]analyzing... ({mode})[/muted]", spinner="dots",
            spinner_style=f"bold {_C['primary']}",
        ):
            try:
                result = asyncio.run(_run())
            except Exception as e:
                c.print(f"  [err]✗  automation error:[/err] {e}\n")
                return

        report  = result.get("report", "")
        details = result.get("report_details", {})

        c.print(f"  [primary]chatRTD[/primary]  [border]{'─' * 46}[/border]")
        c.print(f"  {report}")

        if details:
            history = details.get("history", [])
            if history:
                c.print()
                c.print(f"  [muted]─ execution log ({'─' * 30})[/muted]")
                for item in history:
                    skill   = item.get("skill_id", "")
                    status  = item.get("status", "")
                    color   = "ok" if status in ("done", "success") else "err"
                    c.print(f"  [tool]◆[/tool]  [secondary]{skill:<30}[/secondary] [{color}]{status}[/{color}]")
        c.print()

    # ── /models ───────────────────────────────────────────────────────────────

    def _cmd_models_list(self) -> None:
        models = self.cli_config.get("models", {})
        active = self.cli_config.get("active_model", "")
        if not models:
            self.console.print(
                f"  [muted]no models registered.\n"
                f"  /models add <name> --api-key <k> --base-url <u> --model <m>[/muted]\n"
            )
            return
        t = Table(show_header=True, header_style=f"bold {_C['muted']}",
                  border_style=_C["border"], show_edge=False, pad_edge=True)
        t.add_column("name",     style=_C["primary"],    min_width=12)
        t.add_column("model",    style=_C["secondary"],  min_width=22)
        t.add_column("base url", style=_C["text"],       min_width=35)
        t.add_column("",         justify="center",       min_width=2)
        for name, cfg in models.items():
            t.add_row(
                name,
                cfg.get("model", ""),
                cfg.get("base_url", "")[:38],
                f"[ok]●[/ok]" if name == active else "",
            )
        self.console.print(t)
        self.console.print()

    def _cmd_models_add(self, args: list) -> None:
        if not args:
            self.console.print(
                f"  [err]usage:[/err] /models add <name> --api-key <k> --base-url <u> --model <m>\n"
            )
            return
        name  = args[0]
        flags = _parse_flags(args[1:])
        self.cli_config.setdefault("models", {})[name] = {
            "api_key":  flags.get("api-key",  ""),
            "base_url": flags.get("base-url", ""),
            "model":    flags.get("model",    ""),
        }
        if not self.cli_config.get("active_model"):
            self.cli_config["active_model"] = name
        save_cli_config(self.cli_config)
        self.console.print(f"  [ok]✓[/ok]  [primary]{name}[/primary] [muted]registered[/muted]\n")

    def _cmd_models_select(self, name: str) -> None:
        if not name:
            self.console.print(f"  [err]usage:[/err] /models select <name>\n")
            return
        if name not in self.cli_config.get("models", {}):
            self.console.print(f"  [err]✗[/err]  [muted]'{name}' not found[/muted]\n")
            return
        self.cli_config["active_model"] = name
        save_cli_config(self.cli_config)
        mcfg = self.cli_config["models"][name]
        self.settings.update({
            "api_key":     mcfg.get("api_key", ""),
            "base_url":    mcfg.get("base_url", ""),
            "model":       mcfg.get("model", ""),
            "active_name": name,
        })
        self._init_llm_client()
        self.console.print(
            f"  [ok]✓[/ok]  switched to [primary]{name}[/primary]  [muted]({self.model})[/muted]\n"
        )

    def _cmd_models_remove(self, name: str) -> None:
        if not name:
            self.console.print(f"  [err]usage:[/err] /models remove <name>\n")
            return
        models = self.cli_config.get("models", {})
        if name not in models:
            self.console.print(f"  [err]✗[/err]  [muted]'{name}' not found[/muted]\n")
            return
        del models[name]
        if self.cli_config.get("active_model") == name:
            self.cli_config["active_model"] = next(iter(models), "")
        save_cli_config(self.cli_config)
        self.console.print(f"  [ok]✓[/ok]  [primary]{name}[/primary] [muted]removed[/muted]\n")

    # ── /config ───────────────────────────────────────────────────────────────

    def _cmd_config_show(self) -> None:
        active = self.cli_config.get("active_model", "(none)")
        mcfg   = self.cli_config.get("models", {}).get(active, {})
        key    = mcfg.get("api_key") or self.settings.get("api_key", "")
        masked = (key[:8] + "•" * min(8, max(0, len(key) - 8))) if key else "(none)"

        t = Table(show_header=False, border_style=_C["border"],
                  show_edge=False, pad_edge=True, min_width=52)
        t.add_column("k", style=_C["muted"],      min_width=14)
        t.add_column("v", style=_C["text"])
        t.add_row("mcp-url",      self.mcp_url)
        t.add_row("model-alias",  active)
        t.add_row("model",        mcfg.get("model")    or self.settings.get("model", ""))
        t.add_row("base-url",     mcfg.get("base_url") or self.settings.get("base_url", ""))
        t.add_row("api-key",      masked)
        self.console.print(t)
        self.console.print()

    def _cmd_config_set(self, key: str, value: str) -> None:
        if key == "mcp-url":
            self.cli_config["mcp_url"] = value
            self.mcp_url = value
            save_cli_config(self.cli_config)
            self.console.print(f"  [ok]✓[/ok]  mcp-url [muted]→[/muted] {value}\n")
        else:
            self.console.print(f"  [err]✗[/err]  unknown key: {key}  [muted](supported: mcp-url)[/muted]\n")

    # ── REPL ──────────────────────────────────────────────────────────────────

    def _print_slash_commands(self, prefix: str = "/") -> None:
        needle = prefix if prefix.startswith("/") else f"/{prefix}"
        matches = [(c, d) for c, d in _SLASH_COMMANDS if c.startswith(needle)]
        if not matches:
            self.console.print(f"  [muted]'{prefix}' 와 일치하는 명령이 없습니다.[/muted]\n")
            return
        t = Table(show_header=True, header_style=f"bold {_C['muted']}",
                  border_style=_C["border"], show_edge=False, pad_edge=True)
        t.add_column("command", style=_C["secondary"], min_width=22)
        t.add_column("description", style=_C["text"])
        for cmd, desc in matches:
            t.add_row(cmd, desc)
        self.console.print()
        self.console.print(t)
        self.console.print()

    def _read_user_input(self) -> str:
        if _HAS_PROMPT_TOOLKIT:
            if not hasattr(self, "_prompt_session"):
                self._prompt_session = PromptSession(
                    completer=_SlashCommandCompleter(),
                    complete_while_typing=True,
                )
            return self._prompt_session.prompt(ANSI(_PROMPT)).strip()
        return input(_PROMPT).strip()

    def run(self, single_query: Optional[str] = None) -> None:
        self.load_tools()
        self.print_header()

        if single_query:
            self.chat(single_query)
            return

        while True:
            try:
                user_input = self._read_user_input()
            except (KeyboardInterrupt, EOFError):
                self.console.print(f"\n  [muted]bye.[/muted]\n")
                break

            if not user_input:
                continue
            if user_input == "/":
                self._print_slash_commands()
                continue
            if user_input.startswith("/"):
                self._handle_command(user_input)
            else:
                self.chat(user_input)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    parser = argparse.ArgumentParser(prog="chatRTD",
                                     description="chatRTD — Windows Automation Scheduler CLI")
    parser.add_argument("query",        nargs="?",  help="실행할 작업 (비대화형 모드)")
    parser.add_argument("--no-server",  action="store_true", help="MCP 서버 자동 시작 비활성화")
    parser.add_argument("--server-url", default=None, dest="server_url")
    parser.add_argument("--model",      default=None)
    parser.add_argument("--api-key",    default=None, dest="api_key")
    args = parser.parse_args()

    cli_config = load_cli_config()
    overrides: dict = {}
    if args.server_url: overrides["mcp_url"] = args.server_url
    if args.model:      overrides["model"]   = args.model
    if args.api_key:    overrides["api_key"] = args.api_key

    settings = get_active_settings(cli_config, overrides)
    mcp_url  = settings["mcp_url"]

    # MCP 서버가 응답 없으면 자동 시작 (--no-server 로 비활성화 가능)
    server_proc = None
    if not args.no_server and not _is_mcp_running(mcp_url):
        try:
            port = int(mcp_url.split(":")[-1].split("/")[0])
        except Exception:
            port = 8000
        con = Console(force_terminal=True, theme=_THEME)
        with con.status(f"[muted]starting MCP server...[/muted]", spinner="dots",
                        spinner_style=f"bold {_C['primary']}"):
            server_proc = start_mcp_server(port)
        if server_proc:
            con.print(f"  [ok]✓[/ok]  [muted]MCP server started (port {port})[/muted]\n")
        else:
            con.print(f"  [warn]⚠[/warn]  [muted]MCP server 시작 실패 — mcp_server.py 경로 확인[/muted]\n")

    cli = ChatRTDCLI(settings, cli_config)
    try:
        cli.run(single_query=args.query)
    finally:
        if server_proc:
            server_proc.terminate()


if __name__ == "__main__":
    main()
