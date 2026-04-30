import json, logging, yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field # 구조화된 출력을 위한 규격 정의
from langchain_openai import ChatOpenAI # OpenAI 기반 모델 호출
from langgraph.graph import StateGraph, END # 워크플로우 그래프 제어
from mcp_client import MCPClient # MCP 서버 통신용 클라이언트
from core.llm_config import get_llm_settings, get_mcp_settings
from skills.sequence_skill import SequenceSkill

# 1. AI가 추출할 데이터 구조 정의 (Tool 명칭과 인자값의 쌍)
class ToolCall(BaseModel):
    tool: str = Field(description="실행할 도구의 이름")
    args: Dict[str, Any] = Field(default_factory=dict, description="도구에 주입할 파라미터")

# 2. 에이전트가 들고 다닐 메모리(상태) 정의
class AgentState(BaseModel):
    query: str
    skill_ids: List[str] # 시퀀스 실행할 스킬 리스트
    current_index: int = 0 # 현재 실행 중인 스킬 인덱스
    tool_sequence: List[str] = [] # 현재 스킬의 도구 순서
    enriched_plan: List[ToolCall] = [] # 현재 스킬의 파라미터가 채워진 결과
    history: List[Dict] = [] # 전체 실행 결과 로그
    check_status: str = "" # AI 상황 체크 결과 요약
    report: str = "" # 최종 자연어 분석 결과

class MiniHybridAgent:
    def __init__(self, mcp, model, api_key, base_url):
        self.mcp = mcp
        # 3. LLM 설정: API Key, URL, 모델명을 동적으로 주입
        self.llm = ChatOpenAI(model=model, api_key=api_key, base_url=base_url, temperature=0)
        self.graph = self._build()

    def _build(self):
        # 4. 워크플로우 단계 정의 (상황 체크 -> 추출 -> 실행 -> 다음 체크 -> 요약)
        builder = StateGraph(AgentState)
        builder.add_node("check_situation", self._check_situation)
        builder.add_node("extract", self._extract)
        builder.add_node("run", self._run)
        builder.add_node("next", self._next)
        builder.add_node("report", self._report)
        
        builder.set_entry_point("check_situation")
        builder.add_edge("check_situation", "extract")
        builder.add_edge("extract", "run")
        builder.add_edge("run", "next")
        
        # 조건부 엣지: 남은 스킬이 있으면 상황 체크로 돌아가고, 없으면 보고서 작성
        builder.add_conditional_edges(
            "next",
            lambda x: "check_situation" if x.current_index < len(x.skill_ids) else "report"
        )
        builder.add_edge("report", END)
        return builder.compile()

    async def _check_situation(self, state: AgentState):
        """현재 화면 상태를 분석하여 스킬 실행 가능 여부 체크 (AI-in-the-loop)"""
        current_skill_id = state.skill_ids[state.current_index]
        logger.info(f"--- 상황 체크 시작: {current_skill_id} (Index: {state.current_index}) ---")
        
        # 1. MCP를 통해 현재 화면 상태 획득
        state_info = await self.mcp.call_tool("describe_current_state", {"include_components": False})
        
        # 2. LLM에게 현재 상황이 스킬 실행에 적합한지 판단 요청
        prompt = (
            f"당신은 자동화 감시관입니다. 현재 화면 상태를 보고 다음 스킬을 실행하기에 적절한지 판단하세요.\n\n"
            f"현재 화면 상태: {state_info}\n"
            f"실행할 스킬 ID: {current_skill_id}\n\n"
            f"적절하다면 'OK', 부적절하다면 이유와 함께 'WAIT' 또는 'FAIL'을 포함하여 간략히 설명하세요."
        )
        res = await self.llm.ainvoke(prompt)
        check_msg = res.content
        logger.info(f"상황 체크 결과: {check_msg}")
        
        return {"check_status": check_msg}

    async def _extract(self, state: AgentState):
        """현재 인덱스의 Skill ID를 기반으로 도구 순서를 로드하고 파라미터 추출"""
        from langchain_core.prompts import ChatPromptTemplate
        current_skill_id = state.skill_ids[state.current_index]
        
        # 5-1. Skill 설정에서 도구 순서 추출
        try:
            skill = SequenceSkill(skill_name=current_skill_id)
            tool_sequence = []
            for step in skill.steps:
                name = step.get("tool") or step.get("type") or step.get("action")
                if name:
                    tool_sequence.append(name)
            
            if not tool_sequence:
                raise ValueError(f"Skill '{current_skill_id}'에 유효한 도구가 없습니다.")
        except Exception as e:
            logger.error(f"Skill 로드 실패: {e}")
            raise e

        # 5-2. 추출 규칙 및 예시 정의 (프롬프트 엔지니어링)
        system_msg = (
            "당신은 Windows 자동화를 위한 고도의 파라미터 추출기입니다.\n\n"
            "### 추출 규칙 ###\n"
            "1. 질의에 명시되지 않은 값은 도구 명세의 기본값을 따르되, 없으면 가장 안전한 값을 넣으세요.\n"
            "2. 숫자는 반드시 정수(Integer) 형식으로 추출하세요.\n"
            "3. '마지막' 또는 '최신' 같은 단어는 컨텍스트에 따라 적절한 식별자로 변환하세요."
        )
        
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_msg),
            ("user", "질의: {query}\n현재 상황: {check_status}\n현재 스킬({skill_id})의 도구 순서: {tool_sequence}\n사용 가능한 도구 정보:\n{tools_info}")
        ])

        structured_llm = self.llm.with_structured_output(List[ToolCall])
        tools_info = str(await self.mcp.list_tools())
        
        # 인자값 매핑 로직 실행
        chain = prompt_template | structured_llm
        enriched = await chain.ainvoke({
            "query": state.query,
            "check_status": state.check_status,
            "skill_id": current_skill_id,
            "tool_sequence": tool_sequence,
            "tools_info": tools_info
        })
        return {"enriched_plan": enriched, "tool_sequence": tool_sequence}

    async def _run(self, state: AgentState):
        """추출된 파라미터로 MCP 도구 순차 실행 (현재 스킬 분량)"""
        results = list(state.history) # 기존 이력 복사
        current_skill_id = state.skill_ids[state.current_index]
        
        for call in state.enriched_plan:
            logger.info(f"[Run] {call.tool} 실행 중... (Args: {call.args})")
            out = await self.mcp.call_tool(call.tool, call.args)
            results.append({
                "skill": current_skill_id,
                "tool": call.tool, 
                "output": out
            })
        return {"history": results}

    async def _next(self, state: AgentState):
        """다음 스킬로 인덱스 이동"""
        return {"current_index": state.current_index + 1}

    async def _report(self, state: AgentState):
        """실행 이력을 바탕으로 최종 결과를 자연어로 해석"""
        # 7. 실행 로그를 LLM에 전달하여 사용자가 이해하기 쉬운 보고서 생성
        prompt = f"요청: {state.query}\n결과: {state.history}\n결과를 요약해서 보고하세요."
        res = await self.llm.ainvoke(prompt)
        return {"report": res.content}

async def run_automation(mcp, query, skill_ids, model=None, api_key=None, base_url=None):
    """외부에서 호출하기 위한 실행 함수"""
    if isinstance(skill_ids, str):
        skill_ids = [skill_ids]
        
    settings = get_llm_settings()
    resolved_model = model or settings["model"]
    resolved_api_key = api_key or settings["api_key"]
    resolved_base_url = base_url or settings["base_url"]
    agent = MiniHybridAgent(mcp, resolved_model, resolved_api_key, resolved_base_url)
    # 8. 그래프를 실행하고 최종 리포트 반환
    final = await agent.graph.ainvoke({"query": query, "skill_ids": skill_ids})
    return final["report"]

if __name__ == "__main__":
    import asyncio
    
    async def example():
        llm_settings = get_llm_settings()
        mcp_settings = get_mcp_settings()
        # MCP 클라이언트 및 설정 준비
        mcp_client = MCPClient(base_url=mcp_settings["base_url"])
        my_skills = ["demo_app_mgmt_tools", "demo_app_control_tools"]
        my_query = "앱을 실행하고 커넥션 확인한 뒤, 메모장에 hello world라고 입력해줘"
        
        # 워크플로우 실행
        report = await run_automation(
            mcp=mcp_client,
            query=my_query,
            skill_ids=my_skills,
            model=llm_settings["model"],
            api_key=llm_settings["api_key"],
            base_url=llm_settings["base_url"]
        )
        print(f"\n[AI 자동화 보고서]\n{report}")

    # 비동기 함수 실행
    # asyncio.run(example())
