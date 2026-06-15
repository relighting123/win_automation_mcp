import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.state import AgentState
from graph.nodes import GraphNodes


class AnalyzeGraphPlanTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.nodes = GraphNodes(mcp=MagicMock(), execution_llm=MagicMock())

    async def test_semi_without_skill_ids_falls_back_to_auto_plan(self) -> None:
        state = AgentState(query="demo run", skill_ids=[], mode="semi")
        with patch.object(
            self.nodes,
            "_get_skills_config",
            return_value={"demo_skill": {"description": "demo"}},
        ):
            with patch.object(
                self.nodes,
                "_plan_skills_auto",
                new=AsyncMock(return_value={"skill_ids": ["demo_skill"]}),
            ) as auto_plan:
                result = await self.nodes.plan(state)
        auto_plan.assert_awaited_once()
        self.assertEqual(result["skill_ids"], ["demo_skill"])

    async def test_manual_with_unknown_skill_halts(self) -> None:
        state = AgentState(query="run", skill_ids=["missing_skill"], mode="manual")
        with patch.object(self.nodes, "_get_skills_config", return_value={"demo_skill": {}}):
            with patch.object(self.nodes, "_map_skill_id", new=AsyncMock(return_value="")):
                result = await self.nodes.plan(state)
        self.assertTrue(result["execution_halted"])
        self.assertEqual(result["skill_ids"], [])

    async def test_check_situation_skips_when_no_skills(self) -> None:
        state = AgentState(
            query="run",
            skill_ids=[],
            mode="semi",
            execution_halted=True,
            halt_reason="no skills",
        )
        result = await self.nodes.check_situation(state)
        self.assertEqual(result["next_action"], "abort")
        self.assertTrue(result["execution_halted"])


if __name__ == "__main__":
    unittest.main()
