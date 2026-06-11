import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from graph import langchain_compat  # noqa: F401  # apply LangChain load() defaults early
from langgraph.graph import StateGraph, END
from core.state import AgentState
from graph.nodes import GraphNodes

def build_automation_graph(mcp, execution_llm, planner_llm=None, analyst_llm=None, reporter_llm=None):
    """
    StateGraph를 생성하고 노드 및 엣지를 구성합니다.
    """
    nodes = GraphNodes(
        mcp=mcp,
        execution_llm=execution_llm,
        planner_llm=planner_llm,
        analyst_llm=analyst_llm,
        reporter_llm=reporter_llm,
    )
    builder = StateGraph(AgentState)
    
    # 노드 추가
    builder.add_node("plan", nodes.plan)
    builder.add_node("check_situation", nodes.check_situation)
    builder.add_node("extract", nodes.extract)
    builder.add_node("run", nodes.run)
    builder.add_node("next", nodes.next)
    builder.add_node("report", nodes.report)
    
    # 기본 흐름 정의
    builder.set_entry_point("plan")
    builder.add_edge("plan", "check_situation")
    builder.add_conditional_edges(
        "check_situation",
        lambda x: (
            "extract"
            if x.next_action in {"proceed", "insert_recovery"}
            else ("next" if x.next_action == "skip" else "report")
        ),
    )
    builder.add_edge("extract", "run")
    builder.add_edge("run", "next")
    
    # 조건부 엣지: 남은 스킬 여부 확인
    builder.add_conditional_edges(
        "next",
        lambda x: "check_situation" if x.current_index < len(x.skill_ids) else "report"
    )
    builder.add_edge("report", END)
    
    return builder.compile()
