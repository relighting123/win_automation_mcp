import json
import operator
from typing import Annotated, Any, Dict, List, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph

class AgentState(TypedDict):
    """기본 순차 실행 에이전트 상태."""
    input: str
    plan: List[Dict[str, Any]]  # [{"tool": "...", "args": {...}}]
    current_step: int
    results: List[Any]
    messages: Annotated[Sequence[BaseMessage], operator.add]
    final_response: str

def create_mcp_agent(api_key: str, base_url: str, model_name: str, tools_metadata: List[Dict[str, Any]], call_tool_func):
    """
    가장 기본적인 LangGraph 순차 실행 에이전트를 생성합니다.
    - 입력 plan 형식: [{"tool": "도구명", "args": {...}}, ...]
    - plan 순서대로 도구를 1개씩 호출합니다.
    """
    # 인터페이스 호환을 위해 인자를 유지합니다.
    _ = (api_key, base_url, model_name, tools_metadata)

    # 2. 노드 정의
    def planner_node(state: AgentState):
        """사용자 제공 plan을 검증하고 실행 준비를 합니다."""
        plan = state.get("plan", []) or []
        if not plan:
            return {
                "plan": [],
                "current_step": 0,
                "results": [],
                "final_response": (
                    "실행할 plan이 없습니다. "
                    "[{\"tool\":\"tool_name\", \"args\": {...}}] 형식의 리스트를 전달해주세요."
                ),
                "messages": [AIMessage(content="plan이 비어 있어 실행을 종료합니다.")],
            }

        normalized_plan: List[Dict[str, Any]] = []
        for idx, step in enumerate(plan):
            if not isinstance(step, dict) or "tool" not in step:
                return {
                    "plan": [],
                    "current_step": 0,
                    "results": [],
                    "final_response": f"{idx + 1}번째 step 형식이 잘못되었습니다. (필수 키: tool)",
                    "messages": [AIMessage(content=f"{idx + 1}번째 step 검증 실패")],
                }

            args = step.get("args", {})
            if not isinstance(args, dict):
                return {
                    "plan": [],
                    "current_step": 0,
                    "results": [],
                    "final_response": f"{idx + 1}번째 step의 args는 dict여야 합니다.",
                    "messages": [AIMessage(content=f"{idx + 1}번째 step args 타입 오류")],
                }

            normalized_plan.append({"tool": step["tool"], "args": args})

        return {
            "plan": normalized_plan,
            "current_step": 0,
            "results": [],
            "messages": [AIMessage(content=f"{len(normalized_plan)}개 step 순차 실행을 시작합니다.")],
        }

    def executor_node(state: AgentState):
        """계획된 단계 중 현재 단계를 실행합니다."""
        step_idx = state["current_step"]
        if step_idx >= len(state["plan"]):
            return {}

        step = state["plan"][step_idx]
        tool_name = step["tool"]
        tool_args = step.get("args", {})

        try:
            tool_result = call_tool_func(tool_name, tool_args)
            result_entry = {
                "step": step_idx + 1,
                "tool": tool_name,
                "args": tool_args,
                "status": "ok",
                "result": tool_result,
            }
            msg = f"step {step_idx + 1} 완료: {tool_name}"
        except Exception as exc:
            result_entry = {
                "step": step_idx + 1,
                "tool": tool_name,
                "args": tool_args,
                "status": "error",
                "error": str(exc),
            }
            msg = f"step {step_idx + 1} 실패: {tool_name} - {exc}"

        return {
            "results": state.get("results", []) + [result_entry],
            "current_step": step_idx + 1,
            "messages": [AIMessage(content=msg)],
        }

    def final_node(state: AgentState):
        """실행 결과를 간단히 문자열로 반환합니다."""
        plan = state.get("plan", [])
        results = state.get("results", [])
        success_count = sum(1 for item in results if item.get("status") == "ok")
        fail_count = len(results) - success_count

        summary = {
            "requested_steps": len(plan),
            "executed_steps": len(results),
            "success": success_count,
            "failed": fail_count,
            "results": results,
        }
        return {
            "final_response": json.dumps(summary, ensure_ascii=False, indent=2),
            "messages": [AIMessage(content="모든 step 실행이 종료되었습니다.")],
        }

    # 3. 그래프 구축
    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("finalizer", final_node)

    workflow.set_entry_point("planner")

    def should_execute(state: AgentState):
        if state.get("plan"):
            return "execute"
        return "end"

    workflow.add_conditional_edges(
        "planner",
        should_execute,
        {
            "execute": "executor",
            "end": "finalizer",
        },
    )

    def should_continue(state: AgentState):
        if state["current_step"] < len(state["plan"]):
            return "continue"
        return "end"

    workflow.add_conditional_edges(
        "executor",
        should_continue,
        {
            "continue": "executor",
            "end": "finalizer",
        },
    )
    workflow.add_edge("finalizer", END)

    return workflow.compile()
