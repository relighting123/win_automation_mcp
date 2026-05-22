"""
Dual-LLM Factory

reasoning / task 역할을 가진 두 개의 LLM 인스턴스를 만들고,
Gemma(또는 OpenAI 와 다른 호환 모델)에서도 안전하게 structured output 을 얻기 위한
어댑터를 제공합니다.

핵심 설계 포인트:
- Gemma 는 OpenAI 스타일 `tools` / function calling 을 잘 지원하지 않습니다.
  따라서 `with_structured_output(method="function_calling")` 호출이 실패하면
  `method="json_mode"` 로 자동 fallback 합니다.
- json_mode 마저 미지원인 서빙 환경을 대비해 JSON 프롬프트 + 정규식 파싱 기반의
  최종 fallback (`_JsonPromptStructuredLLM`) 을 제공합니다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Type

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage

try:
    # langchain-core 의 위치가 버전마다 다릅니다. 없으면 None 으로 폴백.
    from langchain_core.prompt_values import ChatPromptValue  # type: ignore
except Exception:  # pragma: no cover
    try:
        from langchain_core.prompts import ChatPromptValue  # type: ignore
    except Exception:
        ChatPromptValue = None  # type: ignore

from pydantic import BaseModel

from core.llm_config import get_role_llm_settings

logger = logging.getLogger(__name__)


class _JsonPromptStructuredLLM:
    """
    LLM 이 OpenAI tools/json_mode 둘 다 지원하지 않을 때 사용하는 최종 fallback.

    Pydantic 스키마를 프롬프트에 직접 주입해 JSON 만 생성하도록 유도한 뒤,
    응답 문자열에서 JSON 블록을 추출해 스키마 인스턴스로 파싱합니다.
    """

    def __init__(self, llm: ChatOpenAI, schema: Type[BaseModel]):
        self._llm = llm
        self._schema = schema

    @staticmethod
    def _schema_to_text(schema: Type[BaseModel]) -> str:
        try:
            return json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
        except Exception:
            return schema.__name__

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        if not text:
            return None
        text = text.strip()

        fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
        if fenced:
            return fenced.group(1)

        brace = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if brace:
            return brace.group(1)

        return text

    def _build_messages(self, payload: Any) -> Any:
        schema_text = self._schema_to_text(self._schema)
        guidance = (
            "Respond with a single JSON object matching this JSON Schema. "
            "Do not include any text outside the JSON.\n\n"
            f"```json\n{schema_text}\n```"
        )

        if isinstance(payload, str):
            return [
                ("system", guidance),
                ("user", payload),
            ]

        if ChatPromptValue is not None and isinstance(payload, ChatPromptValue):
            return list(payload.to_messages()) + [("system", guidance)]

        if isinstance(payload, list):
            return list(payload) + [("system", guidance)]

        return [("system", guidance), ("user", str(payload))]

    def _parse(self, response: Any) -> BaseModel:
        if isinstance(response, BaseMessage):
            text = response.content
        elif isinstance(response, str):
            text = response
        else:
            text = str(response)

        if isinstance(text, list):
            text = "".join(
                chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
                for chunk in text
            )

        json_str = self._extract_json(text or "")
        if not json_str:
            raise ValueError("LLM 응답에서 JSON 을 찾지 못했습니다.")

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 파싱 실패: {exc}") from exc

        return self._schema.model_validate(data)

    def invoke(self, payload: Any) -> BaseModel:
        messages = self._build_messages(payload)
        response = self._llm.invoke(messages)
        return self._parse(response)

    async def ainvoke(self, payload: Any) -> BaseModel:
        messages = self._build_messages(payload)
        response = await self._llm.ainvoke(messages)
        return self._parse(response)


class RoleLLM:
    """
    한 역할(reasoning/task)을 담당하는 ChatOpenAI 래퍼.

    `invoke` / `ainvoke` 는 ChatOpenAI 그대로 위임하기 때문에 기존 코드에서
    `llm.ainvoke(prompt)` 처럼 호출하는 부분과 호환됩니다.
    `with_structured_output` 만 Gemma 안전성을 위해 가로채서 fallback 을 시도합니다.
    """

    def __init__(self, chat: ChatOpenAI, *, provider: str, structured_output_method: str):
        self._chat = chat
        self.provider = (provider or "").lower()
        self.structured_output_method = structured_output_method or "function_calling"

    @property
    def chat(self) -> ChatOpenAI:
        return self._chat

    def __getattr__(self, item: str) -> Any:
        # ChatOpenAI 의 메서드 (invoke/ainvoke/bind_tools/...) 를 그대로 노출
        return getattr(self._chat, item)

    def with_structured_output(
        self,
        schema: Type[BaseModel],
        *,
        method: Optional[str] = None,
        strict: Optional[bool] = None,
    ):
        """
        provider 특성에 따라 안전한 structured output 객체를 반환합니다.

        - openai 호환: 호출자가 지정한 method 우선, 실패 시 json_mode → JSON 프롬프트 순으로 fallback.
        - gemma: function_calling 을 무시하고 json_mode → json_schema → JSON 프롬프트 순으로 시도.
        """
        preferred = method or self.structured_output_method
        attempts = []

        if self.provider == "gemma":
            attempts = ["json_mode", "json_schema"]
            if preferred not in attempts and preferred != "function_calling":
                attempts.append(preferred)
        else:
            attempts = [preferred]
            if preferred != "json_mode":
                attempts.append("json_mode")

        last_exc: Optional[Exception] = None
        for candidate in attempts:
            try:
                kwargs: Dict[str, Any] = {"method": candidate}
                if strict is not None and candidate in {"function_calling", "json_schema"}:
                    kwargs["strict"] = strict
                return self._chat.with_structured_output(schema, **kwargs)
            except Exception as exc:  # pragma: no cover - depends on provider
                last_exc = exc
                logger.warning(
                    "with_structured_output(method=%s) 실패 (%s), 다음 방식으로 fallback",
                    candidate,
                    exc,
                )
                continue

        logger.warning(
            "구조화 출력 어댑터를 LLM 네이티브 기능으로 만들 수 없어 JSON 프롬프트 fallback 을 사용합니다. last=%s",
            last_exc,
        )
        return _JsonPromptStructuredLLM(self._chat, schema)


def build_role_llm(role: str, config_path: Optional[str] = None) -> RoleLLM:
    """role 설정을 읽어 RoleLLM 인스턴스를 만듭니다."""
    settings = get_role_llm_settings(role, config_path)
    chat = _build_chat_openai(settings)
    return RoleLLM(
        chat,
        provider=settings["provider"],
        structured_output_method=settings["structured_output_method"],
    )


def build_role_llm_from_settings(settings: Dict[str, str]) -> RoleLLM:
    """이미 해석된 설정 dict 로부터 RoleLLM 을 만듭니다."""
    chat = _build_chat_openai(settings)
    return RoleLLM(
        chat,
        provider=settings.get("provider", "openai"),
        structured_output_method=settings.get("structured_output_method", "function_calling"),
    )


def _build_chat_openai(settings: Dict[str, str]) -> ChatOpenAI:
    try:
        temperature = float(settings.get("temperature", "0"))
    except (TypeError, ValueError):
        temperature = 0.0

    return ChatOpenAI(
        model=settings["model"],
        api_key=settings.get("api_key") or "sk-placeholder",
        base_url=settings["base_url"],
        temperature=temperature,
    )


def build_dual_llm(config_path: Optional[str] = None) -> Dict[str, RoleLLM]:
    """reasoning / task LLM 한 쌍을 만듭니다."""
    return {
        "reasoning": build_role_llm("reasoning", config_path),
        "task": build_role_llm("task", config_path),
    }
