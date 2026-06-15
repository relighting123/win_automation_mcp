"""
클립보드·JSON 데이터 분석 도구.

표 형태 데이터를 DataFrame 요약으로 변환하고 chatRTD / automation graph 분석에 사용합니다.
"""

from __future__ import annotations

import json
import logging
from io import StringIO
from typing import Any, Dict, List, Optional, Union

from core.dataset_cache import load_dataset, save_dataset

logger = logging.getLogger(__name__)

JsonInput = Union[Dict[str, Any], List[Any], str, None]


def _read_clipboard_text() -> str:
    """시스템 클립보드에서 텍스트를 읽습니다."""
    try:
        import pyperclip

        text = pyperclip.paste()
        if isinstance(text, str):
            return text
    except Exception as exc:  # pragma: no cover - 환경 의존
        logger.debug("pyperclip 클립보드 읽기 실패: %s", exc)

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
            if df.shape[1] >= 2:
                return df, sep
        except Exception:
            continue

    lines = [line for line in cleaned.split("\n") if line.strip()]
    if header and len(lines) >= 2:
        col_name = lines[0].strip() or "value"
        rows = [{"value": line.strip()} for line in lines[1:]]
        if rows:
            fallback_df = pd.DataFrame(rows).rename(columns={"value": col_name})
            return fallback_df, "line_fallback"

    fallback_df = pd.DataFrame({"text": lines})
    return fallback_df, "line_fallback"


def _resolve_json_payload(
    json_data: JsonInput = None,
    json_text: Optional[str] = None,
) -> Any:
    """MCP 인자에서 JSON payload를 파싱합니다."""
    if json_text not in (None, ""):
        return json.loads(str(json_text))
    if isinstance(json_data, str):
        text = json_data.strip()
        if not text:
            raise ValueError("json_data가 비어 있습니다.")
        return json.loads(text)
    if json_data is None:
        raise ValueError("json_data 또는 json_text 중 하나는 필요합니다.")
    return json_data


def _extract_by_records_path(payload: Any, records_path: Optional[str]) -> Any:
    """점(.) 경로로 중첩 JSON에서 표 데이터 노드를 추출합니다."""
    if not records_path:
        return payload
    current = payload
    for part in records_path.strip().split("."):
        key = part.strip()
        if not key:
            continue
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"records_path '{records_path}' 에서 '{key}' 를 찾지 못했습니다.")
        current = current[key]
    return current


def _parse_dataframe_from_json(payload: Any):
    """JSON payload를 DataFrame으로 변환합니다."""
    import pandas as pd

    if isinstance(payload, list):
        if not payload:
            return pd.DataFrame(), "json_records"
        if all(isinstance(item, dict) for item in payload):
            return pd.DataFrame(payload), "json_records"
        return pd.DataFrame({"value": payload}), "json_list"

    if isinstance(payload, dict):
        if "records" in payload and isinstance(payload["records"], list):
            return pd.DataFrame(payload["records"]), "json.records"
        columns = payload.get("columns")
        data = payload.get("data")
        if isinstance(columns, list) and isinstance(data, list):
            return pd.DataFrame(data, columns=columns), "json.columns_data"
        if "rows" in payload and isinstance(payload["rows"], list):
            return pd.DataFrame(payload["rows"]), "json.rows"
        if "items" in payload and isinstance(payload["items"], list):
            return pd.DataFrame(payload["items"]), "json.items"
        return pd.DataFrame([payload]), "json_object"

    raise ValueError("지원하지 않는 JSON 구조입니다. records 배열 또는 columns/data 형식을 사용하세요.")


def _dataframe_summary_result(
    df,
    *,
    source: str,
    delimiter_used: str,
    max_preview_rows: int,
    raw_preview: str = "",
) -> Dict[str, Any]:
    """DataFrame을 automation graph / chatRTD가 소비하는 공통 JSON 형식으로 변환합니다."""
    import pandas as pd

    preview_rows = max(1, min(int(max_preview_rows), 100))
    preview_df = df.head(preview_rows)
    preview_records = preview_df.where(pd.notnull(preview_df), None).to_dict(orient="records")

    return {
        "success": True,
        "message": f"{source} 데이터를 DataFrame으로 변환했습니다.",
        "source": source,
        "delimiter_used": delimiter_used,
        "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
        "columns": [str(col) for col in df.columns.tolist()],
        "dtypes": {str(col): str(dtype) for col, dtype in df.dtypes.items()},
        "preview_records": preview_records,
        "preview_markdown": preview_df.to_markdown(index=False),
        "raw_preview": raw_preview[:2000],
    }


def _error_result(message: str, **extra: Any) -> str:
    return json.dumps({"success": False, "message": message, **extra}, ensure_ascii=False)


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
            import pandas as pd  # noqa: F401
        except ImportError:
            return _error_result("pandas가 설치되어 있지 않아 DataFrame 변환을 수행할 수 없습니다.")

        raw_text = _read_clipboard_text()
        if not raw_text.strip():
            return _error_result(
                "클립보드에 텍스트 데이터가 없습니다. 먼저 Ctrl+C로 데이터를 복사하세요."
            )

        df, used_delimiter = _parse_dataframe_from_text(raw_text, delimiter=delimiter, header=header)
        if df.empty:
            return _error_result(
                "클립보드 텍스트를 표 형태로 파싱하지 못했습니다.",
                raw_preview=raw_text[:2000],
            )

        result = _dataframe_summary_result(
            df,
            source="clipboard",
            delimiter_used=used_delimiter,
            max_preview_rows=max_preview_rows,
            raw_preview=raw_text,
        )
        save_dataset(result, source="clipboard")
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.exception("read_clipboard_as_dataframe 실패")
        return _error_result(f"클립보드 DataFrame 변환 중 오류가 발생했습니다: {exc}")


async def load_json_as_dataframe(
    json_data: JsonInput = None,
    json_text: Optional[str] = None,
    records_path: Optional[str] = None,
    max_preview_rows: int = 20,
) -> str:
    """
    JSON 데이터를 DataFrame으로 변환해 요약 정보를 반환하고 chatRTD 캐시에 저장합니다.

    지원 형식 예시:
      - [{"colA": 1, "colB": 2}, ...]
      - {"records": [...]}
      - {"columns": ["A", "B"], "data": [[1, 2], [3, 4]]}
      - 중첩 JSON은 records_path로 지정 (예: "result.items")

    Args:
        json_data: JSON 객체/배열 또는 JSON 문자열
        json_text: JSON 문자열 (긴 payload용 별칭)
        records_path: 중첩 경로 (점 표기)
        max_preview_rows: 미리보기 최대 행 수
    """
    try:
        try:
            import pandas as pd  # noqa: F401
        except ImportError:
            return _error_result("pandas가 설치되어 있지 않아 DataFrame 변환을 수행할 수 없습니다.")

        payload = _resolve_json_payload(json_data=json_data, json_text=json_text)
        target = _extract_by_records_path(payload, records_path)
        df, used_format = _parse_dataframe_from_json(target)
        if df.empty:
            return _error_result("JSON에서 표 데이터를 추출했지만 행이 없습니다.")

        preview_text = json.dumps(payload, ensure_ascii=False)[:2000]
        result = _dataframe_summary_result(
            df,
            source="json",
            delimiter_used=used_format,
            max_preview_rows=max_preview_rows,
            raw_preview=preview_text,
        )
        if records_path:
            result["records_path"] = records_path
        save_dataset(result, source="json")
        return json.dumps(result, ensure_ascii=False, default=str)
    except json.JSONDecodeError as exc:
        return _error_result(f"JSON 파싱 실패: {exc}")
    except ValueError as exc:
        return _error_result(str(exc))
    except Exception as exc:
        logger.exception("load_json_as_dataframe 실패")
        return _error_result(f"JSON DataFrame 변환 중 오류가 발생했습니다: {exc}")


async def get_cached_dataset_summary() -> str:
    """
    마지막으로 load_json_as_dataframe / read_clipboard_as_dataframe 이 저장한
    데이터셋 요약을 반환합니다. chatRTD 후속 대화·분석에 사용합니다.
    """
    cached = load_dataset()
    if not cached:
        return _error_result("저장된 데이터셋이 없습니다. load_json_as_dataframe 을 먼저 호출하세요.")
    dataset = cached.get("dataset")
    if not isinstance(dataset, dict) or dataset.get("success") is not True:
        return _error_result("캐시에 유효한 데이터셋이 없습니다.", cache=cached)
    return json.dumps(
        {
            "success": True,
            "message": "캐시된 데이터셋 요약을 반환했습니다.",
            "saved_at": cached.get("saved_at"),
            "source": cached.get("source"),
            **dataset,
        },
        ensure_ascii=False,
        default=str,
    )


DATASET_SUMMARY_TOOLS = (
    "read_clipboard_as_dataframe",
    "load_json_as_dataframe",
    "get_cached_dataset_summary",
)


def register_data_analysis_tools(mcp: Any) -> None:
    """데이터 분석 보조 도구 등록."""
    mcp.tool()(read_clipboard_as_dataframe)
    mcp.tool()(load_json_as_dataframe)
    mcp.tool()(get_cached_dataset_summary)
    logger.info(
        "데이터 분석 도구 등록 완료: read_clipboard_as_dataframe, "
        "load_json_as_dataframe, get_cached_dataset_summary"
    )
