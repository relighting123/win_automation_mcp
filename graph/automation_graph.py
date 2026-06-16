import logging
import asyncio
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.mcp_client import create_mcp_client
from core.automation_run_control import begin_run_control, end_run_control
from core.llm_config import (
    get_llm_profile_settings,
    get_llm_settings,
    get_mcp_settings,
    get_automation_settings,
)
try:
    from .builder import build_automation_graph
    from .llm_factory import create_chat_llm
    from .progress import format_graph_progress_event
except ImportError:
    from graph.builder import build_automation_graph
    from graph.llm_factory import create_chat_llm
    from graph.progress import format_graph_progress_event

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
    on_progress: Optional[Callable[[str], None]] = None,
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

    resolved_mode = (mode if mode is not None else auto_settings["mode"]).strip().lower()
    if resolved_mode not in {"auto", "semi", "manual"}:
        resolved_mode = "semi"
    logger.info(
        "automation graph 실행: mode=%s (요청=%s, app_config=%s)",
        resolved_mode,
        mode,
        auto_settings["mode"],
    )
    
    agent = MiniHybridAgent(
        mcp=mcp,
        execution_settings=execution_settings,
        planning_settings=planning_settings,
        analysis_settings=analysis_settings,
        reporting_settings=reporting_settings,
    )

    # 그래프 중간 extract 단계에서 tools/list가 다시 나가지 않도록 선로드
    if hasattr(mcp, "warmup") and callable(getattr(mcp, "warmup")):
        await mcp.warmup()
    elif hasattr(mcp, "list_tools") and callable(getattr(mcp, "list_tools")):
        await mcp.list_tools()
    
    initial_state = {
        "query": query,
        "skill_ids": skill_ids,
        "mode": resolved_mode,
    }

    begin_run_control(resolved_mode)
    try:
        if on_progress is None:
            final = await agent.graph.ainvoke(initial_state)
        else:
            on_progress(f"자동화 그래프 시작 (mode={resolved_mode})")
            progress_context: Dict[str, Any] = {"history_len": 0}
            accumulated: Dict[str, Any] = dict(initial_state)
            async for chunk in agent.graph.astream(initial_state, stream_mode="updates"):
                for node_name, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    accumulated.update(update)
                    for line in format_graph_progress_event(
                        node_name,
                        update,
                        context=progress_context,
                    ):
                        on_progress(line)
            final = accumulated
            on_progress("자동화 그래프 완료")
    finally:
        end_run_control()
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

        mcp_client = create_mcp_client(base_url=mcp_settings["base_url"])
        my_skills = ["demo_mixed_args"]
        my_query = "스케줄링 업무 요청, 문의 해주세요"
        
        report_payload = await run_automation(
            mcp=mcp_client,
            query=my_query,
            skill_ids=my_skills,
        )
        print(f"\n[AI 자동화 보고서]\n{report_payload['report']}")
        print(f"\n[구조화 상세]\n{report_payload['report_details']}")

    asyncio.run(example())
