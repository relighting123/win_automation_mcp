"""
automation_graph.py
────────────────────────────────────────────────────────────────────
정의된 plan 순서대로 MCP tool을 호출하는 최소 LangGraph 실행기.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, TypedDict

from langgraph.graph import END, StateGraph

from mcp_client import MCPClient

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────
class AutomationState(TypedDict):
    """LangGraph 노드 간에 공유되는 순차 실행 상태."""
    plan_source: str
    plan_steps: List[Dict[str, Any]]
    current_step: int
    history: List[Dict[str, Any]]
    status: str
    final_response: str


# ─────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────
def _normalize_plan_steps(raw_steps: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_steps, list):
        raise ValueError("plan은 JSON 리스트여야 합니다.")

    normalized: List[Dict[str, Any]] = []
    for idx, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            raise ValueError(f"{idx + 1}번째 step은 object(dict)여야 합니다.")
        tool = step.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            raise ValueError(f"{idx + 1}번째 step의 tool 값이 유효하지 않습니다.")
        args = step.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ValueError(f"{idx + 1}번째 step의 args는 dict여야 합니다.")
        normalized.append({"tool": tool.strip(), "args": args})

    return normalized


def load_plan_steps_from_json(plan_path: str) -> List[Dict[str, Any]]:
    """
    JSON plan 파일에서 step 리스트를 읽습니다.

    지원 형식:
    1) 배열 루트
       [
         {"tool": "...", "args": {...}}
       ]
    2) 객체 루트
       {"steps": [{"tool": "...", "args": {...}}]}
    """
    path = Path(plan_path)
    loaded = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(loaded, dict):
        raw_steps = loaded.get("steps", [])
    else:
        raw_steps = loaded
    return _normalize_plan_steps(raw_steps)


# ─────────────────────────────────────────────────────────────────
# Graph Factory
# ─────────────────────────────────────────────────────────────────
def build_automation_graph(mcp: MCPClient) -> Any:
    """plan_steps를 순서대로 실행하는 LangGraph."""

    def planner_node(state: AutomationState) -> Dict[str, Any]:
        steps = state.get("plan_steps", []) or []
        if not steps:
            return {
                "status": "invalid_plan",
                "current_step": 0,
                "history": [],
                "final_response": "실행할 plan_steps가 없습니다.",
            }
        return {
            "status": "ready",
            "current_step": 0,
            "history": [],
        }

    async def executor_node(state: AutomationState) -> Dict[str, Any]:
        idx = state["current_step"]
        step = state["plan_steps"][idx]
        name = step["tool"]
        args = step.get("args", {})

        try:
            res = await mcp.call_tool(name, args)
            entry = {
                "step": idx + 1,
                "tool": name,
                "args": args,
                "status": "ok",
                "result": res,
            }
        except Exception as exc:
            entry = {
                "step": idx + 1,
                "tool": name,
                "args": args,
                "status": "error",
                "error": str(exc),
            }

        return {
            "history": state["history"] + [entry],
            "current_step": idx + 1,
            "status": "running",
        }

    def finalizer_node(state: AutomationState) -> Dict[str, Any]:
        if state.get("status") == "invalid_plan":
            return {
                "status": "invalid_plan",
                "final_response": state.get("final_response", "유효한 plan_steps가 없습니다."),
            }

        history = state.get("history", [])
        success_count = sum(1 for h in history if h.get("status") == "ok")
        fail_count = len(history) - success_count
        summary = {
            "plan_source": state.get("plan_source", ""),
            "requested_steps": len(state.get("plan_steps", [])),
            "executed_steps": len(history),
            "success": success_count,
            "failed": fail_count,
            "history": history,
        }
        return {
            "status": "completed",
            "final_response": json.dumps(summary, ensure_ascii=False, indent=2),
        }

    # ── Graph Building ──────────────────────────────────────────
    workflow = StateGraph(AutomationState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("finalizer", finalizer_node)

    workflow.set_entry_point("planner")

    def _plan_ready(state: AutomationState) -> str:
        if state.get("status") == "ready":
            return "execute"
        return "end"

    workflow.add_conditional_edges(
        "planner",
        _plan_ready,
        {"execute": "executor", "end": "finalizer"},
    )

    def _cont(state: AutomationState) -> str:
        return "continue" if state["current_step"] < len(state["plan_steps"]) else "end"

    workflow.add_conditional_edges("executor", _cont, {"continue": "executor", "end": "finalizer"})
    workflow.add_edge("finalizer", END)
    return workflow.compile()


# ─────────────────────────────────────────────────────────────────
# Runner & Example
# ─────────────────────────────────────────────────────────────────
async def run_automation(
    *,
    plan_steps: List[Dict[str, Any]],
    mcp: MCPClient,
    plan_source: str = "inline",
) -> AutomationState:
    app = build_automation_graph(mcp)
    initial: AutomationState = {
        "plan_source": plan_source,
        "plan_steps": plan_steps,
        "current_step": 0,
        "history": [],
        "status": "start",
        "final_response": "",
    }

    final: AutomationState = {}  # type: ignore
    async for event in app.astream(initial):
        for _, values in event.items():
            final = {**final, **values}

    return final


async def run_automation_from_plan_json(
    *,
    plan_path: str,
    mcp: MCPClient,
) -> AutomationState:
    """JSON plan 파일을 읽어 순차 자동화를 실행합니다."""
    steps = load_plan_steps_from_json(plan_path)
    return await run_automation(
        plan_steps=steps,
        mcp=mcp,
        plan_source=plan_path,
    )


if __name__ == "__main__":
    import os

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    _mcp = MCPClient(base_url=os.getenv("MCP_BASE_URL", "http://localhost:8000/mcp"))
    _plan_path = os.getenv("AUTOMATION_PLAN_JSON", "plans/sample_plan.json")
    result = asyncio.run(run_automation_from_plan_json(plan_path=_plan_path, mcp=_mcp))
    print(result.get("final_response", ""))
