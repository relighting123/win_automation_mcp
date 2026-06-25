"""
일일/주간 업무 보고서 생성 도구.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

import yaml

from core.report_paths import (
    daily_report_path,
    get_report_settings,
    parse_report_date,
    weekly_report_path,
)
from tools.report_file_tool import list_report_files, read_text_file, write_text_file

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _PROJECT_ROOT / "skills" / "daily_work_summary" / "report_config.yaml"


def _load_report_config(config_path: Optional[str] = None) -> dict[str, Any]:
    settings = get_report_settings()
    raw_path = config_path or settings["config_file"]
    path = Path(raw_path)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path

    if not path.exists():
        example = path.with_name("report_config.yaml.example")
        if example.exists():
            path = example
        else:
            return {"title": "일일 업무 정리", "urls": [], "oracle_queries": [], "notes": []}

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


async def _run_oracle_query(entry: dict[str, Any]) -> str:
    from tools.oracle_db_tool import query_oracle_db

    raw = await query_oracle_db(
        sql=str(entry.get("sql", "")),
        db=entry.get("db"),
        max_rows=int(entry.get("max_rows", 50)),
    )
    try:
        payload = json.loads(raw)
        if not payload.get("success", True):
            return f"[DB 오류] {payload.get('message', raw)}"
        rows = payload.get("rows") or payload.get("data") or payload
        return json.dumps(rows, ensure_ascii=False, indent=2, default=str)
    except json.JSONDecodeError:
        return raw


async def build_daily_work_report(
    report_date: Optional[str] = None,
    config_path: Optional[str] = None,
) -> str:
    """
    report_config.yaml + skill.md에 정의된 URL/DB 항목을 수집해 일일 MD 보고서를 저장합니다.

    Args:
        report_date: YYYY-MM-DD (기본 오늘)
        config_path: report_config.yaml 경로 (기본 skills/daily_work_summary/report_config.yaml)
    """
    try:
        day = parse_report_date(report_date)
        config = _load_report_config(config_path)
        title = str(config.get("title") or "일일 업무 정리")
        output_path = daily_report_path(day)

        lines = [
            f"# {title}",
            "",
            f"- 작성일: {day.isoformat()}",
            f"- 생성: chatRTD daily_work_summary",
            "",
        ]

        urls = config.get("urls") or []
        if urls:
            lines.append("## 참고 URL")
            lines.append("")
            for item in urls:
                if isinstance(item, str):
                    name, url = "페이지", item
                elif isinstance(item, dict):
                    name = str(item.get("name") or item.get("title") or "페이지")
                    url = str(item.get("url") or "").strip()
                else:
                    continue
                if not url:
                    continue
                lines.append(f"- **{name}**: {url}")
            lines.append("")

        queries = config.get("oracle_queries") or []
        if queries:
            lines.append("## DB 분석")
            lines.append("")
            for entry in queries:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name") or "쿼리")
                lines.append(f"### {name}")
                result_text = await _run_oracle_query(entry)
                lines.append("")
                lines.append("```json")
                lines.append(result_text[:8000])
                lines.append("```")
                lines.append("")

        notes = config.get("notes") or []
        if notes:
            lines.append("## 메모")
            lines.append("")
            for note in notes:
                lines.append(f"- {note}")
            lines.append("")

        manual_sections = config.get("sections") or []
        for section in manual_sections:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("title") or section.get("name") or "항목")
            body = str(section.get("content") or section.get("text") or "").strip()
            lines.append(f"## {heading}")
            lines.append("")
            if body:
                lines.append(body)
                lines.append("")

        content = "\n".join(lines).strip() + "\n"
        write_result = json.loads(
            await write_text_file(str(output_path), content, append=False)
        )
        if not write_result.get("success"):
            return json.dumps(
                {"success": False, "message": write_result.get("message"), "date": day.isoformat()},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "success": True,
                "date": day.isoformat(),
                "file_path": str(output_path),
                "message": "일일 업무 보고서 저장 완료",
                "sections": {
                    "urls": len(urls),
                    "oracle_queries": len(queries),
                },
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("build_daily_work_report 실패")
        return json.dumps({"success": False, "message": str(exc)}, ensure_ascii=False)


async def build_weekly_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    일일 MD 보고서를 모아 주간 보고서를 생성합니다.

    Args:
        start_date: YYYY-MM-DD (기본: 오늘 기준 7일 전)
        end_date: YYYY-MM-DD (기본: 오늘)
    """
    try:
        end = parse_report_date(end_date) if end_date else date.today()
        start = parse_report_date(start_date) if start_date else (end - timedelta(days=6))

        listing = json.loads(
            await list_report_files(
                start_date=start.isoformat(),
                end_date=end.isoformat(),
            )
        )
        if not listing.get("success"):
            return json.dumps(listing, ensure_ascii=False)

        files = listing.get("files") or []
        if not files:
            return json.dumps(
                {
                    "success": False,
                    "message": f"기간 내 일일 보고서가 없습니다: {start} ~ {end}",
                },
                ensure_ascii=False,
            )

        lines = [
            "# 주간 업무 보고",
            "",
            f"- 기간: {start.isoformat()} ~ {end.isoformat()}",
            f"- 일일 보고서 {len(files)}건",
            "",
        ]

        for entry in files:
            file_path = entry["file_path"]
            read_payload = json.loads(await read_text_file(file_path, max_chars=100_000))
            if not read_payload.get("success"):
                lines.append(f"## {entry.get('date') or entry.get('name')} (읽기 실패)")
                lines.append("")
                lines.append(read_payload.get("message", "unknown error"))
                lines.append("")
                continue

            lines.append(f"## {entry.get('date') or entry.get('name')}")
            lines.append("")
            lines.append(read_payload.get("text", ""))
            lines.append("")
            lines.append("---")
            lines.append("")

        output_path = weekly_report_path(start, end)
        content = "\n".join(lines).strip() + "\n"
        write_payload = json.loads(await write_text_file(str(output_path), content, append=False))
        if not write_payload.get("success"):
            return json.dumps(write_payload, ensure_ascii=False)

        return json.dumps(
            {
                "success": True,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "file_path": str(output_path),
                "source_files": [f["file_path"] for f in files],
                "message": "주간 보고서 저장 완료",
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("build_weekly_report 실패")
        return json.dumps({"success": False, "message": str(exc)}, ensure_ascii=False)


def register_daily_report_tools(mcp: "FastMCP") -> None:
    mcp.tool()(build_daily_work_report)
    mcp.tool()(build_weekly_report)
    logger.info("일일/주간 보고서 도구 등록 완료")
