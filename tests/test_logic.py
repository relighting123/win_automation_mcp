import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from core.state import AgentState
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
    llm = MagicMock()
    nodes = GraphNodes(mcp, llm)
    
    state = AgentState(query="test", skill_ids=["skill1"], mode="manual", current_index=0)
    result = await nodes.check_situation(state)
    
    assert result["check_status"] == "manual_bypass"

if __name__ == "__main__":
    # 간단한 직접 실행 테스트
    async def run_manual_test():
        print("Running manual logic tests...")
        await test_next_node()
        await test_manual_mode_check_situation()
        print("All tests passed!")
        
    asyncio.run(run_manual_test())
