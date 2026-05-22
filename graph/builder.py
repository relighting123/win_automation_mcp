from langgraph.graph import StateGraph, END
from core.state import AgentState
from graph.nodes import GraphNodes


def build_automation_graph(mcp, llm, task_llm=None):
    """
    StateGraph 를 생성하고 노드 및 엣지를 구성합니다.

    Args:
        mcp: MCP 클라이언트
        llm: reasoning LLM (계획/상황분석/리포트)
        task_llm: 단순 작업용 LLM (파라미터 추출, 스킬 매핑). None 이면 `llm` 을 공유.
    """
    nodes = GraphNodes(mcp, llm, task_llm=task_llm)
    builder = StateGraph(AgentState)

    builder.add_node("plan", nodes.plan)
    builder.add_node("check_situation", nodes.check_situation)
    builder.add_node("extract", nodes.extract)
    builder.add_node("run", nodes.run)
    builder.add_node("next", nodes.next)
    builder.add_node("report", nodes.report)

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

    builder.add_conditional_edges(
        "next",
        lambda x: "check_situation" if x.current_index < len(x.skill_ids) else "report"
    )
    builder.add_edge("report", END)

    return builder.compile()
