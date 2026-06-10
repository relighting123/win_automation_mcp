#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chatRTD — Windows Automation Scheduler CLI"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── Project root on sys.path ─────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.llm_config import get_llm_settings, get_mcp_settings

# ── Constants ─────────────────────────────────────────────────────────────────
VERSION = "0.1.0"
CONFIG_DIR = Path.home() / ".chatRTD"
CONFIG_FILE = CONFIG_DIR / "config.json"

SYSTEM_PROMPT = (
    "당신은 Windows 자동화 스케줄링 에이전트입니다.\n"
    "사용자의 요청을 분석하여 필요한 도구들을 순서대로 호출하세요.\n"
    "각 도구 실행 결과를 바탕으로 다음 단계를 결정하고,\n"
    "모든 작업이 완료되면 한국어로 최종 결과를 간결하게 보고하세요."
)

HELP_TEXT = """
[bold blue]chatRTD[/bold blue]  [dim]Automation Scheduler v{ver}[/dim]

[bold cyan]일반 명령어[/bold cyan]
  /help              이 도움말
  /exit  /quit       종료
  /clear             대화 기록 초기화

[bold cyan]도구 & 스킬[/bold cyan]
  /tools             사용 가능한 도구 목록
  /skills            스킬 목록
  /skill <id>        스킬 직접 실행

[bold cyan]모델 관리[/bold cyan]
  /models                                                    등록된 모델 목록
  /models add <이름> --api-key <키> --base-url <URL> --model <모델명>  모델 등록
  /models select <이름>                                      활성 모델 전환
  /models remove <이름>                                      모델 삭제

[bold cyan]설정[/bold cyan]
  /config                      현재 설정 확인
  /config set mcp-url <URL>    MCP 서버 URL 변경

[bold cyan]단일 명령 모드[/bold cyan]
  chatRTD "메모장에 오늘 날짜 써줘"
  chatRTD --start-server
""".format(ver=VERSION)


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
    """활성 모델 기준 최종 설정 반환. 우선순위: 인수 override > CLI config > app_config.yaml"""
    overrides = overrides or {}

    app = get_llm_settings()
    mcp = get_mcp_settings()

    models = cli_config.get("models", {})
    active_name = cli_config.get("active_model", "")
    active_cfg = models.get(active_name, {}) if active_name else {}

    return {
        "api_key": overrides.get("api_key") or active_cfg.get("api_key") or app.get("api_key", ""),
        "base_url": overrides.get("base_url") or active_cfg.get("base_url") or app.get("base_url", ""),
        "model": overrides.get("model") or active_cfg.get("model") or app.get("model", ""),
        "mcp_url": overrides.get("mcp_url") or cli_config.get("mcp_url") or mcp.get("base_url", "http://localhost:8000/mcp"),
        "active_name": active_name,
    }


# ── MCP helpers ───────────────────────────────────────────────────────────────

def _mcp_headers() -> dict:
    return {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }


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
    session_id = _mcp_init(mcp_url, headers)
    if not session_id:
        return []
    headers["mcp-session-id"] = session_id
    try:
        res = requests.post(
            mcp_url,
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers=headers,
            timeout=15,
        )
        if res.status_code == 200:
            result = _parse_sse_result(res)
            if result and "tools" in result:
                return [
                    {
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "parameters": t.get("inputSchema", {}),
                        },
                    }
                    for t in result["tools"]
                ]
    except Exception:
        pass
    return []


def call_mcp_tool(mcp_url: str, name: str, arguments: dict) -> dict:
    headers = _mcp_headers()
    session_id = _mcp_init(mcp_url, headers)
    if not session_id:
        return {"error": "MCP 서버에 연결할 수 없습니다"}
    headers["mcp-session-id"] = session_id
    try:
        requests.post(
            mcp_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=headers,
            timeout=2,
        )
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
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


# ── MCP server subprocess ─────────────────────────────────────────────────────

def start_mcp_server(port: int = 8000) -> Optional[subprocess.Popen]:
    server_script = _PROJECT_ROOT / "mcp_server.py"
    if not server_script.exists():
        return None
    proc = subprocess.Popen(
        [sys.executable, str(server_script), "--transport", "http", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(15):
        time.sleep(1)
        try:
            requests.get(f"http://localhost:{port}/", timeout=1)
            return proc
        except Exception:
            pass
    return proc


# ── Flag parser ───────────────────────────────────────────────────────────────

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


# ── Main CLI class ─────────────────────────────────────────────────────────────

class ChatRTDCLI:
    def __init__(self, settings: dict, cli_config: dict):
        self.console = Console(force_terminal=True)
        self.settings = settings
        self.cli_config = cli_config
        self.mcp_url: str = settings["mcp_url"]
        self.tools: list = []
        self.messages: list = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._init_llm_client()

    def _init_llm_client(self) -> None:
        self.model = self.settings["model"]
        self.client = OpenAI(
            api_key=self.settings["api_key"] or "nokey",
            base_url=self.settings["base_url"],
        )

    # ── Header ────────────────────────────────────────────────────────────────

    def print_header(self) -> None:
        active_name = self.settings.get("active_name", "")
        model_display = f"{active_name} / {self.model}" if active_name else self.model
        tool_info = f"  Tools : {len(self.tools)} loaded\n" if self.tools else ""

        lines = Text()
        lines.append(f"  chatRTD  Automation Scheduler  v{VERSION}\n", style="bold blue")
        lines.append(f"  Server : {self.mcp_url}\n", style="dim")
        lines.append(f"  Model  : {model_display}\n", style="cyan")
        if tool_info:
            lines.append(tool_info, style="dim")
        lines.append("  /help 도움말  |  Ctrl+C 종료", style="dim")

        self.console.print(Panel(lines, border_style="blue"))
        self.console.print()

    # ── Tool loading ──────────────────────────────────────────────────────────

    def load_tools(self) -> None:
        with self.console.status("[dim]MCP 서버 도구 목록 로딩 중...[/dim]", spinner="dots"):
            self.tools = fetch_mcp_tools(self.mcp_url)
        if not self.tools:
            self.console.print(
                "[yellow]⚠[/yellow]  도구를 가져오지 못했습니다. "
                "MCP 서버가 실행 중인지 확인하세요.\n"
            )

    # ── Chat / tool-calling loop ───────────────────────────────────────────────

    def chat(self, user_message: str) -> None:
        self.messages.append({"role": "user", "content": user_message})
        step_count = 0
        execution_started = False

        while True:
            with self.console.status("[bold cyan]Planning task...[/bold cyan]", spinner="dots"):
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=self.messages,
                        tools=self.tools or None,
                    )
                except Exception as e:
                    self.console.print(f"[red]LLM 오류: {e}[/red]\n")
                    self.messages.pop()
                    return

            msg = response.choices[0].message

            if msg.tool_calls:
                self.messages.append(msg)
                total = len(msg.tool_calls)

                if not execution_started:
                    self.console.rule("[dim]Task Execution[/dim]", style="dim")
                    execution_started = True

                for tc in msg.tool_calls:
                    step_count += 1
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    self.console.print(
                        f"  [[dim]{step_count}/{total}[/dim]]  [cyan]{tc.function.name}[/cyan]"
                    )

                    t0 = time.time()
                    result = call_mcp_tool(self.mcp_url, tc.function.name, args)
                    elapsed = time.time() - t0

                    is_error = isinstance(result, dict) and "error" in result
                    if not is_error:
                        # content 배열 형식 처리
                        success = True
                        if isinstance(result, dict) and "content" in result:
                            for item in result.get("content", []):
                                if isinstance(item, dict):
                                    text = item.get("text", "")
                                    try:
                                        parsed = json.loads(text)
                                        if isinstance(parsed, dict):
                                            success = parsed.get("success", True)
                                    except Exception:
                                        pass
                        self.console.print(
                            f"         [green]✓[/green]  done   {elapsed:.2f}s"
                        )
                    else:
                        err_msg = str(result.get("error", result))[:100]
                        self.console.print(
                            f"         [red]✗[/red]  error  {err_msg}"
                        )

                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })

            else:
                if execution_started:
                    self.console.rule(style="dim")
                    self.console.print()

                content = (msg.content or "").strip()
                self.console.print(f"[bold][report][/bold]  {content}\n")
                self.messages.append({"role": "assistant", "content": content})
                break

    # ── Slash command dispatcher ──────────────────────────────────────────────

    def _handle_command(self, cmd: str) -> None:
        parts = cmd.strip().split()
        command = parts[0].lower()

        if command in ("/exit", "/quit"):
            self.console.print("[dim]chatRTD를 종료합니다.[/dim]")
            sys.exit(0)

        elif command == "/help":
            self.console.print(HELP_TEXT)

        elif command == "/clear":
            self.messages = [self.messages[0]]
            self.console.print("[green]✓[/green]  대화 기록이 초기화되었습니다.\n")

        elif command == "/tools":
            self._cmd_tools()

        elif command == "/skills":
            self._cmd_skills()

        elif command == "/skill":
            skill_id = parts[1] if len(parts) > 1 else ""
            if skill_id:
                self.chat(f"스킬 '{skill_id}'를 실행해줘")
            else:
                self.console.print("[red]사용법: /skill <skill_id>[/red]")

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
                f"[red]알 수 없는 명령어: {command}[/red]  /help 로 도움말 확인\n"
            )

    # ── /tools ────────────────────────────────────────────────────────────────

    def _cmd_tools(self) -> None:
        if not self.tools:
            self.console.print("[dim]도구 목록이 비어 있습니다.[/dim]")
            return
        table = Table(show_header=True, header_style="bold cyan", border_style="dim")
        table.add_column("도구명", style="cyan", min_width=32)
        table.add_column("설명")
        for t in self.tools:
            fn = t["function"]
            table.add_row(fn["name"], (fn.get("description") or "")[:80])
        self.console.print(table)
        self.console.print()

    # ── /skills ───────────────────────────────────────────────────────────────

    def _cmd_skills(self) -> None:
        skills = [t for t in self.tools if "skill" in t["function"]["name"].lower()]
        if not skills:
            self.console.print("[dim]스킬 도구를 찾을 수 없습니다. /tools 로 전체 목록 확인[/dim]")
            return
        table = Table(show_header=True, header_style="bold cyan", border_style="dim")
        table.add_column("스킬 ID", style="cyan", min_width=32)
        table.add_column("설명")
        for t in skills:
            fn = t["function"]
            table.add_row(fn["name"], (fn.get("description") or "")[:80])
        self.console.print(table)
        self.console.print()

    # ── /models ───────────────────────────────────────────────────────────────

    def _cmd_models_list(self) -> None:
        models = self.cli_config.get("models", {})
        active = self.cli_config.get("active_model", "")
        if not models:
            self.console.print(
                "[dim]등록된 모델이 없습니다.\n"
                "/models add <이름> --api-key <키> --base-url <URL> --model <모델>[/dim]\n"
            )
            return
        table = Table(show_header=True, header_style="bold cyan", border_style="dim")
        table.add_column("이름", style="cyan", min_width=12)
        table.add_column("모델", min_width=22)
        table.add_column("Base URL", min_width=35)
        table.add_column("", justify="center", min_width=4)
        for name, cfg in models.items():
            table.add_row(
                name,
                cfg.get("model", ""),
                cfg.get("base_url", "")[:38],
                "[green]●[/green]" if name == active else "",
            )
        self.console.print(table)
        self.console.print()

    def _cmd_models_add(self, args: list) -> None:
        if not args:
            self.console.print(
                "[red]사용법: /models add <이름> --api-key <키> --base-url <URL> --model <모델>[/red]"
            )
            return
        name = args[0]
        flags = _parse_flags(args[1:])
        cfg = self.cli_config.setdefault("models", {})
        cfg[name] = {
            "api_key": flags.get("api-key", ""),
            "base_url": flags.get("base-url", ""),
            "model": flags.get("model", ""),
        }
        if not self.cli_config.get("active_model"):
            self.cli_config["active_model"] = name
        save_cli_config(self.cli_config)
        self.console.print(f"[green]✓[/green]  모델 [cyan]{name}[/cyan] 등록 완료\n")

    def _cmd_models_select(self, name: str) -> None:
        if not name:
            self.console.print("[red]사용법: /models select <이름>[/red]")
            return
        if name not in self.cli_config.get("models", {}):
            self.console.print(f"[red]'{name}' 모델이 등록되어 있지 않습니다.[/red]")
            return
        self.cli_config["active_model"] = name
        save_cli_config(self.cli_config)
        mcfg = self.cli_config["models"][name]
        self.settings.update({
            "api_key": mcfg.get("api_key", ""),
            "base_url": mcfg.get("base_url", ""),
            "model": mcfg.get("model", ""),
            "active_name": name,
        })
        self._init_llm_client()
        self.console.print(
            f"[green]✓[/green]  Switched to [cyan]{name}[/cyan]  ({self.model})\n"
        )

    def _cmd_models_remove(self, name: str) -> None:
        if not name:
            self.console.print("[red]사용법: /models remove <이름>[/red]")
            return
        models = self.cli_config.get("models", {})
        if name not in models:
            self.console.print(f"[red]'{name}' 모델이 없습니다.[/red]")
            return
        del models[name]
        if self.cli_config.get("active_model") == name:
            self.cli_config["active_model"] = next(iter(models), "")
        save_cli_config(self.cli_config)
        self.console.print(f"[green]✓[/green]  모델 [cyan]{name}[/cyan] 삭제됨\n")

    # ── /config ───────────────────────────────────────────────────────────────

    def _cmd_config_show(self) -> None:
        active = self.cli_config.get("active_model", "(없음)")
        mcfg = self.cli_config.get("models", {}).get(active, {})
        key = mcfg.get("api_key") or self.settings.get("api_key", "")
        masked_key = (key[:8] + "*" * max(0, len(key) - 8)) if key else "(없음)"

        table = Table(show_header=False, border_style="dim", min_width=55)
        table.add_column("key", style="cyan", min_width=16)
        table.add_column("value")
        table.add_row("mcp-url", self.mcp_url)
        table.add_row("active-model", active)
        table.add_row("model", mcfg.get("model") or self.settings.get("model", ""))
        table.add_row("base-url", mcfg.get("base_url") or self.settings.get("base_url", ""))
        table.add_row("api-key", masked_key)
        self.console.print(table)
        self.console.print()

    def _cmd_config_set(self, key: str, value: str) -> None:
        if key == "mcp-url":
            self.cli_config["mcp_url"] = value
            self.mcp_url = value
            save_cli_config(self.cli_config)
            self.console.print(f"[green]✓[/green]  mcp-url → {value}\n")
        else:
            self.console.print(f"[red]알 수 없는 설정 키: {key}[/red]  (지원: mcp-url)\n")

    # ── REPL ──────────────────────────────────────────────────────────────────

    def run(self, single_query: Optional[str] = None) -> None:
        self.load_tools()
        self.print_header()

        if single_query:
            self.chat(single_query)
            return

        while True:
            try:
                user_input = input("[task] > ").strip()
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[dim]chatRTD를 종료합니다.[/dim]")
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                self._handle_command(user_input)
            else:
                self.chat(user_input)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    # Windows CMD 한글 출력 호환
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog="chatRTD",
        description="chatRTD — Windows Automation Scheduler CLI",
    )
    parser.add_argument("query", nargs="?", help="실행할 작업 (비대화형 모드)")
    parser.add_argument("--start-server", action="store_true", help="MCP 서버 자동 시작")
    parser.add_argument("--server-url", default=None, dest="server_url", help="MCP 서버 URL override")
    parser.add_argument("--model", default=None, help="모델 이름 override (이 세션만)")
    parser.add_argument("--api-key", default=None, dest="api_key", help="API 키 override (이 세션만)")
    args = parser.parse_args()

    cli_config = load_cli_config()

    overrides: dict = {}
    if args.server_url:
        overrides["mcp_url"] = args.server_url
    if args.model:
        overrides["model"] = args.model
    if args.api_key:
        overrides["api_key"] = args.api_key

    settings = get_active_settings(cli_config, overrides)

    server_proc = None
    if args.start_server:
        console = Console(force_terminal=True)
        with console.status("[dim]MCP 서버 시작 중...[/dim]", spinner="dots"):
            server_proc = start_mcp_server()
        if server_proc:
            console.print("[green]✓[/green]  MCP 서버 시작됨\n")
        else:
            console.print("[yellow]⚠[/yellow]  MCP 서버 시작 실패 — mcp_server.py 경로 확인\n")

    cli = ChatRTDCLI(settings, cli_config)

    try:
        cli.run(single_query=args.query)
    finally:
        if server_proc:
            server_proc.terminate()


if __name__ == "__main__":
    main()
