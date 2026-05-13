"""
소스 파일 검색/치환 도구

단일 MCP 서버에서 Ctrl+F + 바꾸기와 유사한 흐름을 수행합니다.
대용량 파일을 고려하여 기본적으로 라인 단위 스트리밍 방식으로 처리합니다.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import deque
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

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


def _find_occurrence_indices(
    line: str,
    search_text: str,
    case_sensitive: bool,
    is_regex: bool = False,
) -> List[Tuple[int, int]]:
    """문자열 또는 정규표현식 매칭의 (시작, 끝) 인덱스 리스트를 반환합니다."""
    indices: List[Tuple[int, int]] = []
    
    if is_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            for m in re.finditer(search_text, line, flags=flags):
                indices.append((m.start(), m.end()))
        except re.error as e:
            logger.error("잘못된 정규표현식: %s", e)
            raise ValueError(f"잘못된 정규표현식입니다: {e}")
    else:
        if case_sensitive:
            haystack = line
            needle = search_text
        else:
            haystack = line.lower()
            needle = search_text.lower()

        cursor = 0
        while True:
            idx = haystack.find(needle, cursor)
            if idx < 0:
                break
            indices.append((idx, idx + len(needle)))
            cursor = idx + len(needle)
            
    return indices


def find_text_in_file(
    file_path: str,
    search_text: str,
    case_sensitive: bool = False,
    is_regex: bool = False,
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
                    is_regex=is_regex,
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


def _replace_single_occurrence(line: str, search_text: str, replacement_text: str, start_index: int, end_index: int) -> str:
    """line 내 [start_index:end_index] 범위를 교체합니다."""
    return line[:start_index] + replacement_text + line[end_index:]


def replace_text_in_file(
    file_path: str,
    search_text: str,
    replacement_text: str,
    replace_all: bool = False,
    occurrence: int = 1,
    case_sensitive: bool = True,
    is_regex: bool = False,
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
                        is_regex=is_regex,
                    )
                    hit_count = len(hit_indices)

                    if hit_count > 0:
                        if replace_all:
                            remain_budget = max_replacements - replaced_count
                            if remain_budget > 0:
                                if remain_budget >= hit_count:
                                    if not is_regex and case_sensitive:
                                        updated_line = line.replace(search_text, replacement_text)
                                        applied = hit_count
                                    else:
                                        updated_line = line
                                        applied = 0
                                        for start, end in reversed(hit_indices):
                                            updated_line = _replace_single_occurrence(
                                                updated_line,
                                                search_text,
                                                replacement_text,
                                                start,
                                                end,
                                            )
                                            applied += 1
                                    replaced_count += applied
                                else:
                                    selected = hit_indices[:remain_budget]
                                    updated_line = line
                                    for start, end in reversed(selected):
                                        updated_line = _replace_single_occurrence(
                                            updated_line,
                                            search_text,
                                            replacement_text,
                                            start,
                                            end,
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
                                start, end = hit_indices[local_index]
                                updated_line = _replace_single_occurrence(
                                    line,
                                    search_text,
                                    replacement_text,
                                    start,
                                    end,
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



def replace_text_with_context(
    file_path: str,
    search_text: str,
    replacement_text: str,
    context_text: str,
    context_lines: int = 5,
    case_sensitive: bool = True,
    is_regex: bool = False,
    is_context_regex: bool = False,
    dry_run: bool = False,
) -> str:
    """
    특정 문맥(context_text)이 근처에 있을 때만 검색 텍스트를 치환합니다.

    - search_text: 찾을 텍스트
    - replacement_text: 바꿀 텍스트
    - context_text: 근처에 있어야 하는 키워드
    - context_lines: 검색 텍스트 기준 앞뒤로 확인할 라인 수
    """
    logger.info(
        "[Tool] replace_text_with_context 호출: file=%s, search=%s, context=%s, dry_run=%s",
        file_path,
        search_text,
        context_text,
        dry_run,
    )

    try:
        target = _resolve_workspace_file(file_path)
        if not search_text:
            raise ValueError("search_text는 비어 있을 수 없습니다.")
        if not context_text:
            raise ValueError("context_text는 비어 있을 수 없습니다.")
        
        context_lines = max(int(context_lines), 0)
        
        # 전체 파일을 읽어서 라인 리스트로 변환 (컨텍스트 확인을 위해)
        # 대용량 파일의 경우 메모리 문제가 있을 수 있으나, 문맥 확인을 위해 일정 범위의 버퍼가 필요함.
        # 여기서는 구현의 단순성을 위해 전체를 읽거나, 슬라이딩 윈도우를 사용합니다.
        # 기존 streaming 형식을 유지하면서 슬라이딩 윈도우로 구현합니다.
        
        lines: List[str] = []
        with target.open("r", encoding="utf-8", errors="replace", newline="") as src:
            lines = src.readlines()

        replaced_count = 0
        replacements_preview: List[Dict[str, Any]] = []
        new_lines: List[str] = list(lines)

        for i, line in enumerate(lines):
            hit_indices = _find_occurrence_indices(
                line=line,
                search_text=search_text,
                case_sensitive=case_sensitive,
                is_regex=is_regex,
            )
            
            if hit_indices:
                # 문맥 확인 (i-context_lines ~ i+context_lines)
                start_idx = max(0, i - context_lines)
                end_idx = min(len(lines), i + context_lines + 1)
                context_window = lines[start_idx:end_idx]
                
                context_found = False
                c_flags = 0 if case_sensitive else re.IGNORECASE
                for c_line in context_window:
                    if is_context_regex:
                        if re.search(context_text, c_line, flags=c_flags):
                            context_found = True
                            break
                    else:
                        if case_sensitive:
                            if context_text in c_line:
                                context_found = True
                                break
                        else:
                            if context_text.lower() in c_line.lower():
                                context_found = True
                                break
                
                if context_found:
                    updated_line = line
                    if not is_regex and case_sensitive:
                        updated_line = line.replace(search_text, replacement_text)
                    else:
                        # 대소문자 무시 또는 정규표현식 치환 (뒤에서부터 교체하여 인덱스 유지)
                        for start, end in reversed(hit_indices):
                            updated_line = _replace_single_occurrence(
                                updated_line,
                                search_text,
                                replacement_text,
                                start,
                                end,
                            )
                    
                    if updated_line != line:
                        new_lines[i] = updated_line
                        replaced_count += 1
                        if len(replacements_preview) < 20:
                            replacements_preview.append({
                                "line_number": i + 1,
                                "before": line.rstrip("\r\n")[:300],
                                "after": updated_line.rstrip("\r\n")[:300]
                            })

        if replaced_count > 0 and not dry_run:
            with target.open("w", encoding="utf-8", newline="") as f:
                f.writelines(new_lines)

        return json.dumps(
            {
                "success": replaced_count > 0,
                "file_path": str(target),
                "replaced_count": replaced_count,
                "dry_run": dry_run,
                "preview": replacements_preview,
                "message": (
                    f"{replaced_count}개 매칭을 문맥 기반으로 치환했습니다."
                    if replaced_count > 0
                    else "조건에 맞는 매칭을 찾지 못했습니다."
                ),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error("[Tool] replace_text_with_context 예외: %s", e)
        return json.dumps(
            {
                "success": False,
                "message": f"문맥 기반 치환 실패: {e}",
                "error_detail": str(e),
            },
            ensure_ascii=False,
        )


def register_source_edit_tools(mcp: "FastMCP") -> None:
    """소스 검색/치환 도구를 FastMCP 서버에 등록합니다."""
    mcp.tool()(find_text_in_file)
    mcp.tool()(replace_text_in_file)
    mcp.tool()(replace_text_with_context)
    logger.info("소스 편집 도구 등록 완료: find_text_in_file, replace_text_in_file, replace_text_with_context")
