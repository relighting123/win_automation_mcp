#!/usr/bin/env python3
"""
chatRTD Gemini CLI 런처

- MCP 서버(win_automation_mcp) 연결
- app_config.yaml / .env LLM 설정 검사 및 환경변수 주입
- chatRTD 브랜딩(터미널 타이틀, 시작 배너)
- gemini CLI 실행
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.llm_config import get_llm_settings, get_mcp_settings  # noqa: E402

_GEMINI_DIR = _PROJECT_ROOT / ".gemini"
_SETTINGS_EXAMPLE = _PROJECT_ROOT / "config" / "gemini_settings.json.example"
_SETTINGS_FILE = _GEMINI_DIR / "settings.json"

_LOGO = r"""
 ██████╗██╗  ██╗ █████╗ ████████╗██████╗ ████████╗██████╗ 
██╔════╝██║  ██║██╔══██╗╚══██╔══╝██╔══██╗╚══██╔══╝██╔══██╗
██║     ███████║███████║   ██║   ██████╔╝   ██║   ██║  ██║
██║     ██╔══██║██╔══██║   ██║   ██╔══██╗   ██║   ██║  ██║
╚██████╗██║  ██║██║  ██║   ██║   ██║  ██║   ██║   ██████╔╝
 ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚═════╝ 
        Windows Automation Scheduler (Gemini CLI)
"""

_GEMINI_API_HOSTS = (
    "generativelanguage.googleapis.com",
    "googleapis.com",
    "aiplatform.googleapis.com",
)


def _print(msg: str) -> None:
    print(msg, file=sys.stderr)


def _ensure_gemini_settings(mcp_url: str) -> None:
    _GEMINI_DIR.mkdir(parents=True, exist_ok=True)
    if _SETTINGS_FILE.exists():
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    elif _SETTINGS_EXAMPLE.exists():
        data = json.loads(_SETTINGS_EXAMPLE.read_text(encoding="utf-8"))
    else:
        data = {"mcpServers": {}}

    servers = data.setdefault("mcpServers", {})
    win = servers.setdefault("win-automation", {})
    win["httpUrl"] = mcp_url
    win.setdefault("trust", True)
    win.setdefault("timeout", 600000)

    _SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _mcp_reachable(mcp_url: str, timeout: float = 2.0) -> bool:
    try:
        # MCP streamable-http는 HEAD/GET이 405일 수 있어 연결만 확인
        requests.get(mcp_url, timeout=timeout)
        return True
    except requests.RequestException:
        return False


def _start_mcp_server() -> None:
    mcp_script = _PROJECT_ROOT / "mcp_server.py"
    if not mcp_script.exists():
        _print("[warn] mcp_server.py 를 찾을 수 없습니다. MCP를 수동으로 시작하세요.")
        return

    _print("[info] MCP 서버 시작 중...")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    subprocess.Popen(
        [
            sys.executable,
            str(mcp_script),
            "--transport",
            "http",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--path",
            "/mcp",
        ],
        cwd=str(_PROJECT_ROOT),
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(20):
        if _mcp_reachable(get_mcp_settings()["base_url"]):
            _print("[ok] MCP 서버 연결됨")
            return
        time.sleep(0.5)
    _print("[warn] MCP 서버 응답 대기 시간 초과. gemini 실행은 계속합니다.")


def _analyze_llm(llm: dict[str, str]) -> dict[str, Any]:
    provider = (llm.get("provider") or "").lower()
    base_url = (llm.get("base_url") or "").strip().rstrip("/")
    api_key = (llm.get("api_key") or "").strip()
    model = (llm.get("model") or "").strip()

    host = ""
    if base_url:
        try:
            host = urlparse(base_url).netloc.lower()
        except Exception:
            host = base_url.lower()

    is_openai_compat = (
        provider in {"openai_compatible", "openai"}
        or "groq.com" in host
        or "openai.com" in host
        or "/openai/" in base_url.lower()
    )
    is_gemini_host = any(token in host for token in _GEMINI_API_HOSTS)

    result: dict[str, Any] = {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key_set": bool(api_key),
        "compatible": False,
        "mode": "",
        "warnings": [],
        "env": {},
    }

    if is_openai_compat and not is_gemini_host:
        gemini_key = (os.getenv("GEMINI_API_KEY") or "").strip()
        if gemini_key:
            result["mode"] = "gemini_api_key_override"
            result["compatible"] = True
            result["env"]["GEMINI_API_KEY"] = gemini_key
            result["warnings"].append(
                "app_config 는 OpenAI 호환 API이지만 GEMINI_API_KEY 가 있어 Gemini API로 실행합니다."
            )
            return result

        result["mode"] = "unsupported_openai"
        result["warnings"].append(
            "app_config 의 OpenAI 호환 API(Groq 등)는 Gemini CLI에서 직접 사용할 수 없습니다."
        )
        result["warnings"].append(
            "Gemini CLI는 Google Gemini API 형식만 지원합니다 (GEMINI_API_KEY / GOOGLE_GEMINI_BASE_URL)."
        )
        if api_key:
            result["warnings"].append(
                "대안: GEMINI_API_KEY 를 설정하거나, chatRTD CLI(chatRTD)로 Groq 설정을 계속 사용하세요."
            )
        return result

    if api_key:
        result["env"]["GEMINI_API_KEY"] = api_key

    if base_url and not is_gemini_host:
        # 사내 Gemini 게이트웨이 등
        result["env"]["GOOGLE_GEMINI_BASE_URL"] = base_url
        result["mode"] = "gateway"
        result["compatible"] = True
        result["warnings"].append(
            f"커스텀 LLM 엔드포인트 사용: GOOGLE_GEMINI_BASE_URL={base_url}"
        )
        result["warnings"].append(
            "엔드포인트는 Gemini API 호환 형식이어야 합니다."
        )
        return result

    if api_key or os.getenv("GEMINI_API_KEY"):
        result["mode"] = "gemini_api_key"
        result["compatible"] = True
        if model:
            result["warnings"].append(
                f"모델은 .gemini/settings.json 의 model.name 으로 설정하세요 (요청: {model})."
            )
        return result

    result["mode"] = "oauth_or_missing_key"
    result["warnings"].append(
        "GEMINI_API_KEY 가 없습니다. gemini 실행 후 Google 로그인 또는 API 키를 설정하세요."
    )
    result["compatible"] = True  # OAuth 로그인 가능
    return result


def _apply_env(analysis: dict[str, Any]) -> None:
    os.environ["CLI_TITLE"] = "chatRTD"
    for key, value in analysis.get("env", {}).items():
        os.environ[key] = value


def _find_gemini_executable() -> list[str]:
    gemini = shutil.which("gemini")
    if gemini:
        return [gemini]
    npx = shutil.which("npx")
    if npx:
        return [npx, "-y", "@google/gemini-cli"]
    raise RuntimeError(
        "gemini CLI 를 찾을 수 없습니다. "
        "npm install -g @google/gemini-cli 또는 npx @google/gemini-cli"
    )


def main() -> int:
    _print(_LOGO)

    mcp = get_mcp_settings()
    mcp_url = mcp["base_url"]
    _ensure_gemini_settings(mcp_url)

    if not _mcp_reachable(mcp_url):
        _start_mcp_server()
    else:
        _print(f"[ok] MCP 서버 이미 실행 중: {mcp_url}")

    llm = get_llm_settings()
    analysis = _analyze_llm(llm)

    _print("\n── LLM 설정 검사 ──")
    _print(f"  provider : {analysis['provider'] or '(default)'}")
    _print(f"  base_url : {analysis['base_url'] or '(default)'}")
    _print(f"  model    : {analysis['model'] or '(gemini settings)'}")
    _print(f"  api_key  : {'설정됨' if analysis['api_key_set'] else '없음'}")
    _print(f"  mode     : {analysis['mode']}")

    for warning in analysis["warnings"]:
        _print(f"  [warn] {warning}")

    if analysis["mode"] == "unsupported_openai":
        _print(
            "\n[error] 현재 app_config LLM 설정은 Gemini CLI와 호환되지 않습니다.\n"
            "  1) GEMINI_API_KEY + Gemini 모델 사용\n"
            "  2) chatRTD CLI 유지: chatRTD\n"
        )
        return 1

    _apply_env(analysis)

    if os.getenv("CHATRTD_GEMINI_BRANDED") == "1":
        _print("[info] 브랜딩 패치 적용 빌드(CHATRTD_GEMINI_BRANDED=1)로 실행합니다.")

    cmd = _find_gemini_executable()
    _print(f"\n[info] 실행: {' '.join(cmd)}")
    _print("[info] MCP: /mcp 로 win-automation 연결 확인\n")

    os.chdir(_PROJECT_ROOT)
    try:
        os.execvp(cmd[0], cmd + sys.argv[1:])
    except OSError as exc:
        _print(f"[error] gemini 실행 실패: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
