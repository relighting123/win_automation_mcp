import logging
import asyncio
import os
from langchain_openai import ChatOpenAI
from mcp_client import MCPClient
from core.llm_config import get_llm_settings, get_mcp_settings, get_automation_settings
from core.server_lifecycle import mcp_server_context
from .builder import build_automation_graph

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    """환경변수 -> bool 변환 헬퍼"""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "t"}


class MiniHybridAgent:
    def __init__(self, mcp, model, api_key, base_url):
        self.mcp = mcp
        self.llm = ChatOpenAI(model=model, api_key=api_key, base_url=base_url, temperature=0)
        # 분리된 빌더를 통해 그래프 생성
        self.graph = build_automation_graph(self.mcp, self.llm)

async def run_automation(
    mcp,
    query,
    skill_ids,
    mode=None,
    model=None,
    api_key=None,
    base_url=None,
    include_details: bool = True,
):
    """
    외부에서 자동화 워크플로우를 실행하기 위한 엔트리 포인트
    """
    if isinstance(skill_ids, str):
        skill_ids = [skill_ids]
        
    settings = get_llm_settings()
    auto_settings = get_automation_settings()
    
    resolved_model = model or settings["model"]
    resolved_api_key = api_key or settings["api_key"]
    resolved_base_url = base_url or settings["base_url"]
    resolved_mode = mode or auto_settings["mode"]
    
    agent = MiniHybridAgent(mcp, resolved_model, resolved_api_key, resolved_base_url)
    
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

    async def example(mcp_base_url: str):
        my_skills = ["demo_mixed_args"]
        my_query = "메모장에 안녕써줘"

        auto_settings = get_automation_settings()
        mcp_client = MCPClient(base_url=mcp_base_url)

        report_payload = await run_automation(
            mcp=mcp_client,
            query=my_query,
            skill_ids=my_skills,
            mode=auto_settings["mode"]
        )
        print(f"\n[AI 자동화 보고서]\n{report_payload['report']}")
        print(f"\n[구조화 상세]\n{report_payload['report_details']}")

    mcp_settings = get_mcp_settings()
    base_url = mcp_settings["base_url"]

    # 별도 터미널 없이 빠르게 서버를 띄우고 싶을 때:
    #   AUTOMATION_AUTOSTART_SERVER=1 python -m graph.automation_graph
    # (이미 서버가 떠 있으면 새로 띄우지 않고 그대로 재사용합니다.)
    autostart = _env_bool("AUTOMATION_AUTOSTART_SERVER", default=True)
    startup_timeout = float(os.getenv("AUTOMATION_SERVER_STARTUP_TIMEOUT", "30"))
    server_log = os.getenv("AUTOMATION_SERVER_LOG") or "logs/mcp_server_auto.log"

    with mcp_server_context(
        base_url,
        auto_start=autostart,
        startup_timeout=startup_timeout,
        log_file=server_log,
    ):
        asyncio.run(example(base_url))
