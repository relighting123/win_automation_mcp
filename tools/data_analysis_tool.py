"""
클립보드 데이터 분석 도구.

Ctrl+C로 복사된 텍스트를 표 형태로 파싱하고 DataFrame 요약 정보를 반환합니다.
"""

from __future__ import annotations

import json
import logging
from io import StringIO
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _read_clipboard_text() -> str:
    """시스템 클립보드에서 텍스트를 읽습니다."""
    # 1) pyperclip 우선 사용
    try:
        import pyperclip

        text = pyperclip.paste()
        if isinstance(text, str):
            return text
    except Exception as exc:  # pragma: no cover - 환경 의존
        logger.debug("pyperclip 클립보드 읽기 실패: %s", exc)

    # 2) tkinter fallback
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            text = root.clipboard_get()
            return text if isinstance(text, str) else str(text)
        finally:
            root.destroy()
    except Exception as exc:  # pragma: no cover - 환경 의존
        logger.debug("tkinter 클립보드 읽기 실패: %s", exc)

    return ""


def _parse_dataframe_from_text(raw_text: str, delimiter: Optional[str], header: bool):
    """복사된 텍스트를 DataFrame으로 파싱합니다."""
    import pandas as pd

    cleaned = (raw_text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return pd.DataFrame(), "empty"

    header_row: Optional[int] = 0 if header else None
    candidates = [delimiter] if delimiter else ["\t", ",", "|", ";", r"\s{2,}"]

    for sep in candidates:
        if not sep:
            continue
        try:
            df = pd.read_csv(StringIO(cleaned), sep=sep, engine="python", header=header_row)
            # 2개 이상 컬럼이면 표 형태로 판단
            if df.shape[1] >= 2:
                return df, sep
        except Exception:
            continue

    # 단일 컬럼 fallback
    lines = [line for line in cleaned.split("\n") if line.strip()]
    if header and len(lines) >= 2:
        col_name = lines[0].strip() or "value"
        rows = [{"value": line.strip()} for line in lines[1:]]
        if rows:
            fallback_df = pd.DataFrame(rows).rename(columns={"value": col_name})
            return fallback_df, "line_fallback"

    fallback_df = pd.DataFrame({"text": lines})
    return fallback_df, "line_fallback"


async def read_clipboard_as_dataframe(
    delimiter: Optional[str] = None,
    header: bool = True,
    max_preview_rows: int = 20,
) -> str:
    """
    Ctrl+C로 복사된 텍스트를 DataFrame으로 파싱해 요약 정보를 반환합니다.

    Args:
        delimiter: 컬럼 구분자 (None이면 자동 추론)
        header: 첫 행을 헤더로 사용할지 여부
        max_preview_rows: 미리보기로 포함할 최대 행 수
    """
    try:
        try:
            import pandas as pd
        except ImportError:
            return json.dumps(
                {
                    "success": False,
                    "message": "pandas가 설치되어 있지 않아 DataFrame 변환을 수행할 수 없습니다.",
                },
                ensure_ascii=False,
            )

        raw_text = _read_clipboard_text()
        if not raw_text.strip():
            return json.dumps(
                {
                    "success": False,
                    "message": "클립보드에 텍스트 데이터가 없습니다. 먼저 Ctrl+C로 데이터를 복사하세요.",
                },
                ensure_ascii=False,
            )

        df, used_delimiter = _parse_dataframe_from_text(raw_text, delimiter=delimiter, header=header)
        if df.empty:
            return json.dumps(
                {
                    "success": False,
                    "message": "클립보드 텍스트를 표 형태로 파싱하지 못했습니다.",
                    "raw_preview": raw_text[:2000],
                },
                ensure_ascii=False,
            )

        preview_rows = max(1, min(int(max_preview_rows), 100))
        preview_df = df.head(preview_rows)
        # NaN -> None 변환하여 JSON 직렬화 안정성 확보
        preview_records = preview_df.where(pd.notnull(preview_df), None).to_dict(orient="records")

        result = {
            "success": True,
            "message": "클립보드 데이터를 DataFrame으로 변환했습니다.",
            "delimiter_used": used_delimiter,
            "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
            "columns": [str(col) for col in df.columns.tolist()],
            "dtypes": {str(col): str(dtype) for col, dtype in df.dtypes.items()},
            "preview_records": preview_records,
            "preview_markdown": preview_df.to_markdown(index=False),
            "raw_preview": raw_text[:2000],
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.exception("read_clipboard_as_dataframe 실패")
        return json.dumps(
            {
                "success": False,
                "message": f"클립보드 DataFrame 변환 중 오류가 발생했습니다: {exc}",
            },
            ensure_ascii=False,
        )


def register_data_analysis_tools(mcp: Any) -> None:
    """데이터 분석 보조 도구 등록."""
    mcp.tool()(read_clipboard_as_dataframe)
    logger.info("데이터 분석 도구 등록 완료: read_clipboard_as_dataframe")
