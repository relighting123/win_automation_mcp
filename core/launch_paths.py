"""launch_application 경로 인자 정규화 유틸리티."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

LAUNCH_TARGET_KEYS = (
    "file_path",
    "argument_path",
    "exec_path",
    "path",
)


def is_executable_file(path: str) -> bool:
    return path.lower().endswith((".exe", ".bat", ".cmd", ".msi"))


def normalize_launch_path(path: Optional[str]) -> str:
    """실행/데이터 파일 경로를 비교용으로 정규화합니다."""
    if not path:
        return ""
    raw = str(path).strip()
    try:
        resolved = str(Path(raw).resolve())
    except (OSError, ValueError):
        resolved = raw
    return resolved.lower().replace("/", "\\")


def pick_launch_target(args: Dict[str, Any]) -> Optional[str]:
    """실행 대상 경로를 별칭 키에서 우선순위대로 찾습니다."""
    for key in LAUNCH_TARGET_KEYS:
        value = args.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def resolve_launch_paths(
    args: Dict[str, Any],
    config_connect_path: Optional[str] = None,
) -> Tuple[str, Optional[str], Dict[str, Any]]:
    """
    launch_application 인자를 정규화합니다.

    - argument_path / exec_path / path 를 file_path로 통합
    - connect_path가 없으면 config.connect_path 사용
    - file_path가 없으면 빈 문자열 (실행 시 connect_path exe로 fallback)
    """
    normalized = dict(args)
    normalized.pop("executable_path", None)
    launch_target = pick_launch_target(normalized)
    connect_path = normalized.get("connect_path") or config_connect_path

    normalized["file_path"] = launch_target or ""
    if connect_path:
        normalized["connect_path"] = connect_path

    for key in LAUNCH_TARGET_KEYS:
        if key != "file_path":
            normalized.pop(key, None)

    return launch_target or "", connect_path, normalized
