import json, logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field # 구조화된 출력을 위한 규격 정의
from langchain_openai import ChatOpenAI # OpenAI 기반 모델 호출
from langgraph.graph import StateGraph, END # 워크플로우 그래프 제어
from mcp_client import MCPClient # MCP 서버 통신용 클라이언트
from core.llm_config import get_llm_settings

# 1. AI가 추출할 데이터 구조 정의 (Tool 명칭과 인자값의 쌍)
class ToolCall(BaseModel):
    tool: str = Field(description="실행할 도구의 이름")
    args: Dict[str, Any] = Field(default_factory=dict, description="도구에 주입할 파라미터")

# 2. 에이전트가 들고 다닐 메모리(상태) 정의
class AgentState(BaseModel):
    query: str; plan: List[str] # 사용자 질문과 정해진 실행 순서
    enriched_plan: List[ToolCall] = [] # AI가 파라미터를 채운 결과물
    history: List[Dict] = [] # 실행 결과 로그
    report: str = "" # 최종 자연어 분석 결과

class MiniHybridAgent:
    def __init__(self, mcp, model, api_key, base_url):
        self.mcp = mcp
        # 3. LLM 설정: API Key, URL, 모델명을 동적으로 주입
        self.llm = ChatOpenAI(model=model, api_key=api_key, base_url=base_url, temperature=0)
        self.graph = self._build()

    def _build(self):
        # 4. 워크플로우 단계 정의 (추출 -> 실행 -> 요약)
        builder = StateGraph(AgentState)
        builder.add_node("extract", self._extract)
        builder.add_node("run", self._run)
        builder.add_node("report", self._report)
        builder.set_entry_point("extract")
        builder.add_edge("extract", "run")
        builder.add_edge("run", "report")
        builder.add_edge("report", END)
        return builder.compile()

    async def _extract(self, state: AgentState):
        """규칙(Rule)과 예시(Few-shot)를 포함하여 정교하게 파라미터 추출"""
        from langchain_core.prompts import ChatPromptTemplate
        
        # 5. 추출 규칙 및 예시 정의 (프롬프트 엔지니어링)
        system_msg = (
            "당신은 Windows 자동화를 위한 고도의 파라미터 추출기입니다.\n\n"
            "### 추출 규칙 ###\n"
            "1. 질의에 명시되지 않은 값은 도구 명세의 기본값을 따르되, 없으면 가장 안전한 값을 넣으세요.\n"
            "2. 숫자는 반드시 정수(Integer) 형식으로 추출하세요.\n"
            "3. '마지막' 또는 '최신' 같은 단어는 컨텍스트에 따라 적절한 식별자로 변환하세요.\n\n"
            "### 예시 (Few-shot) ###\n"
            "- 질의: '어드민으로 로그인'\n  - 결과: [{\"tool\": \"login_to_app\", \"args\": {\"username\": \"admin\"}}]\n"
            "- 질의: '루프 50번'\n  - 결과: [{\"tool\": \"set_loop_count\", \"args\": {\"count\": 50}}]"
        )
        
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_msg),
            ("user", "질의: {query}\n현재 실행 순서: {plan}\n사용 가능한 도구 정보:\n{tools_info}")
        ])

        structured_llm = self.llm.with_structured_output(List[ToolCall])
        tools_info = str(await self.mcp.list_tools())
        
        # 인자값 매핑 로직 실행
        chain = prompt_template | structured_llm
        enriched = await chain.ainvoke({
            "query": state.query,
            "plan": state.plan,
            "tools_info": tools_info
        })
        return {"enriched_plan": enriched}

    async def _run(self, state: AgentState):
        """추출된 파라미터로 MCP 도구 순차 실행"""
        results = []
        for call in state.enriched_plan:
            # 6. AI가 뽑은 tool 이름과 args를 그대로 MCP 서버에 전달
            out = await self.mcp.call_tool(call.tool, call.args)
            results.append({"tool": call.tool, "output": out})
        return {"history": results}

    async def _report(self, state: AgentState):
        """실행 이력을 바탕으로 최종 결과를 자연어로 해석"""
        # 7. 실행 로그를 LLM에 전달하여 사용자가 이해하기 쉬운 보고서 생성
        prompt = f"요청: {state.query}\n결과: {state.history}\n결과를 요약해서 보고하세요."
        res = await self.llm.ainvoke(prompt)
        return {"report": res.content}

async def run_automation(mcp, query, plan, model=None, api_key=None, base_url=None):
    """외부에서 호출하기 위한 실행 함수"""
    settings = get_llm_settings()
    resolved_model = model or settings["model"]
    resolved_api_key = api_key or settings["api_key"]
    resolved_base_url = base_url or settings["base_url"]
    agent = MiniHybridAgent(mcp, resolved_model, resolved_api_key, resolved_base_url)
    # 8. 그래프를 실행하고 최종 리포트 반환
    final = await agent.graph.ainvoke({"query": query, "plan": plan})
    return final["report"]

if __name__ == "__main__":
    import asyncio
    
    async def example():
        llm_settings = get_llm_settings()
        # MCP 클라이언트 및 설정 준비
        mcp_client = MCPClient(base_url="http://localhost:8000/mcp")
        my_plan = ["login_to_app", "open_rule_screen", "set_loop_count"]
        my_query = "운영자 계정으로 로그인해서 Rule 창 열고 루프 40번으로 설정해"
        
        # 워크플로우 실행
        report = await run_automation(
            mcp=mcp_client,
            query=my_query,
            plan=my_plan,
            model=llm_settings["model"],
            api_key=llm_settings["api_key"],
            base_url=llm_settings["base_url"]
        )
        print(f"\n[AI 자동화 보고서]\n{report}")

    # 비동기 함수 실행
    # asyncio.run(example())
