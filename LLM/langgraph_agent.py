import operator
from typing import Annotated, Sequence, TypedDict, Dict, Any, List, Tuple
import json
from pydantic import BaseModel, Field

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langchain_core.tools import StructuredTool

class AgentState(TypedDict):
    """에이전트 상태 정의"""
    input: str
    plan: List[Dict[str, Any]]  # [{"tool": "name", "args": {...}}]
    current_step: int
    results: List[Any]
    messages: Annotated[Sequence[BaseMessage], operator.add]
    final_response: str

def create_mcp_agent(api_key: str, base_url: str, model_name: str, tools_metadata: List[Dict[str, Any]], call_tool_func):
    """
    명시적인 Workflow(Plan-and-Execute) 방식의 에이전트를 생성합니다.
    """
    
    # 1. LLM 초기화
    llm = ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        temperature=0
    )
    
    # 도구 정보 텍스트 (Planner를 위해)
    tools_desc = ""
    for t in tools_metadata:
        f = t['function']
        tools_desc += f"- {f['name']}: {f['description']}\n  Args: {json.dumps(f['parameters'], ensure_ascii=False)}\n"

    # 2. 노드 정의
    
    def planner_node(state: AgentState):
        """사용자 요청을 분석하여 명시적인 도구 실행 계획(JSON)을 수립합니다."""
        
        # 만약 이미 계획이 전달되었다면 (Manual Workflow), LLM 수립 단계를 건너뜁니다.
        if state.get("plan") and len(state["plan"]) > 0:
            return {
                "plan": state["plan"],
                "current_step": 0,
                "messages": [AIMessage(content=f"사용자 정의 계획({len(state['plan'])}단계)을 실행합니다.")]
            }
            
        prompt = f"""
당신은 Windows 자동화 전문가입니다. 사용자의 요청을 수행하기 위해 가용한 MCP 도구들을 사용하는 정교한 계획을 세우세요.
결과는 반드시 아래 JSON 형식의 리스트여야 합니다.

[
  {{"tool": "도구이름", "args": {{"인자명": "값"}}}},
  ...
]

[가용한 도구 목록]
{tools_desc}

[사용자 요청]
{state['input']}

불필요한 단계는 생략하고, 성공을 위해 필요한 모든 단계를 포함하세요.
만약 바탕화면에 저장해야 한다면, 경로에 'Desktop'이 포함되도록 인자를 구성하세요.
"""
        response = llm.invoke([HumanMessage(content=prompt)])
        
        # JSON 추출 (마크다운 코드 블록 제거 등)
        content = response.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        try:
            plan = json.loads(content)
        except:
            # Fallback: 유연한 파싱 시도 (JSON 배열만 추출)
            import re
            match = re.search(r"\[.*\]", content, re.DOTALL)
            if match:
                try:
                    plan = json.loads(match.group())
                except:
                    plan = []
            else:
                plan = []
            
        return {
            "plan": plan,
            "current_step": 0,
            "messages": [AIMessage(content=f"계획을 수립했습니다: {len(plan)}개 단계 순차 실행 시작")]
        }

    def executor_node(state: AgentState):
        """계획된 단계 중 현재 단계를 실행합니다."""
        step_idx = state['current_step']
        if step_idx >= len(state['plan']):
            return {"final_response": "모든 단계가 완료되었습니다."}
            
        step = state['plan'][step_idx]
        tool_name = step['tool']
        tool_args = step['args']
        
        # 실제 도구 호출
        result = call_tool_func(tool_name, tool_args)
        
        return {
            "results": state.get('results', []) + [result],
            "current_step": step_idx + 1,
            "messages": [AIMessage(content=f"단계 {step_idx + 1} 실행 완료 ({tool_name}): {json.dumps(result, ensure_ascii=False)[:200]}...")]
        }

    def final_node(state: AgentState):
        """전체 결과를 요약하여 사용자에게 보고합니다."""
        prompt = f"""
모든 자동화 작업 단계가 완료되었습니다. 아래 실행 이력과 결과를 바탕으로 사용자에게 친절하게 한국어로 최종 보고를 하세요.

[실행 계획 및 결과]
{json.dumps(state['plan'], ensure_ascii=False)}
{json.dumps(state['results'], ensure_ascii=False)}

[사용자 요청]
{state['input']}
"""
        response = llm.invoke([HumanMessage(content=prompt)])
        return {"final_response": response.content, "messages": [response]}

    # 3. 그래프 구축
    workflow = StateGraph(AgentState)
    
    workflow.add_node("planner", planner_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("finalizer", final_node)
    
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "executor")
    
    def should_continue(state: AgentState):
        if state['current_step'] < len(state['plan']):
            return "continue"
        return "end"
        
    workflow.add_conditional_edges(
        "executor",
        should_continue,
        {
            "continue": "executor",
            "end": "finalizer"
        }
    )
    workflow.add_edge("finalizer", END)
    
    return workflow.compile()
