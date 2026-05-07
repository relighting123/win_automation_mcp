import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from core.state import AgentState, SituationAnalysis
from graph.nodes import GraphNodes

@pytest.mark.asyncio
async def test_next_node():
    # Mock dependencies
    mcp = MagicMock()
    llm = MagicMock()
    nodes = GraphNodes(mcp, llm)
    
    state = AgentState(query="test", skill_ids=["skill1", "skill2"], current_index=0)
    result = await nodes.next(state)
    
    assert result["current_index"] == 1

@pytest.mark.asyncio
async def test_manual_mode_check_situation():
    mcp = MagicMock()
    mcp.call_tool = AsyncMock()
    llm = MagicMock()
    nodes = GraphNodes(mcp, llm)
    
    state = AgentState(query="test", skill_ids=["skill1"], mode="manual", current_index=0)
    result = await nodes.check_situation(state)
    
    assert result["check_status"] == "manual_bypass"
    assert result["next_action"] == "proceed"
    mcp.call_tool.assert_not_called()
    llm.with_structured_output.assert_not_called()

@pytest.mark.asyncio
async def test_check_situation_skip_when_already_done():
    mcp = MagicMock()
    mcp.call_tool = AsyncMock(return_value={"screen": "already_logged_in"})
    llm = MagicMock()
    structured_llm = MagicMock()
    structured_llm.ainvoke = AsyncMock(
        return_value=SituationAnalysis(
            category="normal",
            reason="이미 로그인된 상태라 해당 스킬은 건너뜁니다.",
            next_action="skip",
        )
    )
    llm.with_structured_output.return_value = structured_llm
    nodes = GraphNodes(mcp, llm)

    state = AgentState(query="test", skill_ids=["login_skill"], mode="semi", current_index=0)
    result = await nodes.check_situation(state)

    assert result["next_action"] == "skip"
    assert result["history"][-1]["output"]["status"] == "skipped"
    assert "이미 로그인" in result["history"][-1]["output"]["reason"]
    mcp.call_tool.assert_awaited_once()

@pytest.mark.asyncio
async def test_check_situation_insert_recovery_skill():
    mcp = MagicMock()
    mcp.call_tool = AsyncMock(return_value={"screen": "login_required"})
    llm = MagicMock()
    structured_llm = MagicMock()
    structured_llm.ainvoke = AsyncMock(
        return_value=SituationAnalysis(
            category="login_required",
            reason="세션 만료로 재로그인이 필요합니다.",
            next_action="insert_recovery",
            recovery_skill_id="login_skill",
        )
    )
    llm.with_structured_output.return_value = structured_llm
    nodes = GraphNodes(mcp, llm)

    state = AgentState(
        query="feature 실행",
        skill_ids=["launch_app", "open_feature"],
        mode="semi",
        current_index=1,
    )
    result = await nodes.check_situation(state)

    assert result["next_action"] == "insert_recovery"
    assert result["extra_skill"] == "login_skill"
    assert result["skill_ids"] == ["launch_app", "login_skill", "open_feature"]

if __name__ == "__main__":
    # 간단한 직접 실행 테스트
    async def run_manual_test():
        print("Running manual logic tests...")
        await test_next_node()
        await test_manual_mode_check_situation()
        print("All tests passed!")
        
    asyncio.run(run_manual_test())
