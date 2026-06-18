"""MCP tool 결과 파싱 공통 유틸."""

from __future__ import annotations

import json
from typing import Any, Dict


def extract_mcp_text_content(raw_result: dict[str, Any]) -> str:
    blocks = raw_result.get("content")
    if not isinstance(blocks, list):
        return ""

    texts = [
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(text for text in texts if text).strip()


def normalize_mcp_tool_result(raw_result: Any) -> Dict[str, Any]:
    """tool 반환값(JSON 문자열/딕셔너리/MCP content)을 공통 딕셔너리 형태로 통일합니다."""
    if isinstance(raw_result, dict):
        if "error" in raw_result and "content" not in raw_result:
            return {"success": False, "message": str(raw_result.get("error"))}

        if raw_result.get("isError") is True:
            message = extract_mcp_text_content(raw_result) or str(raw_result)
            return {"success": False, "message": message}

        content_text = extract_mcp_text_content(raw_result)
        if content_text:
            if content_text.startswith("Error:"):
                return {"success": False, "message": content_text}
            try:
                parsed = json.loads(content_text)
                if isinstance(parsed, dict):
                    if parsed.get("success") is False:
                        return parsed
                    return parsed
                return {"success": True, "result": parsed}
            except json.JSONDecodeError:
                return {"success": True, "text": content_text}

        if raw_result.get("success") is False:
            return raw_result
        return raw_result

    if isinstance(raw_result, str):
        try:
            parsed = json.loads(raw_result)
            return parsed if isinstance(parsed, dict) else {"success": True, "result": parsed}
        except json.JSONDecodeError:
            return {"success": True, "result": raw_result}

    if hasattr(raw_result, "to_dict") and callable(raw_result.to_dict):
        return raw_result.to_dict()

    return {"success": True, "result": raw_result}
