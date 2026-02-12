import os
from typing import Annotated, List, Dict, Any, TypedDict
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from mcp_client import MCPClient
import asyncio
import json

# State 정의
class AgentState(TypedDict):
    task: str
    plan: List[str]
    current_step_index: int
    history: List[BaseMessage]
    status: str

# 환경 변수 및 설정
# 윗단 모델 (Planner) - API 기반 (OpenAI 예시)
# os.environ["OPENAI_API_KEY"] = "your-api-key"
planner_llm = ChatOpenAI(model="gpt-4o", temperature=0)

# 아랫단 모델 (Executor) - 로컬 Gemma API (OpenAI 호환 포맷 가정)
executor_llm = ChatOpenAI(
    model="google/gemma-3-4b-it",
    openai_api_base="http://localhost:8001/v1",
    openai_api_key="local-token", # 더미 토큰
    temperature=0.1
)

mcp_client = MCPClient()

# Node 1: Planner - 상위 LLM
async def planner_node(state: AgentState):
    print("--- PLANNER ---")
    prompt = f"""
    당신은 Windows 프로그램을 제어하는 마스터 플래너입니다.
    사용자의 요청을 수행하기 위해 단계별 계획을 수립하세요.
    최대한 구체적으로 작성하세요.
    요청: {state['task']}
    
    계획 형식: JSON list of strings
    """
    
    response = await planner_llm.ainvoke([SystemMessage(content=prompt)])
    
    # 단순 파싱 (GPT-4가 JSON을 잘 준다고 가정)
    try:
        plan = json.loads(response.content)
    except:
        # JSON 형식이 아닐 경우 fallback (줄바꿈 기준)
        plan = [s.strip() for s in response.content.split('\n') if s.strip()]
        
    return {
        "plan": plan,
        "current_step_index": 0,
        "status": "planned"
    }

# Node 2: Executor - 로컬 Gemma를 통한 MCP Tool 호출
async def executor_node(state: AgentState):
    print(f"--- EXECUTOR (Step {state['current_step_index'] + 1}) ---")
    current_step = state['plan'][state['current_step_index']]
    
    # MCP 도구 목록 가져오기 (Gemma에게 전달할 용도)
    # 실제 구현에서는 client.list_tools() 결과를 Gemini/Gemma의 Tool 정의 형식으로 변환 필요
    # 여기선 예시로 고정된 도구 정의를 사용하거나 단순 텍스트 프롬프트 전달
    
    prompt = f"""
    당신은 Windows 자동화 도구 호출 전문가입니다.
    현재 단계: {current_step}
    전체 상황: {state['task']}
    
    가용한 MCP 도구들을 사용하여 이 단계를 수행하세요.
    최종 결과만 'SUCCESS' 또는 'FAILURE'를 포함하여 보고하세요.
    """
    
    response = await executor_llm.ainvoke([HumanMessage(content=prompt)])
    
    # Gemma가 도구 호출을 수행했다고 가정하고, 실제론 Tool Call 파싱 및 MCP 클라이언트 호출 로직이 들어감
    # 여기서는 간단하게 응답을 이력에 추가
    
    return {
        "history": state['history'] + [AIMessage(content=f"Step {state['current_step_index'] + 1} 완료: {response.content}")],
        "current_step_index": state['current_step_index'] + 1
    }

# 조건부 엣지: 모든 단계 완료 여부 확인
def should_continue(state: AgentState):
    if state['current_step_index'] < len(state['plan']):
        return "continue"
    return "end"

# Graph 구축
workflow = StateGraph(AgentState)

workflow.add_node("planner", planner_node)
workflow.add_node("executor", executor_node)

workflow.set_entry_point("planner")
workflow.add_edge("planner", "executor")

workflow.add_conditional_edges(
    "executor",
    should_continue,
    {
        "continue": "executor",
        "end": END
    }
)

app = workflow.compile()

async def run_automation(task: str):
    initial_state = {
        "task": task,
        "plan": [],
        "current_step_index": 0,
        "history": [],
        "status": "start"
    }
    
    async for event in app.astream(initial_state):
        for kind, values in event.items():
            print(f"Node '{kind}' finished.")
            if 'plan' in values:
                print(f"Plan: {values['plan']}")
            if 'current_step_index' in values:
                print(f"Progress: {values['current_step_index']}/{len(values.get('plan', []))}")

if __name__ == "__main__":
    task = "메모장을 열고 'Hello from Gemma and LangGraph'라고 입력한 뒤 저장해줘."
    asyncio.run(run_automation(task))
