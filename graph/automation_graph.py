import logging
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.mcp_client import MCPClient
from core.llm_config import (
    get_llm_profile_settings,
    get_llm_settings,
    get_mcp_settings,
    get_automation_settings,
)
try:
    from .builder import build_automation_graph
    from .llm_factory import create_chat_llm
except ImportError:
    from graph.builder import build_automation_graph
    from graph.llm_factory import create_chat_llm

# 로깅 설정
logger = logging.getLogger(__name__)

class MiniHybridAgent:
    def __init__(
        self,
        mcp,
        execution_settings,
        planning_settings=None,
        analysis_settings=None,
        reporting_settings=None,
    ):
        self.mcp = mcp
        self.execution_llm = create_chat_llm(execution_settings, temperature=0)
        self.planner_llm = create_chat_llm(planning_settings or execution_settings, temperature=0)
        self.analyst_llm = create_chat_llm(analysis_settings or planning_settings or execution_settings, temperature=0)
        self.reporter_llm = create_chat_llm(reporting_settings or planning_settings or execution_settings, temperature=0)
        # 분리된 빌더를 통해 그래프 생성
        self.graph = build_automation_graph(
            self.mcp,
            execution_llm=self.execution_llm,
            planner_llm=self.planner_llm,
            analyst_llm=self.analyst_llm,
            reporter_llm=self.reporter_llm,
        )

async def run_automation(
    mcp,
    query,
    skill_ids,
    mode=None,
    model=None,
    api_key=None,
    base_url=None,
    provider=None,
    include_details: bool = True,
):
    """
    외부에서 자동화 워크플로우를 실행하기 위한 엔트리 포인트
    """
    if isinstance(skill_ids, str):
        skill_ids = [skill_ids]
        
    settings = get_llm_settings()
    execution_settings = get_llm_profile_settings("execution")
    planning_settings = get_llm_profile_settings("planning")
    analysis_settings = get_llm_profile_settings("analysis")
    reporting_settings = get_llm_profile_settings("reporting")
    auto_settings = get_automation_settings()
    
    # 하위 호환: run_automation 인자(model/api_key/base_url/provider)가 전달되면 execution profile을 override
    if model:
        execution_settings["model"] = model
    if api_key:
        execution_settings["api_key"] = api_key
    if base_url:
        execution_settings["base_url"] = base_url
    if provider:
        execution_settings["provider"] = provider

    # execution profile이 미설정인 경우 기존 default 설정 사용
    if not execution_settings.get("model"):
        execution_settings["model"] = settings["model"]
    if not execution_settings.get("api_key"):
        execution_settings["api_key"] = settings["api_key"]
    if not execution_settings.get("base_url"):
        execution_settings["base_url"] = settings["base_url"]
    if not execution_settings.get("provider"):
        execution_settings["provider"] = settings.get("provider", "openai_compatible")

    # planning/analysis/reporting profile이 없으면 execution으로 fallback
    for profile_settings in (planning_settings, analysis_settings, reporting_settings):
        if not profile_settings.get("model"):
            profile_settings["model"] = execution_settings["model"]
        if not profile_settings.get("api_key"):
            profile_settings["api_key"] = execution_settings["api_key"]
        if not profile_settings.get("base_url"):
            profile_settings["base_url"] = execution_settings["base_url"]
        if not profile_settings.get("provider"):
            profile_settings["provider"] = execution_settings["provider"]

    resolved_mode = mode or auto_settings["mode"]
    
    agent = MiniHybridAgent(
        mcp=mcp,
        execution_settings=execution_settings,
        planning_settings=planning_settings,
        analysis_settings=analysis_settings,
        reporting_settings=reporting_settings,
    )
    
    # 그래프 실행
    final = await agent.graph.ainvoke({
        "query": query, 
        "skill_ids": skill_ids, 
        "mode": resolved_mode
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
        llm_settings = get_llm_settings()
        mcp_settings = get_mcp_settings()
        auto_settings = get_automation_settings()

        mcp_client = MCPClient(base_url=mcp_settings["base_url"])
        my_skills = ["demo_mixed_args"]
        my_query = "스케줄링 업무 요청, 문의 해주세요"
        
        report_payload = await run_automation(
            mcp=mcp_client,
            query=my_query,
            skill_ids=my_skills,
            mode=auto_settings["mode"]
        )
        print(f"\n[AI 자동화 보고서]\n{report_payload['report']}")
        print(f"\n[구조화 상세]\n{report_payload['report_details']}")

    asyncio.run(example())
