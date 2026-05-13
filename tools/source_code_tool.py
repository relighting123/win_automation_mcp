"""
파일 내 소스 검색/치환 도구

LLM이 코드 파일의 특정 구간을 찾고 안전하게 치환할 수 있도록 지원합니다.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _resolve_file_path(file_path: str) -> Path:
    """
    작업 대상 파일 경로를 검증하고 절대 경로로 반환합니다.
    """
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
        raise ValueError(f"파일 경로만 허용됩니다: {file_path}")
    return target


def _line_number_from_offset(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _build_context(lines: List[str], start_line: int, end_line: int, context_lines: int) -> Dict[str, List[str]]:
    before_start = max(1, start_line - context_lines)
    after_end = min(len(lines), end_line + context_lines)

    before = lines[before_start - 1 : start_line - 1]
    after = lines[end_line:after_end]
    return {"before": before, "after": after}


def _compile_pattern(query: str, match_mode: str, case_sensitive: bool) -> re.Pattern[str]:
    if not query:
        raise ValueError("query/search_text는 비어 있을 수 없습니다.")

    flags = 0 if case_sensitive else re.IGNORECASE
    if match_mode == "regex":
        return re.compile(query, flags=flags | re.MULTILINE)
    if match_mode in {"contains", "exact"}:
        return re.compile(re.escape(query), flags=flags | re.MULTILINE)
    raise ValueError("match_mode는 contains, exact, regex 중 하나여야 합니다.")


def find_source_in_file(
    file_path: str,
    query: str,
    match_mode: str = "contains",
    case_sensitive: bool = False,
    context_lines: int = 2,
    max_matches: int = 20,
) -> str:
    """
    파일에서 특정 텍스트(또는 정규식) 구간을 검색합니다.

    Args:
        file_path: 검색 대상 파일 경로 (워크스페이스 기준 상대/절대 경로)
        query: 검색할 텍스트 또는 정규식
        match_mode: contains | exact | regex
        case_sensitive: 대소문자 구분 여부
        context_lines: 매칭 구간 앞뒤 컨텍스트 라인 수
        max_matches: 반환할 최대 매칭 개수
    """
    logger.info(
        "[Tool] find_source_in_file 호출: file=%s, query=%s, mode=%s",
        file_path,
        query,
        match_mode,
    )

    try:
        target = _resolve_file_path(file_path)
        content = target.read_text(encoding="utf-8")
        lines = content.splitlines()
        pattern = _compile_pattern(query=query, match_mode=match_mode, case_sensitive=case_sensitive)

        matches = []
        for idx, match in enumerate(pattern.finditer(content), start=1):
            start_line = _line_number_from_offset(content, match.start())
            end_line = _line_number_from_offset(content, match.end())
            context = _build_context(lines, start_line, end_line, context_lines)
            snippet = match.group(0)
            if len(snippet) > 200:
                snippet = snippet[:200] + "...(truncated)"

            matches.append(
                {
                    "index": idx,
                    "start_line": start_line,
                    "end_line": end_line,
                    "matched_text": snippet,
                    "context_before": context["before"],
                    "context_after": context["after"],
                }
            )
            if len(matches) >= max_matches:
                break

        result: Dict[str, Any] = {
            "success": True,
            "file_path": str(target),
            "count": len(matches),
            "matches": matches,
            "message": f"{len(matches)}개 매칭을 찾았습니다." if matches else "매칭 결과가 없습니다.",
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("[Tool] find_source_in_file 예외: %s", e)
        return json.dumps(
            {
                "success": False,
                "message": f"소스 검색 실패: {e}",
                "error_detail": str(e),
            },
            ensure_ascii=False,
        )


def replace_source_in_file(
    file_path: str,
    search_text: str,
    replacement_text: str,
    match_mode: str = "exact",
    replace_all: bool = False,
    occurrence: int = 1,
    case_sensitive: bool = True,
    dry_run: bool = False,
) -> str:
    """
    파일에서 찾은 텍스트 구간을 치환합니다.

    Args:
        file_path: 수정 대상 파일 경로
        search_text: 찾을 텍스트 또는 정규식
        replacement_text: 치환할 텍스트
        match_mode: exact | contains | regex
        replace_all: true면 전체 매칭 치환
        occurrence: replace_all=false일 때 치환할 1-based 순번
        case_sensitive: 대소문자 구분 여부
        dry_run: true면 파일 저장 없이 변경 요약만 반환
    """
    logger.info(
        "[Tool] replace_source_in_file 호출: file=%s, mode=%s, replace_all=%s, occurrence=%s, dry_run=%s",
        file_path,
        match_mode,
        replace_all,
        occurrence,
        dry_run,
    )

    try:
        target = _resolve_file_path(file_path)
        content = target.read_text(encoding="utf-8")
        pattern = _compile_pattern(query=search_text, match_mode=match_mode, case_sensitive=case_sensitive)

        all_matches = list(pattern.finditer(content))
        if not all_matches:
            return json.dumps(
                {
                    "success": False,
                    "message": "치환 대상 텍스트를 찾지 못했습니다.",
                    "file_path": str(target),
                },
                ensure_ascii=False,
            )

        if replace_all:
            selected_matches = all_matches
        else:
            if occurrence < 1:
                raise ValueError("occurrence는 1 이상의 정수여야 합니다.")
            if occurrence > len(all_matches):
                raise ValueError(f"occurrence={occurrence}는 매칭 개수({len(all_matches)})를 초과합니다.")
            selected_matches = [all_matches[occurrence - 1]]

        new_content = content
        replacements_summary = []
        for match in reversed(selected_matches):
            start_line = _line_number_from_offset(content, match.start())
            end_line = _line_number_from_offset(content, match.end())
            before_text = match.group(0)
            replacements_summary.append(
                {
                    "start_line": start_line,
                    "end_line": end_line,
                    "before": before_text[:200] + ("...(truncated)" if len(before_text) > 200 else ""),
                    "after": replacement_text[:200] + ("...(truncated)" if len(replacement_text) > 200 else ""),
                }
            )
            new_content = new_content[: match.start()] + replacement_text + new_content[match.end() :]

        if not dry_run:
            target.write_text(new_content, encoding="utf-8")

        replacements_summary.reverse()
        return json.dumps(
            {
                "success": True,
                "file_path": str(target),
                "replaced_count": len(selected_matches),
                "dry_run": dry_run,
                "replacements": replacements_summary,
                "message": (
                    f"{len(selected_matches)}개 매칭을 미리보기로 치환했습니다."
                    if dry_run
                    else f"{len(selected_matches)}개 매칭을 치환하고 파일을 저장했습니다."
                ),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error("[Tool] replace_source_in_file 예외: %s", e)
        return json.dumps(
            {
                "success": False,
                "message": f"소스 치환 실패: {e}",
                "error_detail": str(e),
            },
            ensure_ascii=False,
        )


def register_source_code_tools(mcp: "FastMCP") -> None:
    """파일 소스 검색/치환 도구를 FastMCP 서버에 등록합니다."""
    mcp.tool()(find_source_in_file)
    mcp.tool()(replace_source_in_file)
    logger.info("소스 코드 도구 등록 완료: find_source_in_file, replace_source_in_file")
