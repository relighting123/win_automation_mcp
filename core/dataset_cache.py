"""클립보드 DataFrame JSON 저장."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

CACHE_DIR = Path.home() / ".chatRTD"
DEFAULT_CLIPBOARD_JSON = CACHE_DIR / "clipboard_data.json"


def save_dataframe_json(
    records: list[Dict[str, Any]],
    *,
    columns: Optional[list[str]] = None,
    path: Optional[str] = None,
) -> str:
    """DataFrame records를 JSON 파일로 저장하고 경로를 반환합니다."""
    target = Path(path) if path else DEFAULT_CLIPBOARD_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": time.time(),
        "columns": columns or [],
        "record_count": len(records),
        "records": records,
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(target)
