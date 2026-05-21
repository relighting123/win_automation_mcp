"""
LLM 프롬프트/응답 로깅 유틸.

목적
----
LangChain/OpenAI 등 다양한 형태의 LLM 호출 입력(messages, prompt template, dict 등)을
사람이 읽기 좋은 형태로 표준화하여 logger `llm.prompt` 에 남깁니다.

활성/비활성 제어
----------------
- 환경 변수 `LLM_PROMPT_LOG` 가 "0"/"false"/"off"/"no" 이면 비활성화.
- 그 외에는 기본 활성. (자동화 디버깅 편의를 위해 기본 ON)

출력 위치
---------
- 기본 stdout (루트 logger 설정을 따름).
- 환경 변수 `LLM_PROMPT_LOG_FILE` 가 지정되면 해당 경로에 파일 핸들러를 한 번만 부착.

로그 길이
---------
- 기본적으로 system / user 메시지 전체를 출력합니다.
- 응답 길이를 줄이고 싶다면 `LLM_PROMPT_LOG_MAX_CHARS` 로 잘라낼 수 있습니다(기본: 잘라내지 않음).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

_LOGGER_NAME = "llm.prompt"
_logger = logging.getLogger(_LOGGER_NAME)
_file_handler_attached = False
_stream_handler_attached = False


def _ensure_stream_handler() -> None:
    """루트 logger 가 아직 설정되지 않았어도 콘솔 출력이 가능하도록 보장한다."""
    global _stream_handler_attached
    if _stream_handler_attached:
        return
    # 이미 어디선가 핸들러가 부착되어 있으면 중복 출력 방지를 위해 건너뜀.
    root_logger = logging.getLogger()
    if _logger.handlers or root_logger.handlers:
        _stream_handler_attached = True
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    _logger.addHandler(handler)
    # 루트로의 전파는 끄지 않는다. 사용자가 나중에 basicConfig 를 호출해도 동작하도록.
    if _logger.level == logging.NOTSET:
        _logger.setLevel(logging.INFO)
    _stream_handler_attached = True


def _is_enabled() -> bool:
    raw = os.getenv("LLM_PROMPT_LOG")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "off", "no", ""}


def _max_chars() -> Optional[int]:
    raw = os.getenv("LLM_PROMPT_LOG_MAX_CHARS")
    if not raw:
        return None
    try:
        value = int(raw)
        return value if value > 0 else None
    except ValueError:
        return None


def _ensure_file_handler() -> None:
    global _file_handler_attached
    if _file_handler_attached:
        return
    target = os.getenv("LLM_PROMPT_LOG_FILE")
    if not target:
        return
    try:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        _logger.addHandler(handler)
        _logger.setLevel(logging.INFO)
        _file_handler_attached = True
    except Exception as exc:  # noqa: BLE001
        # 파일 핸들러 부착 실패는 치명적이지 않으므로 경고만 출력.
        logging.getLogger(__name__).warning("LLM 프롬프트 로그 파일 부착 실패: %s", exc)


def _truncate(text: str) -> str:
    limit = _max_chars()
    if limit is None or len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def _stringify_part(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


def _format_message(role: str, content: Any) -> str:
    body = _stringify_part(content)
    return f"[{role}]\n{body}"


def _normalize_messages(prompt: Any) -> list[tuple[str, Any]]:
    """다양한 입력 형태를 (role, content) 튜플 리스트로 정규화."""
    if prompt is None:
        return []

    if isinstance(prompt, str):
        return [("user", prompt)]

    if isinstance(prompt, dict):
        # ChatPromptTemplate format dict 등
        return [("input", prompt)]

    if isinstance(prompt, Sequence) and not isinstance(prompt, (bytes, bytearray)):
        normalized: list[tuple[str, Any]] = []
        for item in prompt:
            if isinstance(item, tuple) and len(item) == 2:
                role, content = item
                normalized.append((str(role), content))
            elif isinstance(item, dict):
                role = item.get("role") or item.get("type") or "message"
                content = item.get("content", item)
                normalized.append((str(role), content))
            else:
                # LangChain BaseMessage 등
                role = getattr(item, "type", None) or item.__class__.__name__
                content = getattr(item, "content", str(item))
                normalized.append((str(role), content))
        return normalized

    # 기타 객체: 그대로 표시
    return [("prompt", prompt)]


def log_llm_request(
    stage: str,
    prompt: Any,
    *,
    extra: Optional[dict] = None,
) -> None:
    """LLM 요청 프롬프트를 사람이 읽기 좋은 형태로 로그에 남긴다.

    Parameters
    ----------
    stage: 호출 단계(예: "plan", "extract", "report").
    prompt: 메시지 리스트, 문자열, dict 등 임의 형태.
    extra: 함께 남길 메타데이터(스킬 ID 등).
    """
    if not _is_enabled():
        return
    _ensure_stream_handler()
    _ensure_file_handler()

    messages = _normalize_messages(prompt)
    formatted = "\n\n".join(_format_message(role, content) for role, content in messages)
    formatted = _truncate(formatted)

    header = f"=== [LLM REQUEST: {stage}] ==="
    if extra:
        try:
            header += f" {json.dumps(extra, ensure_ascii=False)}"
        except Exception:  # noqa: BLE001
            header += f" {extra!r}"

    _logger.info("%s\n%s\n=== [END LLM REQUEST: %s] ===", header, formatted, stage)


def log_llm_response(stage: str, response: Any) -> None:
    """LLM 응답을 로그에 남긴다."""
    if not _is_enabled():
        return
    _ensure_stream_handler()
    _ensure_file_handler()

    # LangChain AIMessage 등은 .content 사용
    if hasattr(response, "content") and not isinstance(response, (str, dict)):
        body = _stringify_part(getattr(response, "content"))
    elif hasattr(response, "model_dump"):
        try:
            body = json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            body = _stringify_part(response)
    else:
        body = _stringify_part(response)

    body = _truncate(body)
    _logger.info("=== [LLM RESPONSE: %s] ===\n%s\n=== [END LLM RESPONSE: %s] ===", stage, body, stage)


def log_llm_exchange(
    stage: str,
    prompt: Any,
    response: Any,
    *,
    extra: Optional[dict] = None,
) -> None:
    """요청/응답을 한 번에 기록하는 헬퍼."""
    log_llm_request(stage, prompt, extra=extra)
    log_llm_response(stage, response)


__all__ = [
    "log_llm_request",
    "log_llm_response",
    "log_llm_exchange",
]
