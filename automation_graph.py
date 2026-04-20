"""
automation_graph.py
────────────────────────────────────────────────────────────────────
비동기 결정론적 "병렬" 자동화 그래프 (Parameterizer → Builder → Executor)

Flow
────
  [parameterizer] ──► [builder] ──► [executor] ──► (loop) ──► END
       │ LLM 1회           │ 템플릿 치환        │ MCP 병렬/순차 실행
       │ 파라미터 추출      └─► steps 완성       └─► asyncio.gather 사용
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, Final, List, TypedDict, Union

from langchain_core.messages import HumanMessage
from langchain_openai import AsyncChatOpenAI
from langgraph.graph import END, StateGraph

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
    step_templates: List[Union[Dict[str, Any], List[Dict[str, Any]]]]  # 단일 또는 병렬 그룹

    params: Dict[str, Any]
    steps: List[List[Dict[str, Any]]]     # 실행 시점에는 무조건 그룹(List) 단위로 관리
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

    # ── Node 1: Parameterizer ────────────────────────────────────
    async def parameterizer_node(state: AutomationState) -> Dict[str, Any]:
        logger.info("[PARAMETERIZER] 파라미터 추출 중...")
        schema_lines = "\n".join(f"  - {k}: {desc}" for k, desc in state["param_schema"].items())
        prompt = (
            f"[추출 스키마]\n{schema_lines}\n\n"
            f"[사용자 요청]\n{state['user_input']}\n\n"
            "위 요청에서 파라미터를 추출하여 JSON으로만 응답하세요."
        )
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        try:
            params = json.loads(_strip_fences(response.content))
        except:
            params = {}
        
        logger.info("[PARAMETERIZER] 추출 완료: %s", params)
        return {"params": params, "status": "parameterized"}

    # ── Node 2: Builder ──────────────────────────────────────────
    async def builder_node(state: AutomationState) -> Dict[str, Any]:
        """템플릿을 구체적인 실행 단계(Group 리스트)로 변환합니다."""
        logger.info("[BUILDER] 실행 계획 수립 중...")
        
        final_steps: List[List[Dict[str, Any]]] = []
        for item in state["step_templates"]:
            if isinstance(item, list):
                # 명시적 병렬 그룹
                group = [{"tool": s["tool"], "args": _fill_template(s.get("args", {}), state["params"])} for s in item]
                final_steps.append(group)
            else:
                # 단일 단계를 단일 원소 그룹으로 변환
                step = {"tool": item["tool"], "args": _fill_template(item.get("args", {}), state["params"])}
                final_steps.append([step])

        logger.info("[BUILDER] 총 %d 개의 그룹 확정 (병렬 단계 포함)", len(final_steps))
        return {"steps": final_steps, "current_step": 0, "history": [], "status": "built"}

    # ── Node 3: Executor ─────────────────────────────────────────
    async def executor_node(state: AutomationState) -> Dict[str, Any]:
        """현재 그룹의 모든 도구를 asyncio.gather 로 병렬 실행합니다."""
        idx = state["current_step"]
        group = state["steps"][idx]
        
        logger.info("[EXECUTOR] Group %d/%d 실행 (도구 %d개 병렬)", 
                    idx + 1, len(state["steps"]), len(group))

        async def _call(step_info: Dict[str, Any]) -> Dict[str, Any]:
            name, args = step_info["tool"], step_info.get("args", {})
            try:
                res = await mcp.call_tool(name, args)
                return {"tool": name, "result": res}
            except Exception as e:
                return {"tool": name, "error": str(e)}

        # 병렬 실행!
        results = await asyncio.gather(*[_call(s) for s in group])
        
        # 결과 분석 (하나라도 에러가 있으면 실패 처리)
        has_error = any("error" in r for r in results)
        new_history = state["history"] + [{"group": idx + 1, "results": results}]
        
        if has_error:
            logger.error("[EXECUTOR] Group %d 작업 중 오류 발생", idx + 1)
            return {"history": new_history, "current_step": len(state["steps"]), "status": "failed"}
        
        return {"history": new_history, "current_step": idx + 1, "status": "in_progress"}

    # ── Graph Setup ──────────────────────────────────────────────
    def _should_continue(state: AutomationState) -> str:
        return "continue" if state["current_step"] < len(state["steps"]) else "end"

    graph = StateGraph(AutomationState)
    graph.add_node("parameterizer", parameterizer_node)
    graph.add_node("builder",       builder_node)
    graph.add_node("executor",      executor_node)
    graph.set_entry_point("parameterizer")
    graph.add_edge("parameterizer", "builder")
    graph.add_edge("builder",       "executor")
    graph.add_conditional_edges("executor", _should_continue, {"continue": "executor", "end": END})
    
    return graph.compile()


# ─────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────
async def run_automation(
    *,
    user_input: str,
    param_schema: Dict[str, str],
    step_templates: List[Union[Dict[str, Any], List[Dict[str, Any]]]],
    llm: AsyncChatOpenAI,
    mcp: MCPClient,
) -> AutomationState:
    app = build_automation_graph(llm, mcp)
    initial: AutomationState = {
        "user_input": user_input, "param_schema": param_schema, "step_templates": step_templates,
        "params": {}, "steps": [], "current_step": 0, "history": [], "status": "start",
    }
    
    final: AutomationState = {} # type: ignore
    async for event in app.astream(initial):
        for _, values in event.items():
            final = {**final, **values}

    logger.info("■ 자동화 최종 상태: %s", final.get("status"))
    return final


# ─────────────────────────────────────────────────────────────────
# Example
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    _llm = AsyncChatOpenAI(api_key=os.environ["OPENAI_API_KEY"], model="gpt-4o-mini")
    _mcp = MCPClient()

    # 예시: 메모장과 계산기를 '동시'에 띄움 (병렬)
    _schema = {"msg": "메모장에 적을 내용"}
    _templates = [
        # Group 1: 병렬 실행
        [
            {"tool": "launch_application", "args": {"executable_path": "notepad.exe"}},
            {"tool": "launch_application", "args": {"executable_path": "calc.exe"}},
        ],
        # Group 2: 순차 실행 (앞의 그룹이 다 끝나야 실행됨)
        {"tool": "type_app_text", "args": {"text": "{msg}"}},
    ]

    asyncio.run(run_automation(
        user_input="메모장이랑 계산기 켜고 메모장에 'Hello'라고 적어줘",
        param_schema=_schema,
        step_templates=_templates,
        llm=_llm,
        mcp=_mcp
    ))
