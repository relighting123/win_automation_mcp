from langgraph.graph import StateGraph, END
from core.state import AgentState
from graph.nodes import GraphNodes

def build_automation_graph(mcp, llm):
    """
    StateGraph를 생성하고 노드 및 엣지를 구성합니다.
    """
    nodes = GraphNodes(mcp, llm)
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
    builder.add_edge("check_situation", "extract")
    builder.add_edge("extract", "run")
    builder.add_edge("run", "next")
    
    # 조건부 엣지: 남은 스킬 여부 확인
    builder.add_conditional_edges(
        "next",
        lambda x: "check_situation" if x.current_index < len(x.skill_ids) else "report"
    )
    builder.add_edge("report", END)
    
    return builder.compile()
