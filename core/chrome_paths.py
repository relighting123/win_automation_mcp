"""
OpenChrome용 Chrome/Chromium 실행 파일 경로 탐지.

Windows에서는 Google Chrome이 없어도 Microsoft Edge(Chromium)로 대체할 수 있습니다.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


def _first_existing(paths: list[Path]) -> Optional[str]:
    for path in paths:
        if path.is_file():
            return str(path)
    return None


def _windows_chrome_candidates() -> list[Path]:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

    candidates = [
        Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(program_files) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    if local_app_data:
        candidates.append(
            Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe"
        )
    return candidates


def _darwin_chrome_candidates() -> list[Path]:
    return [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]


def _linux_chrome_candidates() -> list[Path]:
    return [
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/snap/bin/chromium"),
    ]


def find_chrome_binary() -> Optional[str]:
    """시스템에서 Chrome/Chromium/Edge 실행 파일을 찾습니다."""
    explicit = (
        os.getenv("MCP_OPENCHROME_CHROME_PATH")
        or os.getenv("CHROME_PATH")
        or os.getenv("CHROME_BINARY")
    )
    if explicit and Path(explicit).is_file():
        return explicit

    if sys.platform == "win32":
        found = _first_existing(_windows_chrome_candidates())
        if found:
            return found
    elif sys.platform == "darwin":
        found = _first_existing(_darwin_chrome_candidates())
        if found:
            return found
    else:
        found = _first_existing(_linux_chrome_candidates())
        if found:
            return found

    for command in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        resolved = shutil.which(command)
        if resolved:
            return resolved

    return None


def chrome_missing_help_message() -> str:
    """Chrome/Edge 미설치 시 사용자 안내 문구."""
    if sys.platform == "win32":
        return (
            "[Chrome/Edge 없음] OpenChrome은 Chromium 기반 브라우저가 필요합니다.\n"
            "1) Google Chrome 설치: https://www.google.com/chrome/\n"
            "2) 또는 이미 Edge가 있다면 .env에 다음 중 하나를 설정하세요:\n"
            '   CHROME_PATH=C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe\n'
            "3) chatRTD를 재시작한 뒤 다시 시도하세요."
        )

    if sys.platform == "darwin":
        return (
            "[Chrome 없음] OpenChrome은 Chromium 기반 브라우저가 필요합니다.\n"
            "1) Google Chrome 설치: https://www.google.com/chrome/\n"
            "2) 또는 .env에 CHROME_PATH=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n"
            "3) chatRTD를 재시작한 뒤 다시 시도하세요."
        )

    return (
        "[Chrome 없음] OpenChrome은 Chromium 기반 브라우저가 필요합니다.\n"
        "1) google-chrome 또는 chromium 패키지를 설치하세요.\n"
        "2) 또는 .env에 CHROME_PATH=/usr/bin/google-chrome\n"
        "3) chatRTD를 재시작한 뒤 다시 시도하세요."
    )


def is_chrome_missing_error(message: str) -> bool:
    lowered = (message or "").lower()
    markers = (
        "chrome executable not found",
        "chrome binary",
        "chrome not found",
        "cannot find chrome",
        "install google chrome",
        "install chrome",
        "chrome_path",
    )
    return any(marker in lowered for marker in markers)
