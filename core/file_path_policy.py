"""소스 파일 접근 경로 정책 (워크스페이스 + app_config/.env 허용 경로)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional

from core.llm_config import load_app_config


def _normalize_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.is_file():
        return resolved.parent
    return resolved


def _is_under_root(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _parse_path_list(raw: object) -> List[str]:
    if not isinstance(raw, list):
        return []
    return [str(entry).strip() for entry in raw if str(entry).strip()]


def _paths_from_env(env_name: str) -> List[str]:
    raw = (os.getenv(env_name) or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(os.pathsep) if part.strip()]


def _dedupe_roots(roots: Iterable[Path]) -> List[Path]:
    unique: List[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _roots_from_entries(entries: Iterable[str]) -> List[Path]:
    roots: List[Path] = []
    for entry in entries:
        try:
            roots.append(_normalize_root(Path(entry)))
        except Exception:
            continue
    return roots


def get_file_access_settings(config_path: Optional[str] = None) -> dict:
    """file_access 설정을 반환합니다."""
    config = load_app_config(config_path)
    file_access = config.get("file_access", {}) if isinstance(config, dict) else {}

    if not file_access:
        try:
            from core.app_session import AppSession

            session_config = AppSession.get_instance().config or {}
            if isinstance(session_config, dict):
                file_access = session_config.get("file_access", {}) or {}
        except Exception:
            pass

    yaml_present = isinstance(file_access, dict) and bool(file_access)

    if not isinstance(file_access, dict):
        file_access = {}

    allow_workspace = file_access.get("allow_workspace", True)
    if not yaml_present and os.getenv("CHATRTD_FILE_ALLOW_WORKSPACE") is not None:
        allow_workspace = str(os.getenv("CHATRTD_FILE_ALLOW_WORKSPACE")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    allowed_paths = _parse_path_list(file_access.get("allowed_paths"))
    read_paths = _parse_path_list(file_access.get("read_paths"))

    if not yaml_present and not allowed_paths:
        allowed_paths = _paths_from_env("CHATRTD_FILE_ALLOWED_PATHS")

    extra_read_paths = _paths_from_env("CHATRTD_FILE_READ_PATHS")

    return {
        "allow_workspace": bool(allow_workspace),
        "allowed_paths": allowed_paths,
        "read_paths": read_paths,
        "extra_read_paths": extra_read_paths,
    }


def get_allowed_read_roots(
    *,
    workspace: Optional[Path] = None,
    config_path: Optional[str] = None,
) -> List[Path]:
    """파일 읽기가 허용되는 루트 디렉터리 목록을 반환합니다."""
    settings = get_file_access_settings(config_path)
    roots: List[Path] = []

    if settings.get("allow_workspace", True):
        roots.append((workspace or Path.cwd()).resolve())

    read_entries = (
        list(settings.get("allowed_paths", []))
        + list(settings.get("read_paths", []))
        + list(settings.get("extra_read_paths", []))
    )
    roots.extend(_roots_from_entries(read_entries))
    return _dedupe_roots(roots)


def get_allowed_write_roots(
    *,
    workspace: Optional[Path] = None,
    config_path: Optional[str] = None,
) -> List[Path]:
    """파일 쓰기가 허용되는 루트 디렉터리 목록을 반환합니다."""
    settings = get_file_access_settings(config_path)
    roots: List[Path] = []

    if settings.get("allow_workspace", True):
        roots.append((workspace or Path.cwd()).resolve())

    write_entries = list(settings.get("allowed_paths", []))
    if not write_entries and not settings.get("read_paths") and not settings.get("extra_read_paths"):
        write_entries = _paths_from_env("CHATRTD_FILE_ALLOWED_PATHS")

    roots.extend(_roots_from_entries(write_entries))
    return _dedupe_roots(roots)


def get_allowed_file_roots(
    *,
    workspace: Optional[Path] = None,
    config_path: Optional[str] = None,
) -> List[Path]:
    """하위 호환: 읽기 허용 루트를 반환합니다."""
    return get_allowed_read_roots(workspace=workspace, config_path=config_path)


def is_path_allowed(
    target: Path,
    *,
    roots: Optional[Iterable[Path]] = None,
    config_path: Optional[str] = None,
    for_write: bool = False,
) -> bool:
    resolved = target.resolve()
    if roots is not None:
        allowed_roots = list(roots)
    elif for_write:
        allowed_roots = get_allowed_write_roots(config_path=config_path)
    else:
        allowed_roots = get_allowed_read_roots(config_path=config_path)
    return any(_is_under_root(resolved, root) for root in allowed_roots)


def resolve_allowed_file(
    file_path: str,
    *,
    workspace: Optional[Path] = None,
    config_path: Optional[str] = None,
) -> Path:
    """
    file_path를 정규화하고 읽기 정책을 통과하면 Path를 반환합니다.

    허용 범위:
      - cwd(워크스페이스) 하위 (allow_workspace=true, 기본)
      - file_access.allowed_paths (읽기/쓰기 공통)
      - file_access.read_paths (읽기 전용)
      - CHATRTD_FILE_READ_PATHS 환경변수 (읽기 전용 추가)
    """
    if not file_path or not str(file_path).strip():
        raise ValueError("file_path는 비어 있을 수 없습니다.")

    target = Path(file_path).expanduser()
    if not target.is_absolute():
        target = (workspace or Path.cwd()) / target
    target = target.resolve()

    allowed_roots = get_allowed_read_roots(workspace=workspace, config_path=config_path)
    if not allowed_roots:
        raise ValueError(
            "허용된 파일 읽기 경로가 없습니다. "
            "file_access.allow_workspace=true, file_access.allowed_paths/read_paths, "
            "또는 CHATRTD_FILE_READ_PATHS 를 설정하세요."
        )

    if not is_path_allowed(target, roots=allowed_roots):
        roots_text = ", ".join(str(root) for root in allowed_roots)
        raise ValueError(
            f"허용되지 않은 경로입니다: {file_path} "
            f"(읽기 허용 루트: {roots_text})"
        )
    if not target.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")
    if not target.is_file():
        raise ValueError(f"file_path는 파일이어야 합니다: {file_path}")
    return target


def resolve_allowed_directory(
    directory: str,
    *,
    workspace: Optional[Path] = None,
    config_path: Optional[str] = None,
) -> Path:
    """읽기 허용 루트 하위 디렉터리를 검증합니다."""
    if not directory or not str(directory).strip():
        raise ValueError("directory는 비어 있을 수 없습니다.")

    target = Path(directory).expanduser()
    if not target.is_absolute():
        target = (workspace or Path.cwd()) / target
    target = target.resolve()

    allowed_roots = get_allowed_read_roots(workspace=workspace, config_path=config_path)
    if not allowed_roots:
        raise ValueError(
            "허용된 파일 읽기 경로가 없습니다. "
            "file_access.allowed_paths/read_paths 또는 CHATRTD_FILE_READ_PATHS 를 설정하세요."
        )

    if not is_path_allowed(target, roots=allowed_roots):
        roots_text = ", ".join(str(root) for root in allowed_roots)
        raise ValueError(
            f"허용되지 않은 경로입니다: {directory} "
            f"(읽기 허용 루트: {roots_text})"
        )
    if not target.exists():
        raise FileNotFoundError(f"디렉터리를 찾을 수 없습니다: {directory}")
    if not target.is_dir():
        raise ValueError(f"directory는 폴더여야 합니다: {directory}")
    return target


def resolve_allowed_output_path(
    file_path: str,
    *,
    workspace: Optional[Path] = None,
    config_path: Optional[str] = None,
    create_parent: bool = True,
) -> Path:
    """
    새 파일 생성/덮어쓰기용 경로를 검증합니다.

    read_paths / CHATRTD_FILE_READ_PATHS 는 쓰기에 사용할 수 없습니다.
    """
    if not file_path or not str(file_path).strip():
        raise ValueError("file_path는 비어 있을 수 없습니다.")

    target = Path(file_path).expanduser()
    if not target.is_absolute():
        target = (workspace or Path.cwd()) / target
    target = target.resolve()

    allowed_roots = get_allowed_write_roots(workspace=workspace, config_path=config_path)
    if not allowed_roots:
        raise ValueError(
            "허용된 파일 쓰기 경로가 없습니다. "
            "file_access.allow_workspace=true 또는 file_access.allowed_paths를 설정하세요."
        )

    if not is_path_allowed(target, roots=allowed_roots):
        roots_text = ", ".join(str(root) for root in allowed_roots)
        raise ValueError(
            f"허용되지 않은 경로입니다: {file_path} "
            f"(쓰기 허용 루트: {roots_text})"
        )

    if create_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    return target
