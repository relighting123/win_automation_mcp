#!/usr/bin/env python3
"""주간 업무 보고서 예약 실행 엔트리포인트 (Windows 작업 스케줄러용)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from tools.daily_report_tool import build_weekly_report


async def _main(start_date: str | None, end_date: str | None) -> int:
    raw = await build_weekly_report(start_date=start_date, end_date=end_date)
    payload = json.loads(raw)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("success") else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="chatRTD 주간 업무 보고서 생성")
    parser.add_argument("--start", default=None, help="YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.start, args.end)))


if __name__ == "__main__":
    main()
