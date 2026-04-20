"""
automation_graph.py
────────────────────────────────────────────────────────────────────
비동기 결정론적 "Fan-out/Fan-in" 자동화 그래프 (Smart Session Manager)

Flow
────
      ┌──► [parameterizer] ──┐
  START                      ├──► [builder] ──► [executor] ──► END
      └──► [session_manager] ┘
        (LLM 추출 & 세션 체크 병렬)   (결과 취합/분석)     (남은 단계 실행)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, Final, List, TypedDict, Union

from langchain_core.messages import HumanMessage
from langchain_openai import AsyncChatOpenAI
from langgraph.graph import END, StateGraph, START

from mcp_client import MCPClient

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────
_JSON_FENCE_RE: Final = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


# ─────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────
class AutomationState(TypedDict):
    """LangGraph 노드 간에 공유되는 불변 상태 컨테이너."""
    user_input: str
    param_schema: Dict[str, str]
    
    immediate_steps: List[Dict[str, Any]]         # 초기 실행 도구 (주로 앱 런처)
    parameterized_templates: List[Union[Dict[str, Any], List[Dict[str, Any]]]]

    params: Dict[str, Any]
    steps: List[List[Dict[str, Any]]]
    current_step: int
    history: List[Dict[str, Any]]
    status: str


# ─────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────
def _strip_fences(text: str) -> str:
    m = _JSON_FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _fill_template(value: Any, params: Dict[str, Any]) -> Any:
    match value:
        case str():
            try: return value.format_map(params)
            except KeyError: return value
        case dict():
            return {k: _fill_template(v, params) for k, v in value.items()}
        case list():
            return [_fill_template(v, params) for v in value]
        case _:
            return value


# ─────────────────────────────────────────────────────────────────
# Graph Factory
# ─────────────────────────────────────────────────────────────────
def build_automation_graph(llm: AsyncChatOpenAI, mcp: MCPClient) -> Any:

    # ── Node 1: Parameterizer (LLM Extraction) ───────────────────
    async def parameterizer_node(state: AutomationState) -> Dict[str, Any]:
        logger.info("[PARAMETERIZER] LLM 파라미터 추출 시작...")
        schema_lines = "\n".join(f"  - {k}: {desc}" for k, desc in state["param_schema"].items())
        prompt = (
            f"[추출 스키마]\n{schema_lines}\n\n"
            f"[사용자 요청]\n{state['user_input']}\n\n"
            "위 요청에서 필요한 정보를 추출하여 JSON으로만 응답하세요."
        )
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        try:
            params = json.loads(_strip_fences(response.content))
        except:
            params = {}
        
        logger.info("[PARAMETERIZER] 추출 완료: %s", params)
        return {"params": params}

    # ── Node 2: Session Manager (Smart App Launcher) ──────────────
    async def session_manager_node(state: AutomationState) -> Dict[str, Any]:
        """앱 세션 상태를 체크하여 필요할 때만 실행합니다."""
        logger.info("[SESSION_MANAGER] 세션 상태 체크 및 초기화 시작...")
        
        # 1. 현재 연결 상태 확인
        try:
            status_raw = await mcp.call_tool("get_connection_status", {})
            status = json.loads(status_raw) if isinstance(status_raw, str) else status_raw
            is_active = status.get("is_connected", False)
        except Exception:
            is_active = False

        results = []
        for s in state["immediate_steps"]:
            tool_name = s["tool"]
            args = s.get("args", {})
            
            # 앱 런처 도구일 경우 스마트 체크
            if tool_name == "launch_application" and is_active:
                logger.info("[SESSION_MANAGER] 앱이 이미 실행 중입니다. 실행 단계를 건너뜁니다.")
                results.append({"tool": tool_name, "result": "skipped (already active)", "status": "existing"})
                continue
            
            # 실행이 필요하거나 다른 종류의 도구인 경우
            try:
                res = await mcp.call_tool(tool_name, args)
                results.append({"tool": tool_name, "result": res, "status": "launched"})
            except Exception as e:
                results.append({"tool": tool_name, "error": str(e)})

        logger.info("[SESSION_MANAGER] 세션 관리 완료")
        return {"history": [{"group": "session_init", "results": results}]}

    # ── Node 3: Builder (Join & Analysis) ────────────────────────
    async def builder_node(state: AutomationState) -> Dict[str, Any]:
        logger.info("[BUILDER] 취합 및 후속 계획 수립...")
        
        params = state.get("params", {})
        final_steps: List[List[Dict[str, Any]]] = []
        
        for item in state["parameterized_templates"]:
            if isinstance(item, list):
                group = [{"tool": s["tool"], "args": _fill_template(s.get("args", {}), params)} for s in item]
                final_steps.append(group)
            else:
                step = {"tool": item["tool"], "args": _fill_template(item.get("args", {}), params)}
                final_steps.append([step])

        return {"steps": final_steps, "current_step": 0, "status": "built"}

    # ── Node 4: Executor (Remaining Steps) ───────────────────────
    async def executor_node(state: AutomationState) -> Dict[str, Any]:
        idx = state["current_step"]
        group = state["steps"][idx]
        
        async def _call(step_info: Dict[str, Any]):
            name, args = step_info["tool"], step_info.get("args", {})
            try:
                res = await mcp.call_tool(name, args)
                return {"tool": name, "result": res}
            except Exception as e:
                return {"tool": name, "error": str(e)}

        results = await asyncio.gather(*[_call(s) for s in group])
        new_history = state["history"] + [{"group": idx + 1, "results": results}]
        
        if any("error" in r for r in results):
            return {"history": new_history, "current_step": len(state["steps"]), "status": "failed"}
        
        return {"history": new_history, "current_step": idx + 1, "status": "in_progress"}

    # ── Graph Building ──────────────────────────────────────────
    workflow = StateGraph(AutomationState)

    workflow.add_node("parameterizer", parameterizer_node)
    workflow.add_node("session_manager", session_manager_node)
    workflow.add_node("builder", builder_node)
    workflow.add_node("executor", executor_node)

    # Fan-out
    workflow.add_edge(START, "parameterizer")
    workflow.add_edge(START, "session_manager")

    # Fan-in
    workflow.add_edge("parameterizer", "builder")
    workflow.add_edge("session_manager", "builder")

    workflow.add_edge("builder", "executor")
    
    def _cont(state): return "continue" if state["current_step"] < len(state["steps"]) else "end"
    workflow.add_conditional_edges("executor", _cont, {"continue": "executor", "end": END})
    
    return workflow.compile()


# ─────────────────────────────────────────────────────────────────
# Runner & Example
# ─────────────────────────────────────────────────────────────────
async def run_automation(
    *,
    user_input: str,
    param_schema: Dict[str, str],
    immediate_steps: List[Dict[str, Any]],
    parameterized_templates: List[Union[Dict[str, Any], List[Dict[str, Any]]]],
    llm: AsyncChatOpenAI,
    mcp: MCPClient,
) -> AutomationState:
    app = build_automation_graph(llm, mcp)
    initial: AutomationState = {
        "user_input": user_input, "param_schema": param_schema,
        "immediate_steps": immediate_steps, "parameterized_templates": parameterized_templates,
        "params": {}, "steps": [], "current_step": 0, "history": [], "status": "start",
    }
    
    final: AutomationState = {} # type: ignore
    async for event in app.astream(initial):
        for _, values in event.items():
            final = {**final, **values}

    return final


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    _llm = AsyncChatOpenAI(api_key=os.environ["OPENAI_API_KEY"], model="gpt-4o-mini")
    _mcp = MCPClient()

    _schema = {"msg": "입력할 텍스트"}
    _immediate = [{"tool": "launch_application", "args": {"executable_path": "notepad.exe"}}]
    _templates = [{"tool": "type_app_text", "args": {"text": "{msg}"}}]

    asyncio.run(run_automation(
        user_input="메모장에 '스마트 세션 테스트'라고 써줘",
        param_schema=_schema,
        immediate_steps=_immediate,
        parameterized_templates=_templates,
        llm=_llm,
        mcp=_mcp
    ))
