"""소스 파일 접근 경로 정책 (워크스페이스 + app_config 허용 경로)."""

from __future__ import annotations

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

    if not isinstance(file_access, dict):
        return {"allow_workspace": True, "allowed_paths": []}

    allow_workspace = file_access.get("allow_workspace", True)
    raw_paths = file_access.get("allowed_paths", [])
    allowed_paths = []
    if isinstance(raw_paths, list):
        allowed_paths = [str(p).strip() for p in raw_paths if str(p).strip()]

    return {
        "allow_workspace": bool(allow_workspace),
        "allowed_paths": allowed_paths,
    }


def get_allowed_file_roots(
    *,
    workspace: Optional[Path] = None,
    config_path: Optional[str] = None,
) -> List[Path]:
    """파일 접근이 허용되는 루트 디렉터리 목록을 반환합니다."""
    settings = get_file_access_settings(config_path)
    roots: List[Path] = []

    if settings.get("allow_workspace", True):
        roots.append((workspace or Path.cwd()).resolve())

    for entry in settings.get("allowed_paths", []):
        try:
            roots.append(_normalize_root(Path(entry)))
        except Exception:
            continue

    unique: List[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def is_path_allowed(
    target: Path,
    *,
    roots: Optional[Iterable[Path]] = None,
    config_path: Optional[str] = None,
) -> bool:
    resolved = target.resolve()
    allowed_roots = list(roots) if roots is not None else get_allowed_file_roots(config_path=config_path)
    return any(_is_under_root(resolved, root) for root in allowed_roots)


def resolve_allowed_file(
    file_path: str,
    *,
    workspace: Optional[Path] = None,
    config_path: Optional[str] = None,
) -> Path:
    """
    file_path를 정규화하고 접근 정책을 통과하면 Path를 반환합니다.

    허용 범위:
      - cwd(워크스페이스) 하위 (allow_workspace=true, 기본)
      - app_config.file_access.allowed_paths 에 등록된 디렉터리 하위
    """
    if not file_path or not str(file_path).strip():
        raise ValueError("file_path는 비어 있을 수 없습니다.")

    target = Path(file_path).expanduser()
    if not target.is_absolute():
        target = (workspace or Path.cwd()) / target
    target = target.resolve()

    allowed_roots = get_allowed_file_roots(workspace=workspace, config_path=config_path)
    if not allowed_roots:
        raise ValueError(
            "허용된 파일 접근 경로가 없습니다. "
            "file_access.allow_workspace=true 또는 file_access.allowed_paths를 설정하세요."
        )

    if not is_path_allowed(target, roots=allowed_roots):
        roots_text = ", ".join(str(root) for root in allowed_roots)
        raise ValueError(
            f"허용되지 않은 경로입니다: {file_path} "
            f"(허용 루트: {roots_text})"
        )
    if not target.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")
    if not target.is_file():
        raise ValueError(f"file_path는 파일이어야 합니다: {file_path}")
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

    기존 resolve_allowed_file 과 달리 파일이 없어도 허용합니다.
    """
    if not file_path or not str(file_path).strip():
        raise ValueError("file_path는 비어 있을 수 없습니다.")

    target = Path(file_path).expanduser()
    if not target.is_absolute():
        target = (workspace or Path.cwd()) / target
    target = target.resolve()

    allowed_roots = get_allowed_file_roots(workspace=workspace, config_path=config_path)
    if not allowed_roots:
        raise ValueError(
            "허용된 파일 접근 경로가 없습니다. "
            "file_access.allow_workspace=true 또는 file_access.allowed_paths를 설정하세요."
        )

    if not is_path_allowed(target, roots=allowed_roots):
        roots_text = ", ".join(str(root) for root in allowed_roots)
        raise ValueError(
            f"허용되지 않은 경로입니다: {file_path} "
            f"(허용 루트: {roots_text})"
        )

    if create_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    return target
