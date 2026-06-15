"""chatRTD / automation graph용 최근 데이터셋 캐시."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

CACHE_DIR = Path.home() / ".chatRTD"
CACHE_FILE = CACHE_DIR / "last_dataset.json"


def save_dataset(payload: Dict[str, Any], *, source: str = "unknown") -> None:
    """성공한 데이터셋 요약을 로컬 캐시에 저장합니다."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "saved_at": time.time(),
        "source": source,
        "dataset": payload,
    }
    CACHE_FILE.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def load_dataset() -> Optional[Dict[str, Any]]:
    """마지막으로 저장된 데이터셋 캐시를 반환합니다."""
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None
