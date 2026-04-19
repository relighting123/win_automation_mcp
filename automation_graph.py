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
    steps: List[Dict[str, Any]]  # [{"tool": "...", "args": {...}}, ...]
    current_step_index: int
    history: List[Dict[str, Any]]
    status: str

mcp_client = MCPClient()

# Node: Executor - MCP Tool 호출
async def executor_node(state: AgentState):
    print(f"\n--- EXECUTOR (Step {state['current_step_index'] + 1}/{len(state['steps'])}) ---")
    
    current_step = state['steps'][state['current_step_index']]
    tool_name = current_step.get("tool")
    tool_args = current_step.get("args", {})
    
    print(f"Calling tool: {tool_name} with args: {tool_args}")
    
    try:
        # MCP 서버 연결 확인 및 도구 호출
        # MCPClient.call_tool은 동기 함수인 경우를 대비해 asyncio 루프 확인 필요
        # mcp_client.py 구현에 따라 다름. 여기서는 비동기 호출 가정.
        result = await mcp_client.call_tool(tool_name, tool_args)
        
        status_msg = f"Step {state['current_step_index'] + 1} 성공: {result}"
        print(status_msg)
        
        return {
            "history": state['history'] + [{"step": state['current_step_index'] + 1, "tool": tool_name, "result": result}],
            "current_step_index": state['current_step_index'] + 1,
            "status": "in_progress"
        }
    except Exception as e:
        error_msg = f"Step {state['current_step_index'] + 1} 실패 ({tool_name}): {e}"
        print(error_msg)
        return {
            "history": state['history'] + [{"step": state['current_step_index'] + 1, "tool": tool_name, "error": str(e)}],
            "current_step_index": len(state['steps']), # 에러 발생 시 종료
            "status": "failed"
        }

# 조건부 엣지: 모든 단계 완료 여부 확인
def should_continue(state: AgentState):
    if state['current_step_index'] < len(state['steps']):
        return "continue"
    return "end"

# Graph 구축
workflow = StateGraph(AgentState)

workflow.add_node("executor", executor_node)

workflow.set_entry_point("executor")

workflow.add_conditional_edges(
    "executor",
    should_continue,
    {
        "continue": "executor",
        "end": END
    }
)

app = workflow.compile()

async def run_automation(task: str, steps: List[Dict[str, Any]]):
    initial_state = {
        "task": task,
        "steps": steps,
        "current_step_index": 0,
        "history": [],
        "status": "start"
    }
    
    print(f"Starting automation for task: {task}")
    async for event in app.astream(initial_state):
        for kind, values in event.items():
            if 'status' in values and values['status'] == 'failed':
                print("Automation failed during execution.")
                break

if __name__ == "__main__":
    # 고정된 도구 호출 시퀀스 정의 예시
    my_task = "메모장을 열고 인사말 입력하기"
    my_steps = [
        {
            "tool": "launch_application", 
            "args": {"executable_path": "C:\\Windows\\System32\\notepad.exe"}
        },
        {
            "tool": "type_app_text",
            "args": {"text": "Hello from Deterministic LangGraph!\n"}
        },
        {
            "tool": "click_app_child_window",
            "args": {
                "title": "도움말",
                "auto_id": "buttonLogin",
                "control_type": "MenuItem",
                "draw_outline": True
            }
        },
        {
            "tool": "press_app_shortcut",
            "args": {"shortcut": "ctrl+s"}
        }
    ]
    
    asyncio.run(run_automation(my_task, my_steps))
