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

    def _load_step_definitions(self, skill_id: str) -> List[Dict[str, Any]]:
        """스킬 YAML을 로드해 단계별 도구/기본 args/arg_policy를 반환"""
        skill = SequenceSkill(skill_name=skill_id)
        return skill.get_step_definitions()

    def _format_arg_policy_constraints(self, step_definitions: List[Dict[str, Any]]) -> str:
        """LLM 프롬프트에 주입할 고정 인자 제약 설명을 구성"""
        constraints: List[str] = []
        for idx, step in enumerate(step_definitions):
            fixed_arg_values = {
                arg_name: step.get("args", {}).get(arg_name)
                for arg_name, is_mutable in (step.get("arg_policy") or {}).items()
                if is_mutable is False
            }
            if fixed_arg_values:
                constraints.append(
                    f"- step {idx + 1} ({step['tool']}): "
                    f"고정 인자 = {json.dumps(fixed_arg_values, ensure_ascii=False)}"
                )
        return "\n".join(constraints) if constraints else "- 고정 인자 제약 없음"

    def _merge_tool_args_with_policy(
        self,
        extracted_args: Dict[str, Any],
        step_definition: Optional[Dict[str, Any]],
        tool_name: str,
    ) -> Dict[str, Any]:
        """LLM 추출 인자와 YAML 기본값을 arg_policy 기반으로 병합"""
        if not step_definition:
            return dict(extracted_args or {})

        merged_args = dict(step_definition.get("args") or {})
        arg_policy = step_definition.get("arg_policy") or {}

        for arg_name, arg_value in (extracted_args or {}).items():
            is_mutable = arg_policy.get(arg_name, True)
            if not is_mutable:
                logger.info(
                    "[ArgPolicy] %s.%s 는 고정 인자여서 LLM 추출값을 무시합니다. (요청값=%r, 고정값=%r)",
                    tool_name,
                    arg_name,
                    arg_value,
                    merged_args.get(arg_name),
                )
                continue
            merged_args[arg_name] = arg_value

        return merged_args

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
        
        try:
            step_definitions = self._load_step_definitions(current_skill_id)
            tool_sequence = [step.get("tool") for step in step_definitions if step]
            if not tool_sequence:
                raise ValueError(f"Skill '{current_skill_id}'에 유효한 도구가 없습니다.")
        except Exception as e:
            logger.error(f"Skill 로드 실패: {e}")
            raise e

        mode_instruction = MODE_INSTRUCTIONS.get(state.mode, MODE_INSTRUCTIONS["semi"])
        
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", f"{EXTRACTOR_SYSTEM_PROMPT}\n\n{mode_instruction}"),
            ("user", "질의: {query}\n현재 상황: {check_status}\n현재 스킬({skill_id})의 도구 순서: {tool_sequence}\n현재 스킬의 step 기본값/arg_policy:\n{step_definitions}\n고정 인자 제약:\n{arg_policy_constraints}\n사용 가능한 도구 정보:\n{tools_info}")
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
            "tool_sequence": tool_sequence,
            "step_definitions": json.dumps(step_definitions, ensure_ascii=False),
            "arg_policy_constraints": self._format_arg_policy_constraints(step_definitions),
            "tools_info": tools_info
        })
        
        # [Strict Fix] LLM이 생성한 도구 중 현재 스킬에 정의되지 않은 도구는 강제 제외
        valid_calls = [call for call in enriched.calls if call.tool in tool_sequence]
        if len(valid_calls) < len(enriched.calls):
            removed = [call.tool for call in enriched.calls if call.tool not in tool_sequence]
            logger.warning(f"스킬 '{current_skill_id}'에 정의되지 않은 도구 호출이 제외되었습니다: {removed}")

        return {"enriched_plan": valid_calls, "tool_sequence": tool_sequence}

    async def run(self, state: AgentState):
        """추출된 파라미터로 MCP 도구 순차 실행"""
        results = list(state.history)
        current_skill_id = state.skill_ids[state.current_index]
        step_definitions = self._load_step_definitions(current_skill_id)
        step_defs_by_tool: Dict[str, List[Dict[str, Any]]] = {}
        for step in step_definitions:
            step_defs_by_tool.setdefault(step.get("tool"), []).append(step)
        step_usage_counter: Dict[str, int] = {}
        
        for call in state.enriched_plan:
            tool_name = call.tool
            tool_steps = step_defs_by_tool.get(tool_name, [])
            used_count = step_usage_counter.get(tool_name, 0)
            matched_step = tool_steps[used_count] if used_count < len(tool_steps) else None
            if matched_step is not None:
                step_usage_counter[tool_name] = used_count + 1

            effective_args = self._merge_tool_args_with_policy(call.args, matched_step, tool_name)
            logger.info(f"[Run] {tool_name} 실행 중... (Args: {effective_args})")
            out = await self.mcp.call_tool(tool_name, effective_args)
            results.append({
                "skill": current_skill_id,
                "tool": tool_name,
                "requested_args": call.args,
                "effective_args": effective_args,
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
