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

    @staticmethod
    def _decode_tool_output(raw_output: Any) -> Any:
        """MCP tool 결과(dict/string)를 가능한 한 파싱 가능한 형태로 정규화합니다."""
        normalized = raw_output
        if isinstance(normalized, dict):
            content_blocks = normalized.get("content")
            if isinstance(content_blocks, list):
                text_blocks = [
                    block.get("text")
                    for block in content_blocks
                    if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
                ]
                if text_blocks:
                    normalized = text_blocks[0]

        if isinstance(normalized, str):
            stripped = normalized.strip()
            if stripped and stripped[0] in {"{", "["}:
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    return normalized
        return normalized

    @staticmethod
    def _is_failed_output(decoded_output: Any) -> bool:
        """도구 실행 결과가 실패인지 판정합니다."""
        if isinstance(decoded_output, dict):
            if decoded_output.get("success") is False:
                return True
            if decoded_output.get("is_success") is False:
                return True
            status = str(decoded_output.get("status", "")).lower()
            result = str(decoded_output.get("result", "")).lower()
            if status in {"error", "failed", "aborted", "timeout"}:
                return True
            if result in {"error", "failed", "timeout"}:
                return True
        return False

    def _collect_execution_summary(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """실행 이력에서 성공/실패/스킵 정보를 집계합니다."""
        failed_steps: List[Dict[str, Any]] = []
        skipped_steps = 0
        executed_steps = 0

        for entry in history:
            tool_name = str(entry.get("tool", ""))
            output = self._decode_tool_output(entry.get("output"))
            if tool_name == "__skill_gate__":
                if isinstance(output, dict) and str(output.get("status", "")).lower() == "skipped":
                    skipped_steps += 1
                if isinstance(output, dict) and str(output.get("status", "")).lower() == "aborted":
                    failed_steps.append(
                        {
                            "skill": entry.get("skill", ""),
                            "tool": tool_name,
                            "reason": output.get("reason") or output.get("message") or "aborted",
                        }
                    )
                continue

            executed_steps += 1
            if self._is_failed_output(output):
                reason = ""
                if isinstance(output, dict):
                    reason = (
                        str(output.get("message", "")).strip()
                        or str(output.get("error", "")).strip()
                        or str(output.get("reason", "")).strip()
                    )
                failed_steps.append(
                    {
                        "skill": entry.get("skill", ""),
                        "tool": tool_name,
                        "reason": reason or "tool execution failed",
                    }
                )

        return {
            "status": "failed" if failed_steps else "success",
            "executed_steps": executed_steps,
            "skipped_steps": skipped_steps,
            "failed_steps": failed_steps,
        }

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
            return {"check_status": "manual_bypass", "next_action": "proceed"}

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
        
        logger.info(
            "상황 분석 결과: category=%s, next_action=%s, reason=%s",
            analysis.category,
            analysis.next_action,
            analysis.reason,
        )
        allowed_actions = {"proceed", "skip", "insert_recovery", "abort"}
        next_action = analysis.next_action if analysis.next_action in allowed_actions else "proceed"
        if next_action != analysis.next_action:
            logger.warning("알 수 없는 next_action '%s' 감지, proceed로 대체", analysis.next_action)
        
        new_skill_ids = list(state.skill_ids)
        fallback_skill = ""
        history = list(state.history)
        
        if next_action == "insert_recovery":
            if analysis.recovery_skill_id and analysis.recovery_skill_id != current_skill_id:
                logger.info(f"복구 스킬 감지: {analysis.recovery_skill_id} 삽입")
                new_skill_ids.insert(state.current_index, analysis.recovery_skill_id)
                fallback_skill = analysis.recovery_skill_id
            else:
                logger.warning("insert_recovery가 요청되었지만 recovery_skill_id가 유효하지 않아 proceed로 대체합니다.")
                next_action = "proceed"

        if next_action == "skip":
            history.append(
                {
                    "skill": current_skill_id,
                    "tool": "__skill_gate__",
                    "output": {
                        "success": True,
                        "status": "skipped",
                        "reason": analysis.reason,
                    },
                }
            )

        if next_action == "abort":
            history.append(
                {
                    "skill": current_skill_id,
                    "tool": "__skill_gate__",
                    "output": {
                        "success": False,
                        "status": "aborted",
                        "reason": analysis.reason,
                    },
                }
            )
        
        return {
            "check_status": analysis.reason, 
            "next_action": next_action,
            "extra_skill": fallback_skill,
            "skill_ids": new_skill_ids,
            "history": history,
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
        """최종 결과를 자연어/구조화 형태로 보고"""
        history = list(state.history)
        execution_summary = self._collect_execution_summary(history)

        query_lower = state.query.lower()
        query_wants_clipboard = any(
            token in query_lower
            for token in ["ctrl+c", "ctrl c", "clipboard", "복사", "데이터프레임", "dataframe", "표"]
        )
        clipboard_entry = next((h for h in reversed(history) if h.get("tool") == "read_clipboard_as_dataframe"), None)

        clipboard_data: Dict[str, Any] = {
            "success": False,
            "message": "클립보드 분석이 수행되지 않았습니다.",
        }
        if clipboard_entry is not None:
            decoded_clipboard = self._decode_tool_output(clipboard_entry.get("output"))
            if isinstance(decoded_clipboard, dict):
                clipboard_data = decoded_clipboard
            else:
                clipboard_data = {
                    "success": False,
                    "message": "클립보드 도구 응답을 파싱하지 못했습니다.",
                    "raw": decoded_clipboard,
                }
        elif query_wants_clipboard:
            # read_clipboard_as_dataframe가 스킬에서 실행되지 않았더라도 report 단계에서 보조 조회
            live_clipboard = await self.mcp.call_tool("read_clipboard_as_dataframe", {})
            decoded_clipboard = self._decode_tool_output(live_clipboard)
            if isinstance(decoded_clipboard, dict):
                clipboard_data = decoded_clipboard
            else:
                clipboard_data = {
                    "success": False,
                    "message": "클립보드 응답 파싱 실패",
                    "raw": decoded_clipboard,
                }

        clipboard_analysis = ""
        if clipboard_data.get("success") is True:
            analysis_payload = {
                "shape": clipboard_data.get("shape", {}),
                "columns": clipboard_data.get("columns", []),
                "dtypes": clipboard_data.get("dtypes", {}),
                "preview_records": clipboard_data.get("preview_records", [])[:20],
            }
            analysis_prompt = (
                "당신은 표 데이터 분석가입니다. 아래 DataFrame 요약을 바탕으로 사용자 요청과 관련된 인사이트를 한국어로 작성하세요.\n"
                "응답 형식:\n"
                "1) 데이터 개요\n2) 핵심 인사이트\n3) 사용자가 바로 실행할 수 있는 다음 액션\n\n"
                f"[사용자 요청]\n{state.query}\n\n"
                f"[DataFrame 요약]\n{json.dumps(analysis_payload, ensure_ascii=False)}"
            )
            analysis_res = await self.llm.ainvoke(analysis_prompt)
            clipboard_analysis = analysis_res.content

        report_details = {
            "execution": execution_summary,
            "clipboard": clipboard_data,
            "clipboard_analysis": clipboard_analysis,
        }

        prompt = (
            f"요청: {state.query}\n"
            f"실행 요약: {json.dumps(execution_summary, ensure_ascii=False)}\n"
            f"클립보드 분석: {clipboard_analysis or clipboard_data.get('message', '없음')}\n"
            f"전체 실행 이력: {history}\n\n"
            "최종 답변은 한국어로 작성하세요. 반드시 '수행 여부'를 먼저 명시하고, "
            "그 다음 클립보드 데이터(DataFrame) 분석 결과를 자연스럽게 이어서 설명하세요."
        )
        res = await self.llm.ainvoke(prompt)
        return {"report": res.content, "report_details": report_details}
