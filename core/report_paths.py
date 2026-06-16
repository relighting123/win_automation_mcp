"""업무 보고서(일일/주간) 저장 경로 설정."""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from core.llm_config import load_app_config

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _expand(path_str: str) -> Path:
    return Path(os.path.expandvars(path_str)).expanduser().resolve()


def get_report_settings(config_path: Optional[str] = None) -> dict:
    config = load_app_config(config_path)
    reports = config.get("reports", {}) if isinstance(config, dict) else {}
    if not isinstance(reports, dict):
        reports = {}

    default_daily = _PROJECT_ROOT / "reports" / "daily"
    default_weekly = _PROJECT_ROOT / "reports" / "weekly"
    daily_dir = reports.get("daily_dir") or os.getenv("CHATRTD_DAILY_REPORT_DIR") or str(default_daily)
    weekly_dir = reports.get("weekly_dir") or os.getenv("CHATRTD_WEEKLY_REPORT_DIR") or str(default_weekly)
    config_file = reports.get("config_file") or os.getenv(
        "CHATRTD_DAILY_REPORT_CONFIG",
        "skills/daily_work_summary/report_config.yaml",
    )

    return {
        "daily_dir": _expand(str(daily_dir)),
        "weekly_dir": _expand(str(weekly_dir)),
        "config_file": str(config_file),
    }


def daily_report_path(report_date: Optional[date] = None, config_path: Optional[str] = None) -> Path:
    settings = get_report_settings(config_path)
    day = report_date or date.today()
    return settings["daily_dir"] / f"{day.isoformat()}.md"


def weekly_report_path(start: date, end: date, config_path: Optional[str] = None) -> Path:
    settings = get_report_settings(config_path)
    return settings["weekly_dir"] / f"weekly_{start.isoformat()}_{end.isoformat()}.md"


def parse_report_date(value: Optional[str]) -> date:
    if not value or not str(value).strip():
        return date.today()
    return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
