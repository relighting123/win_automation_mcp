"""
소스 파일 검색/치환 도구

단일 MCP 서버에서 Ctrl+F + 바꾸기와 유사한 흐름을 수행합니다.
대용량 파일을 고려하여 기본적으로 라인 단위 스트리밍 방식으로 처리합니다.
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _resolve_workspace_file(file_path: str) -> Path:
    if not file_path or not str(file_path).strip():
        raise ValueError("file_path는 비어 있을 수 없습니다.")

    target = Path(file_path).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    target = target.resolve()

    workspace = Path.cwd().resolve()
    if not str(target).startswith(str(workspace)):
        raise ValueError(f"워크스페이스 외부 경로는 허용되지 않습니다: {file_path}")
    if not target.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")
    if not target.is_file():
        raise ValueError(f"file_path는 파일이어야 합니다: {file_path}")
    return target


def _find_occurrence_indices(line: str, search_text: str, case_sensitive: bool) -> List[int]:
    if case_sensitive:
        haystack = line
        needle = search_text
    else:
        haystack = line.lower()
        needle = search_text.lower()

    indices: List[int] = []
    cursor = 0
    while True:
        idx = haystack.find(needle, cursor)
        if idx < 0:
            break
        indices.append(idx)
        cursor = idx + len(needle)
    return indices


def find_text_in_file(
    file_path: str,
    search_text: str,
    case_sensitive: bool = False,
    context_lines: int = 2,
    max_matches: int = 20,
) -> str:
    """
    파일에서 특정 텍스트를 검색하고 라인 번호/컨텍스트를 반환합니다.

    대용량 파일 대응을 위해 전체 파일을 메모리에 올리지 않고 라인 스트리밍으로 처리합니다.
    """
    logger.info(
        "[Tool] find_text_in_file 호출: file=%s, case_sensitive=%s, max_matches=%s",
        file_path,
        case_sensitive,
        max_matches,
    )

    try:
        target = _resolve_workspace_file(file_path)
        if not search_text:
            raise ValueError("search_text는 비어 있을 수 없습니다.")
        if "\n" in search_text:
            raise ValueError("search_text의 멀티라인 검색은 지원하지 않습니다.")

        context_lines = max(int(context_lines), 0)
        max_matches = max(int(max_matches), 1)

        matches: List[Dict[str, Any]] = []
        before_buffer = deque(maxlen=context_lines)
        pending_context: List[Dict[str, Any]] = []

        stop_after_line: Optional[int] = None
        line_no = 0

        with target.open("r", encoding="utf-8", errors="replace", newline="") as src:
            for raw_line in src:
                line_no += 1
                line = raw_line.rstrip("\r\n")

                if pending_context:
                    completed: List[Dict[str, Any]] = []
                    for item in pending_context:
                        if len(item["context_after"]) < context_lines:
                            item["context_after"].append(line)
                        if len(item["context_after"]) >= context_lines:
                            completed.append(item)
                    if completed:
                        pending_context = [it for it in pending_context if it not in completed]

                hit_indices = _find_occurrence_indices(
                    line=line,
                    search_text=search_text,
                    case_sensitive=case_sensitive,
                )
                if hit_indices and len(matches) < max_matches:
                    match_entry = {
                        "line_number": line_no,
                        "occurrences_in_line": len(hit_indices),
                        "line_preview": line[:500],
                        "context_before": list(before_buffer),
                        "context_after": [],
                    }
                    matches.append(match_entry)
                    if context_lines > 0:
                        pending_context.append(match_entry)

                    if len(matches) >= max_matches and stop_after_line is None:
                        stop_after_line = line_no + context_lines

                before_buffer.append(line)

                if stop_after_line is not None and line_no >= stop_after_line and not pending_context:
                    break

        return json.dumps(
            {
                "success": True,
                "file_path": str(target),
                "file_size_bytes": target.stat().st_size,
                "search_text": search_text,
                "count": len(matches),
                "matches": matches,
                "message": f"{len(matches)}개의 매칭 라인을 찾았습니다." if matches else "매칭 결과가 없습니다.",
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error("[Tool] find_text_in_file 예외: %s", e)
        return json.dumps(
            {
                "success": False,
                "message": f"텍스트 검색 실패: {e}",
                "error_detail": str(e),
            },
            ensure_ascii=False,
        )


def _replace_single_occurrence(line: str, search_text: str, replacement_text: str, target_index: int) -> str:
    """line 내 target_index 위치의 1개 매칭만 교체합니다."""
    return line[:target_index] + replacement_text + line[target_index + len(search_text) :]


def replace_text_in_file(
    file_path: str,
    search_text: str,
    replacement_text: str,
    replace_all: bool = False,
    occurrence: int = 1,
    case_sensitive: bool = True,
    dry_run: bool = False,
    max_replacements: int = 10000,
) -> str:
    """
    파일에서 검색 텍스트를 찾아 치환합니다.

    - replace_all=False: occurrence(1-based)번째 매칭 1건만 치환
    - replace_all=True: 최대 max_replacements까지 모두 치환
    - 멀티라인 search_text는 지원하지 않습니다(대용량 스트리밍 안전성 우선)
    """
    logger.info(
        "[Tool] replace_text_in_file 호출: file=%s, replace_all=%s, occurrence=%s, dry_run=%s",
        file_path,
        replace_all,
        occurrence,
        dry_run,
    )

    try:
        target = _resolve_workspace_file(file_path)
        if not search_text:
            raise ValueError("search_text는 비어 있을 수 없습니다.")
        if "\n" in search_text:
            raise ValueError("search_text의 멀티라인 치환은 지원하지 않습니다.")
        if max_replacements < 1:
            raise ValueError("max_replacements는 1 이상이어야 합니다.")
        if not replace_all and occurrence < 1:
            raise ValueError("occurrence는 1 이상의 정수여야 합니다.")

        total_seen = 0
        replaced_count = 0
        line_no = 0
        replacements_preview: List[Dict[str, Any]] = []

        tmp_file: Optional[NamedTemporaryFile] = None
        tmp_path: Optional[Path] = None

        if not dry_run:
            tmp_file = NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                delete=False,
                dir=str(target.parent),
                prefix=f"{target.name}.mcp_edit_",
                suffix=".tmp",
            )
            tmp_path = Path(tmp_file.name)

        try:
            with target.open("r", encoding="utf-8", errors="replace", newline="") as src:
                for raw_line in src:
                    line_no += 1
                    line = raw_line
                    updated_line = line

                    hit_indices = _find_occurrence_indices(
                        line=line,
                        search_text=search_text,
                        case_sensitive=case_sensitive,
                    )
                    hit_count = len(hit_indices)

                    if hit_count > 0:
                        if replace_all:
                            remain_budget = max_replacements - replaced_count
                            if remain_budget > 0:
                                if remain_budget >= hit_count:
                                    if case_sensitive:
                                        updated_line = line.replace(search_text, replacement_text)
                                        applied = hit_count
                                    else:
                                        updated_line = line
                                        applied = 0
                                        for idx in reversed(hit_indices):
                                            updated_line = _replace_single_occurrence(
                                                updated_line,
                                                search_text,
                                                replacement_text,
                                                idx,
                                            )
                                            applied += 1
                                    replaced_count += applied
                                else:
                                    selected = hit_indices[:remain_budget]
                                    updated_line = line
                                    for idx in reversed(selected):
                                        updated_line = _replace_single_occurrence(
                                            updated_line,
                                            search_text,
                                            replacement_text,
                                            idx,
                                        )
                                    replaced_count += len(selected)

                                if line != updated_line and len(replacements_preview) < 20:
                                    replacements_preview.append(
                                        {
                                            "line_number": line_no,
                                            "before": line.rstrip("\r\n")[:300],
                                            "after": updated_line.rstrip("\r\n")[:300],
                                        }
                                    )
                        else:
                            if total_seen + hit_count >= occurrence and replaced_count == 0:
                                local_index = occurrence - total_seen - 1
                                target_idx = hit_indices[local_index]
                                updated_line = _replace_single_occurrence(
                                    line,
                                    search_text,
                                    replacement_text,
                                    target_idx,
                                )
                                replaced_count = 1
                                if len(replacements_preview) < 20:
                                    replacements_preview.append(
                                        {
                                            "line_number": line_no,
                                            "before": line.rstrip("\r\n")[:300],
                                            "after": updated_line.rstrip("\r\n")[:300],
                                        }
                                    )

                        total_seen += hit_count
                    if not dry_run and tmp_file is not None:
                        tmp_file.write(updated_line)

            if not dry_run and tmp_file is not None:
                tmp_file.flush()
                tmp_file.close()

            if replaced_count == 0:
                if tmp_path is not None and tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                return json.dumps(
                    {
                        "success": False,
                        "file_path": str(target),
                        "message": "치환할 매칭을 찾지 못했습니다.",
                        "replaced_count": 0,
                    },
                    ensure_ascii=False,
                )

            if replace_all and replaced_count >= max_replacements:
                logger.warning("max_replacements 한도에 도달했습니다: %s", max_replacements)

            if not dry_run and tmp_path is not None:
                os.replace(tmp_path, target)

            return json.dumps(
                {
                    "success": True,
                    "file_path": str(target),
                    "replaced_count": replaced_count,
                    "dry_run": dry_run,
                    "replace_all": replace_all,
                    "occurrence": occurrence,
                    "preview": replacements_preview,
                    "message": (
                        f"{replaced_count}개 매칭을 미리보기로 치환했습니다."
                        if dry_run
                        else f"{replaced_count}개 매칭을 치환하고 파일에 저장했습니다."
                    ),
                },
                ensure_ascii=False,
            )
        finally:
            if tmp_file is not None and not tmp_file.closed:
                tmp_file.close()
            if dry_run and tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
    except Exception as e:
        logger.error("[Tool] replace_text_in_file 예외: %s", e)
        return json.dumps(
            {
                "success": False,
                "message": f"텍스트 치환 실패: {e}",
                "error_detail": str(e),
            },
            ensure_ascii=False,
        )


def register_source_edit_tools(mcp: "FastMCP") -> None:
    """소스 검색/치환 도구를 FastMCP 서버에 등록합니다."""
    mcp.tool()(find_text_in_file)
    mcp.tool()(replace_text_in_file)
    logger.info("소스 편집 도구 등록 완료: find_text_in_file, replace_text_in_file")
