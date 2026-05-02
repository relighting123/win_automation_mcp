import json
import logging
import yaml
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from core.state import AgentState, ToolCall, ToolCalls, SituationAnalysis
from graph.prompts import PLANNER_SYSTEM_PROMPT, ANALYST_SYSTEM_PROMPT, EXTRACTOR_SYSTEM_PROMPT, MODE_INSTRUCTIONS
from skills.sequence_skill import SequenceSkill

logger = logging.getLogger(__name__)

class GraphNodes:
    def __init__(self, mcp, llm):
        self.mcp = mcp
        self.llm = llm

    async def plan(self, state: AgentState):
        """[auto] 모드일 경우 전체 실행 계획(Skill Sequence)을 AI가 자율적으로 수립"""
        if state.mode != "auto":
            logger.info(f"[{state.mode} 모드] 기존 스킬 리스트를 사용합니다.")
            return {"skill_ids": state.skill_ids}

        logger.info("--- [auto 모드] AI 스킬 계획 시작 ---")
        
        try:
            with open("config/skills.yaml", "r", encoding="utf-8") as f:
                skills_config = yaml.safe_load(f).get("skills", {})
            skills_info = "\n".join([f"- {sid}: {info.get('description', '')}" for sid, info in skills_config.items()])
        except Exception as e:
            logger.error(f"스킬 설정 로드 실패: {e}")
            return {"skill_ids": state.skill_ids}

        class SkillPlan(BaseModel):
            skill_ids: List[str] = Field(description="실행할 스킬 ID 리스트 (순서대로)")

        structured_llm = self.llm.with_structured_output(SkillPlan)
        plan = await structured_llm.ainvoke([
            ("system", PLANNER_SYSTEM_PROMPT),
            ("user", f"질의: {state.query}\n\n사용 가능한 스킬 목록:\n{skills_info}")
        ])
        
        logger.info(f"AI 계획 결과: {plan.skill_ids}")
        return {"skill_ids": plan.skill_ids}

    async def check_situation(self, state: AgentState):
        """현재 화면 상태를 분석하여 스킬 실행 가능 여부 체크"""
        current_skill_id = state.skill_ids[state.current_index]
        logger.info(f"--- 상황 체크 시작: {current_skill_id} (Index: {state.current_index}) ---")
        
        if state.mode == "manual":
            logger.info("[manual 모드] 상황 체크를 건너뛰고 진행합니다.")
            return {"check_status": "manual_bypass"}

        state_info = await self.mcp.call_tool("describe_current_state", {"include_components": False})
        
        prompt = (
            f"현재 화면 상태: {state_info}\n"
            f"실행할 스킬 ID: {current_skill_id}\n"
        )
        
        structured_llm = self.llm.with_structured_output(SituationAnalysis)
        analysis = await structured_llm.ainvoke([
            ("system", ANALYST_SYSTEM_PROMPT),
            ("user", prompt)
        ])
        
        logger.info(f"상황 분석 결과: {analysis.category} ({analysis.reason})")
        
        new_skill_ids = list(state.skill_ids)
        fallback_skill = ""
        
        if state.mode != "manual" and analysis.recovery_skill_id and analysis.recovery_skill_id != current_skill_id:
            logger.info(f"복구 스킬 감지: {analysis.recovery_skill_id} 삽입")
            new_skill_ids.insert(state.current_index, analysis.recovery_skill_id)
            fallback_skill = analysis.recovery_skill_id
        
        return {
            "check_status": analysis.reason, 
            "extra_skill": fallback_skill,
            "skill_ids": new_skill_ids
        }

    async def extract(self, state: AgentState):
        """현재 인덱스의 Skill ID를 기반으로 도구 순서를 로드하고 파라미터 추출"""
        current_skill_id = state.skill_ids[state.current_index]
        
        skill = SequenceSkill(skill_name=current_skill_id)
        steps_metadata = skill.get_steps_with_metadata(state.model_dump())
        tool_sequence = [step["tool"] for step in steps_metadata]
        
        if not tool_sequence:
            logger.error(f"Skill '{current_skill_id}'에 유효한 도구가 없습니다.")
            raise ValueError(f"Skill '{current_skill_id}'에 유효한 도구가 없습니다.")

        mode_instruction = MODE_INSTRUCTIONS.get(state.mode, MODE_INSTRUCTIONS["semi"])
        
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", f"{EXTRACTOR_SYSTEM_PROMPT}\n\n{mode_instruction}"),
            ("user", (
                "질의: {query}\n"
                "현재 상황: {check_status}\n"
                "현재 스킬({skill_id})의 도구 순서 및 인자 제약: {tool_constraints}\n"
                "사용 가능한 도구 정보:\n{tools_info}"
            ))
        ])

        structured_llm = self.llm.with_structured_output(ToolCalls, method="function_calling", strict=False)
        
        all_tools = await self.mcp.list_tools()
        skill_tools = [t for t in all_tools if t['name'] in tool_sequence]
        tools_info = json.dumps(skill_tools, indent=2, ensure_ascii=False)
        
        chain = prompt_template | structured_llm
        enriched = await chain.ainvoke({
            "query": state.query,
            "check_status": state.check_status,
            "skill_id": current_skill_id,
            "tool_constraints": json.dumps(steps_metadata, indent=2, ensure_ascii=False),
            "tools_info": tools_info
        })
        
        # [Post-process] Fixed 값 강제 적용 및 AI 값 유지
        final_calls = []
        for i, call in enumerate(enriched.calls):
            # 도구 순서에 맞춰 메타데이터 적용 (수동/준자동 모드 대응)
            matching_step = next((s for s in steps_metadata if s["tool"] == call.tool), None)
            if matching_step:
                new_args = dict(call.args)
                for arg_name, arg_meta in matching_step["args"].items():
                    if arg_meta["mode"] == "fixed":
                        new_args[arg_name] = arg_meta["value"]
                call.args = new_args
            final_calls.append(call)
            
        valid_calls = [call for call in final_calls if call.tool in tool_sequence]
        if len(valid_calls) < len(enriched.calls):
            removed = [call.tool for call in enriched.calls if call.tool not in tool_sequence]
            logger.warning(f"스킬 '{current_skill_id}'에 정의되지 않은 도구 호출이 제외되었습니다: {removed}")

        return {"enriched_plan": valid_calls, "tool_sequence": tool_sequence}

    async def run(self, state: AgentState):
        """추출된 파라미터로 MCP 도구 순차 실행"""
        results = list(state.history)
        current_skill_id = state.skill_ids[state.current_index]
        
        for call in state.enriched_plan:
            logger.info(f"[Run] {call.tool} 실행 중... (Args: {call.args})")
            out = await self.mcp.call_tool(call.tool, call.args)
            results.append({
                "skill": current_skill_id,
                "tool": call.tool, 
                "output": out
            })
        return {"history": results}

    async def next(self, state: AgentState):
        """다음 스킬로 인덱스 이동"""
        return {"current_index": state.current_index + 1}

    async def report(self, state: AgentState):
        """최종 결과를 자연어로 해석"""
        prompt = f"요청: {state.query}\n결과: {state.history}\n결과를 요약해서 보고하세요."
        res = await self.llm.ainvoke(prompt)
        return {"report": res.content}
