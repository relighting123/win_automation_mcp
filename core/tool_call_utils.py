"""LLM 텍스트 응답에 포함된 tool_call 블록 파싱 유틸."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ParsedToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


_TOOL_CALL_BLOCK_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL | re.IGNORECASE,
)


def normalize_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _parse_tool_call_payload(payload: dict[str, Any]) -> Optional[ParsedToolCall]:
    name = payload.get("name") or payload.get("tool") or payload.get("function")
    if not name:
        return None

    args = payload.get("arguments")
    if args is None:
        args = payload.get("parameters")
    if args is None and isinstance(payload.get("function"), dict):
        fn = payload["function"]
        name = fn.get("name") or name
        args = fn.get("arguments")

    return ParsedToolCall(
        id=str(payload.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
        name=str(name),
        arguments=normalize_tool_arguments(args),
    )


def parse_text_tool_calls(content: str) -> list[ParsedToolCall]:
    """모델이 본문에 출력한 <tool_call> 블록을 파싱합니다."""
    if not content:
        return []

    calls: list[ParsedToolCall] = []
    for match in _TOOL_CALL_BLOCK_RE.finditer(content):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        parsed = _parse_tool_call_payload(payload)
        if parsed is not None:
            calls.append(parsed)
    return calls


def parse_kv_args(tokens: list[str]) -> dict[str, str]:
    """`url=https://example.com` 형태 인자를 dict로 변환합니다."""
    out: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            out[key] = value
    return out
