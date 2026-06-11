"""launch_application 경로 인자 정규화 유틸리티."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

LAUNCH_TARGET_KEYS = (
    "executable_path",
    "argument_path",
    "exec_path",
    "file_path",
    "path",
)


def is_executable_file(path: str) -> bool:
    return path.lower().endswith((".exe", ".bat", ".cmd", ".msi"))


def pick_launch_target(args: Dict[str, Any]) -> Optional[str]:
    """실행 대상 경로를 별칭 키에서 우선순위대로 찾습니다."""
    for key in LAUNCH_TARGET_KEYS:
        value = args.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def resolve_launch_paths(
    args: Dict[str, Any],
    config_executable_path: Optional[str],
) -> Tuple[str, Optional[str], Dict[str, Any]]:
    """
    launch_application 인자를 정규화합니다.

    - argument_path / exec_path / file_path 등을 executable_path로 통합
    - .rul 등 데이터 파일 실행 시 connect_path가 없으면 app_config exe를 사용
    - 실행 대상 경로가 없을 때만 config executable_path로 fallback
    """
    normalized = dict(args)
    launch_target = pick_launch_target(normalized)
    connect_path = normalized.get("connect_path")

    if not launch_target:
        launch_target = config_executable_path or ""
    elif (
        not connect_path
        and config_executable_path
        and not is_executable_file(launch_target)
    ):
        connect_path = config_executable_path

    normalized["executable_path"] = launch_target
    if connect_path:
        normalized["connect_path"] = connect_path

    for key in LAUNCH_TARGET_KEYS:
        if key != "executable_path":
            normalized.pop(key, None)

    return launch_target, connect_path, normalized
