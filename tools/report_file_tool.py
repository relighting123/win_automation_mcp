"""
보고서 파일 읽기/쓰기 도구.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

import yaml

from core.file_path_policy import is_path_allowed, resolve_allowed_file, resolve_allowed_output_path
from core.report_paths import get_report_settings, parse_report_date

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def write_text_file(
    file_path: str,
    content: str,
    append: bool = False,
) -> str:
    """
    허용된 경로에 텍스트 파일을 저장합니다. 디렉터리가 없으면 생성합니다.

    Args:
        file_path: 저장 경로
        content: 본문
        append: True면 기존 파일 뒤에 추가
    """
    try:
        target = resolve_allowed_output_path(file_path, workspace=_PROJECT_ROOT)
        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as handle:
            if append and target.exists() and target.stat().st_size > 0:
                handle.write("\n")
            handle.write(content or "")

        return json.dumps(
            {
                "success": True,
                "file_path": str(target),
                "append": bool(append),
                "message": "파일 저장 완료",
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("write_text_file 실패: %s", file_path)
        return json.dumps(
            {"success": False, "message": str(exc), "file_path": file_path},
            ensure_ascii=False,
        )


async def read_text_file(file_path: str, max_chars: int = 200_000) -> str:
    """허용된 경로의 텍스트 파일을 읽습니다."""
    try:
        target = resolve_allowed_file(file_path, workspace=_PROJECT_ROOT)
        text = target.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]
        return json.dumps(
            {
                "success": True,
                "file_path": str(target),
                "text": text,
                "truncated": truncated,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {"success": False, "message": str(exc), "file_path": file_path},
            ensure_ascii=False,
        )


def _parse_file_date(path: Path) -> Optional[date]:
    try:
        return datetime.strptime(path.stem, "%Y-%m-%d").date()
    except ValueError:
        return None


async def list_report_files(
    directory: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    pattern: str = "*.md",
) -> str:
    """
    보고서 디렉터리에서 기간 내 MD 파일 목록을 반환합니다.

    Args:
        directory: 검색 폴더 (기본 daily_dir)
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        pattern: glob 패턴
    """
    try:
        settings = get_report_settings()
        root = Path(directory).expanduser() if directory else Path(settings["daily_dir"])
        if not root.is_absolute():
            root = (_PROJECT_ROOT / root).resolve()
        else:
            root = root.resolve()

        if not is_path_allowed(root, workspace=_PROJECT_ROOT):
            raise ValueError(f"허용되지 않은 보고서 경로입니다: {root}")

        start = parse_report_date(start_date) if start_date else None
        end = parse_report_date(end_date) if end_date else None

        files: list[dict[str, Any]] = []
        if root.is_dir():
            for path in sorted(root.glob(pattern)):
                if not path.is_file():
                    continue
                file_date = _parse_file_date(path)
                if start and file_date and file_date < start:
                    continue
                if end and file_date and file_date > end:
                    continue
                files.append(
                    {
                        "file_path": str(path),
                        "name": path.name,
                        "date": file_date.isoformat() if file_date else None,
                        "size": path.stat().st_size,
                    }
                )

        return json.dumps(
            {
                "success": True,
                "directory": str(root),
                "count": len(files),
                "files": files,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"success": False, "message": str(exc)}, ensure_ascii=False)


def register_report_file_tools(mcp: "FastMCP") -> None:
    mcp.tool()(write_text_file)
    mcp.tool()(read_text_file)
    mcp.tool()(list_report_files)
    logger.info("보고서 파일 도구 등록 완료")
