import logging
import asyncio
from typing import Any, Dict, Optional

from mcp_client import MCPClient
from core.llm_config import (
    get_role_llm_settings,
    get_mcp_settings,
    get_automation_settings,
    get_llm_settings,
)
from core.llm_factory import build_role_llm_from_settings
from .builder import build_automation_graph

logger = logging.getLogger(__name__)


def _merge_settings(base: Dict[str, str], override: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """role 설정 위에 override 를 얹습니다 (None / 빈 문자열은 무시)."""
    if not override:
        return dict(base)
    merged = dict(base)
    for key, value in override.items():
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        merged[key] = value
    return merged


class MiniHybridAgent:
    """
    Dual-LLM 자동화 에이전트.

    - reasoning_llm: 계획/상황분석/리포트 (외부 LLM 권장)
    - task_llm: 파라미터 추출/스킬 매핑 (Gemma 등 경량 LLM 권장)
    """

    def __init__(
        self,
        mcp,
        reasoning_settings: Dict[str, str],
        task_settings: Optional[Dict[str, str]] = None,
    ):
        self.mcp = mcp
        self.reasoning_llm = build_role_llm_from_settings(reasoning_settings)
        self.task_llm = (
            build_role_llm_from_settings(task_settings) if task_settings else self.reasoning_llm
        )
        self.graph = build_automation_graph(self.mcp, self.reasoning_llm, task_llm=self.task_llm)


async def run_automation(
    mcp,
    query,
    skill_ids,
    mode=None,
    model=None,
    api_key=None,
    base_url=None,
    include_details: bool = True,
    reasoning_overrides: Optional[Dict[str, Any]] = None,
    task_overrides: Optional[Dict[str, Any]] = None,
):
    """
    외부에서 자동화 워크플로우를 실행하기 위한 엔트리 포인트.

    레거시 인자 (model/api_key/base_url) 는 reasoning LLM 의 동일 필드 override 로 동작합니다.
    """
    if isinstance(skill_ids, str):
        skill_ids = [skill_ids]

    reasoning_settings = get_role_llm_settings("reasoning")
    task_settings = get_role_llm_settings("task")
    auto_settings = get_automation_settings()

    legacy_overrides = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }
    reasoning_settings = _merge_settings(reasoning_settings, legacy_overrides)
    reasoning_settings = _merge_settings(reasoning_settings, reasoning_overrides)
    task_settings = _merge_settings(task_settings, task_overrides)

    resolved_mode = mode or auto_settings["mode"]

    agent = MiniHybridAgent(mcp, reasoning_settings, task_settings)

    final = await agent.graph.ainvoke({
        "query": query,
        "skill_ids": skill_ids,
        "mode": resolved_mode,
    })
    if include_details:
        return {
            "report": final.get("report", ""),
            "report_details": final.get("report_details", {}),
        }
    return final.get("report", "")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    async def example():
        mcp_settings = get_mcp_settings()
        auto_settings = get_automation_settings()

        mcp_client = MCPClient(base_url=mcp_settings["base_url"])
        my_skills = ["demo_mixed_args"]
        my_query = "메모장에 안녕써줘"

        report_payload = await run_automation(
            mcp=mcp_client,
            query=my_query,
            skill_ids=my_skills,
            mode=auto_settings["mode"]
        )
        print(f"\n[AI 자동화 보고서]\n{report_payload['report']}")
        print(f"\n[구조화 상세]\n{report_payload['report_details']}")

    asyncio.run(example())
