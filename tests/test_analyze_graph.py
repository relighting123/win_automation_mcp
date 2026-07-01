import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.state import AgentState, ToolCall
from graph.nodes import GraphNodes, UserInterrupt
from core.automation_run_control import begin_run_control, end_run_control


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

    async def test_manual_without_skill_ids_falls_back_to_auto_plan(self) -> None:
        state = AgentState(query="demo run", skill_ids=[], mode="manual")
        with patch.object(
            self.nodes,
            "_get_skills_config",
            return_value={"demo_skill": {"description": "demo", "tools": [{"tool": "wait"}]}},
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
        with patch.object(self.nodes, "_get_skills_config", return_value={"demo_skill": {"tools": [{"tool": "wait"}]}}):
            with patch.object(self.nodes, "_map_skill_id", new=AsyncMock(return_value="")):
                result = await self.nodes.plan(state)
        self.assertTrue(result["execution_halted"])
        self.assertEqual(result["skill_ids"], [])

    async def test_manual_with_skill_ids_uses_provided_skills_not_ai_plan(self) -> None:
        state = AgentState(query="demo run", skill_ids=["demo_skill"], mode="manual")
        with patch.object(
            self.nodes,
            "_get_skills_config",
            return_value={"demo_skill": {"tools": [{"tool": "wait"}]}},
        ):
            with patch.object(
                self.nodes,
                "_plan_skills_auto",
                new=AsyncMock(return_value={"skill_ids": ["other_skill"]}),
            ) as auto_plan:
                with patch.object(
                    self.nodes,
                    "_map_skill_id",
                    new=AsyncMock(return_value="demo_skill"),
                ):
                    result = await self.nodes.plan(state)
        auto_plan.assert_not_awaited()
        self.assertEqual(result["skill_ids"], ["demo_skill"])

    async def test_map_skill_id_ignores_unknown_query_text(self) -> None:
        with patch.object(self.nodes, "_get_skills_config", return_value={"demo_skill": {}}):
            mapped = await self.nodes._map_skill_id("분석해줘", {"demo_skill": {}})
        self.assertEqual(mapped, "")

    async def test_runnable_skill_ids_require_tools(self) -> None:
        skills = {
            "empty_skill": {"description": "no tools"},
            "demo_skill": {"tools": [{"tool": "wait"}]},
        }
        self.assertEqual(self.nodes._get_runnable_skill_ids(skills), ["demo_skill"])

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


class AnalyzeGraphInteractiveControlTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.nodes = GraphNodes(mcp=MagicMock(), execution_llm=MagicMock())
        self.control = begin_run_control("semi")

    def tearDown(self) -> None:
        end_run_control()

    async def test_run_stops_when_user_requests_stop(self) -> None:
        state = AgentState(
            query="demo",
            skill_ids=["demo_skill"],
            mode="semi",
            enriched_plan=[
                ToolCall(tool="wait", args={"seconds": 0.01}),
                ToolCall(tool="wait", args={"seconds": 0.01}),
            ],
        )
        self.control.request_stop()
        result = await self.nodes.run(state)
        self.assertTrue(result["execution_halted"])
        self.assertIn("중지", result["halt_reason"])

    async def test_run_skips_remaining_steps_on_user_skip(self) -> None:
        self.nodes.mcp.call_tool = AsyncMock(return_value={"success": True})
        state = AgentState(
            query="demo",
            skill_ids=["demo_skill"],
            mode="manual",
            enriched_plan=[
                ToolCall(tool="wait", args={"seconds": 0.01}),
                ToolCall(tool="wait", args={"seconds": 0.01}),
            ],
        )
        self.control.request_skip_skill()
        result = await self.nodes.run(state)
        self.assertFalse(result["execution_halted"])
        self.nodes.mcp.call_tool.assert_not_awaited()
        self.assertTrue(any(item.get("tool") == "__user_skip__" for item in result["history"]))

    async def test_run_interrupts_long_running_tool_on_stop(self) -> None:
        """도구 실행 도중 중지를 누르면 즉시 중단되어야 한다 (단계 경계 대기 X)."""
        started = asyncio.Event()

        async def slow_tool(tool, args):
            started.set()
            await asyncio.sleep(10)
            return {"success": True}

        self.nodes.mcp.call_tool = slow_tool
        state = AgentState(
            query="demo",
            skill_ids=["demo_skill"],
            mode="semi",
            enriched_plan=[ToolCall(tool="wait", args={"seconds": 10})],
        )

        async def trigger_stop():
            await started.wait()
            self.control.request_stop()

        asyncio.create_task(trigger_stop())
        result = await asyncio.wait_for(self.nodes.run(state), timeout=3)
        self.assertTrue(result["execution_halted"])
        self.assertIn("중지", result["halt_reason"])

    async def test_manual_check_situation_honors_user_skip(self) -> None:
        state = AgentState(
            query="demo",
            skill_ids=["demo_skill"],
            mode="manual",
            current_index=0,
        )
        self.control.request_skip_skill()
        result = await self.nodes.check_situation(state)
        self.assertEqual(result["next_action"], "skip")

    async def test_plan_stops_when_user_requests_stop(self) -> None:
        state = AgentState(query="demo", skill_ids=[], mode="auto")
        self.control.request_stop()
        result = await self.nodes.plan(state)
        self.assertTrue(result["execution_halted"])
        self.assertEqual(result["skill_ids"], [])
        self.assertIn("중지", result["halt_reason"])

    async def test_auto_mode_run_honors_pause_gate(self) -> None:
        control = begin_run_control("auto")
        try:
            state = AgentState(
                query="demo",
                skill_ids=["demo_skill"],
                mode="auto",
                enriched_plan=[ToolCall(tool="wait", args={"seconds": 0.01})],
            )
            control.request_stop()
            result = await self.nodes.run(state)
            self.assertTrue(result["execution_halted"])
        finally:
            end_run_control()


if __name__ == "__main__":
    unittest.main()
