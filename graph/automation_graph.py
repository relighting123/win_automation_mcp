import logging
import asyncio
from langchain_openai import ChatOpenAI
from mcp_client import MCPClient
from core.llm_config import (
    get_llm_settings,
    get_mcp_settings,
    get_automation_settings,
    normalize_automation_mode,
)
from .builder import build_automation_graph

# 로깅 설정
logger = logging.getLogger(__name__)

# LLM 프롬프트 로거가 자동화 실행 시 항상 출력되도록 기본 레벨을 보장한다.
# (루트 logger 가 WARNING 이라도 INFO 로그를 받을 수 있게 한다.)
_llm_prompt_logger = logging.getLogger("llm.prompt")
if _llm_prompt_logger.level == logging.NOTSET:
    _llm_prompt_logger.setLevel(logging.INFO)

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
    resolved_mode = normalize_automation_mode(mode or auto_settings["mode"])
    
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
    
    async def example():
        llm_settings = get_llm_settings()
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
