"""
Windows 작업 스케줄러(schtasks) 연동.

chatRTD에서 일일/주간 보고서 등 예약 작업을 등록합니다.
"""

from __future__ import annotations

import csv
import io
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TASK_PREFIX = "chatRTD-"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_PRESETS = {
    "daily": {
        "task_name": f"{TASK_PREFIX}DailySummary",
        "script": "scripts/run_daily_summary.py",
        "description": "일일 업무 보고서 (daily_work_summary)",
    },
    "weekly": {
        "task_name": f"{TASK_PREFIX}WeeklyReport",
        "script": "scripts/run_weekly_report.py",
        "description": "주간 업무 보고서 (weekly_report)",
    },
}


@dataclass
class ScheduledTaskInfo:
    name: str
    status: str
    next_run: str
    schedule: str


def is_windows_scheduler_available() -> bool:
    return sys.platform == "win32"


def _build_tr_command(script_relative: str) -> str:
    script = (_PROJECT_ROOT / script_relative).resolve()
    if not script.exists():
        raise FileNotFoundError(f"스크립트를 찾을 수 없습니다: {script}")
    root = str(_PROJECT_ROOT.resolve())
    python_exe = str(Path(sys.executable).resolve())
    return f'cmd /c cd /d "{root}" && "{python_exe}" "{script}"'


def _run_schtasks(args: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed


def list_chatrtd_tasks() -> list[ScheduledTaskInfo]:
    if not is_windows_scheduler_available():
        return []

    completed = _run_schtasks(["/Query", "/FO", "CSV", "/NH"])
    if completed.returncode != 0:
        logger.warning("schtasks query 실패: %s", completed.stderr)
        return []

    tasks: list[ScheduledTaskInfo] = []
    reader = csv.reader(io.StringIO(completed.stdout))
    for row in reader:
        if len(row) < 3:
            continue
        name = row[0].strip().strip('"')
        if not name.startswith(TASK_PREFIX):
            continue
        next_run = row[1].strip().strip('"') if len(row) > 1 else ""
        status = row[2].strip().strip('"') if len(row) > 2 else ""
        schedule = row[3].strip().strip('"') if len(row) > 3 else ""
        tasks.append(
            ScheduledTaskInfo(
                name=name,
                next_run=next_run,
                status=status,
                schedule=schedule,
            )
        )
    return tasks


def register_preset_task(
    preset: str,
    *,
    time_hhmm: str,
    weekday: Optional[str] = None,
) -> dict:
    """
  preset: daily | weekly
  time_hhmm: HH:MM (24h)
  weekday: weekly일 때 MON..SUN (기본 FRI)
    """
    if not is_windows_scheduler_available():
        return {
            "success": False,
            "message": "Windows 작업 스케줄러는 Windows에서만 지원됩니다.",
        }

    preset_key = preset.strip().lower()
    meta = _PRESETS.get(preset_key)
    if meta is None:
        return {
            "success": False,
            "message": f"지원하지 않는 preset: {preset} (daily|weekly)",
        }

    if not _validate_time_hhmm(time_hhmm):
        return {"success": False, "message": "time은 HH:MM 형식이어야 합니다. 예: 18:00"}

    try:
        tr_command = _build_tr_command(meta["script"])
    except FileNotFoundError as exc:
        return {"success": False, "message": str(exc)}

    args = [
        "/Create",
        "/TN",
        meta["task_name"],
        "/TR",
        tr_command,
        "/ST",
        time_hhmm,
        "/F",
    ]

    if preset_key == "daily":
        args.extend(["/SC", "DAILY"])
    else:
        day = (weekday or "FRI").strip().upper()
        if day not in {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}:
            return {"success": False, "message": f"잘못된 요일: {weekday}"}
        args.extend(["/SC", "WEEKLY", "/D", day])

    completed = _run_schtasks(args)
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "schtasks 실패").strip()
        return {"success": False, "message": message}

    return {
        "success": True,
        "task_name": meta["task_name"],
        "preset": preset_key,
        "time": time_hhmm,
        "weekday": weekday if preset_key == "weekly" else None,
        "description": meta["description"],
        "message": "작업 스케줄러에 등록되었습니다.",
    }


def remove_task(task_name: str) -> dict:
    if not is_windows_scheduler_available():
        return {"success": False, "message": "Windows에서만 지원됩니다."}

    name = task_name.strip()
    if not name.startswith(TASK_PREFIX):
        name = f"{TASK_PREFIX}{name}"

    completed = _run_schtasks(["/Delete", "/TN", name, "/F"])
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "삭제 실패").strip()
        return {"success": False, "message": message}
    return {"success": True, "task_name": name, "message": "작업이 삭제되었습니다."}


def run_preset_now(preset: str) -> dict:
    preset_key = preset.strip().lower()
    meta = _PRESETS.get(preset_key)
    if meta is None:
        return {"success": False, "message": f"지원하지 않는 preset: {preset}"}

    script = (_PROJECT_ROOT / meta["script"]).resolve()
    if not script.exists():
        return {"success": False, "message": f"스크립트 없음: {script}"}

    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout or completed.stderr or "").strip()
    return {
        "success": completed.returncode == 0,
        "preset": preset_key,
        "exit_code": completed.returncode,
        "output": output,
        "message": "즉시 실행 완료" if completed.returncode == 0 else "실행 실패",
    }


def _validate_time_hhmm(value: str) -> bool:
    parts = value.strip().split(":")
    if len(parts) != 2:
        return False
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59
