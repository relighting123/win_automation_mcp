from __future__ import annotations

from typing import Any, Dict

from langchain_openai import ChatOpenAI


def create_chat_llm(settings: Dict[str, Any], temperature: float = 0):
    """
    provider 설정에 따라 LangChain Chat 모델 인스턴스를 생성합니다.

    지원 provider:
      - openai_compatible (기본): OpenAI API 호환 엔드포인트
      - google_genai: Google Generative AI (Gemini/Gemma 계열)
      - ollama: Ollama 로컬/원격 서버
    """
    provider = str(settings.get("provider", "openai_compatible")).strip().lower()
    model = str(settings.get("model", "")).strip()
    api_key = str(settings.get("api_key", "")).strip()
    base_url = str(settings.get("base_url", "")).strip()

    if provider in {"openai_compatible", "openai", "groq", "openrouter"}:
        kwargs: Dict[str, Any] = {
            "model": model,
            "temperature": temperature,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    if provider in {"google_genai", "google"}:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise ImportError(
                "google_genai provider를 사용하려면 'langchain-google-genai' 패키지를 설치하세요."
            ) from exc

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=temperature,
        )

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise ImportError(
                "ollama provider를 사용하려면 'langchain-ollama' 패키지를 설치하세요."
            ) from exc

        kwargs = {
            "model": model,
            "temperature": temperature,
        }
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOllama(**kwargs)

    raise ValueError(
        f"지원하지 않는 provider '{provider}'. "
        "지원 목록: openai_compatible, google_genai, ollama"
    )
