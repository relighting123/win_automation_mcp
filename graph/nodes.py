import asyncio
import json
import logging
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal, Union
from pydantic import BaseModel, Field, create_model
from langchain_core.prompts import ChatPromptTemplate
from core.state import AgentState, ToolCall, ToolCalls, SituationAnalysis
from graph.prompts import (
    PLANNER_SYSTEM_PROMPT, 
    ANALYST_SYSTEM_PROMPT, 
    EXTRACTOR_SYSTEM_PROMPT, 
    MODE_INSTRUCTIONS,
    ALLOWED_PATHS
)
from skills.sequence_skill import SequenceSkill

logger = logging.getLogger(__name__)

class GraphNodes:
    def __init__(self, mcp, llm):
        self.mcp = mcp
        self.llm = llm
        self._skills_cache: Optional[Dict[str, Any]] = None

    def _get_skills_config(self) -> Dict[str, Any]:
        """skills.yaml 및 skills/ 디렉토리에서 스킬 설정들을 로드합니다."""
        all_skills = {}
        
        # 1. Legacy skills.yaml 로드
        try:
            with open("config/skills.yaml", "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                all_skills.update(config.get("skills", {}))
        except Exception as e:
            logger.warning(f"Legacy skills.yaml 로드 실패: {e}")

        # 2. 개별 폴더 기반 스킬 로드 (skills/*/skill.yaml)
        try:
            skills_dir = Path("skills")
            for skill_folder in skills_dir.iterdir():
                if skill_folder.is_dir():
                    yaml_path = skill_folder / "skill.yaml"
                    if yaml_path.exists():
                        with open(yaml_path, "r", encoding="utf-8") as f:
                            skill_config = yaml.safe_load(f)
                            # 폴더명을 스킬 ID로 사용
                            all_skills[skill_folder.name] = skill_config
        except Exception as e:
            logger.error(f"디렉토리 기반 스킬 로드 중 오류: {e}")

        self._skills_cache = all_skills
        return all_skills

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        """실행 모드를 정규화합니다. (auto|semi|manual)"""
        normalized = (mode or "").strip().lower()
        if normalized in {"auto", "semi", "manual"}:
            return normalized
        logger.warning("알 수 없는 mode '%s' 감지, semi로 대체합니다.", mode)
        return "semi"

    async def _map_skill_id(self, skill_id: str, valid_skills: Dict[str, Any]) -> str:
        """스킬 ID를 결정론적으로 정규화합니다. (유사도/의미 매핑 없음)"""
        if not skill_id:
            return skill_id

        requested_skill_id = skill_id.strip()
        skill_id_lower = requested_skill_id.lower()
        valid_ids = list(valid_skills.keys())
        
        # 1. 완전 일치 확인 (Case-insensitive)
        exact_match = next((sid for sid in valid_ids if sid.lower() == skill_id_lower), None)
        if exact_match:
            return exact_match

        # 2. 정규화 일치 확인 (언더바/하이픈 차이 허용)
        def normalize(s):
            return s.lower().replace("_", "").replace("-", "").strip()
        
        norm_id = normalize(requested_skill_id)
        norm_match = next((sid for sid in valid_ids if normalize(sid) == norm_id), None)
        if norm_match:
            logger.info(f"스킬 ID 정규화 매핑: '{skill_id}' -> '{norm_match}'")
            return norm_match

        logger.warning("등록되지 않은 스킬 ID '%s'는 변경하지 않고 유지합니다.", requested_skill_id)
        return requested_skill_id

    def _create_structured_plan_model(self, valid_ids: List[str]):
        """유효한 스킬 ID만 선택하도록 강제하는 동적 Pydantic 모델 생성 (Latest LangGraph/LangChain Pattern)"""
        if not valid_ids:
            class DefaultSkillPlan(BaseModel):
                skill_ids: List[str] = Field(description="실행할 스킬 ID 리스트")
            return DefaultSkillPlan

        # Literal을 사용하여 LLM이 선택할 수 있는 범위를 제한
        SkillIdType = Literal[tuple(valid_ids)] # type: ignore
        
        return create_model(
            "SkillPlan",
            skill_ids=(List[SkillIdType], Field(description="실행할 스킬 ID 리스트 (반드시 제공된 목록 내에서만 선택)"))
        )

    def _create_structured_analysis_model(self, valid_ids: List[str]):
        """복구 스킬 ID를 유효한 목록 내에서 선택하도록 강제하는 동적 분석 모델 생성"""
        if not valid_ids:
            return SituationAnalysis

        SkillIdType = Optional[Literal[tuple(valid_ids)]] # type: ignore

        return create_model(
            "DynamicSituationAnalysis",
            __base__=SituationAnalysis,
            recovery_skill_id=(SkillIdType, Field(None, description="필요 시 자동 실행할 복구 스킬 ID (반드시 목록 내에서 선택)"))
        )

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

    @staticmethod
    def _is_retryable_llm_error(exc: Exception) -> bool:
        """504/게이트웨이/일시적 네트워크 오류 등 재시도 가능한 LLM 오류를 판정합니다."""
        message = str(exc).lower()
        retry_tokens = (
            "504",
            "502",
            "503",
            "gateway timeout",
            "timed out",
            "timeout",
            "service unavailable",
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
        )
        return any(token in message for token in retry_tokens)

    async def _ainvoke_with_retry(
        self,
        runnable: Any,
        payload: Any,
        *,
        timeout: float,
        max_attempts: int,
        op_name: str,
    ) -> Any:
        """LLM ainvoke를 timeout + exponential backoff 재시도로 실행합니다."""
        last_exc: Optional[Exception] = None
        for attempt in range(1, max(1, max_attempts) + 1):
            try:
                return await asyncio.wait_for(runnable.ainvoke(payload), timeout=timeout)
            except asyncio.TimeoutError as exc:
                last_exc = exc
                retryable = True
                reason = "timeout"
            except Exception as exc:
                last_exc = exc
                retryable = self._is_retryable_llm_error(exc)
                reason = str(exc)

            if attempt >= max_attempts or not retryable:
                break

            delay = min(6.0, 1.5 * (2 ** (attempt - 1)))
            logger.warning(
                "%s 실패(%s). %d/%d 재시도 전 %.1fs 대기",
                op_name,
                reason,
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

        if last_exc:
            raise last_exc
        raise RuntimeError(f"{op_name} 실패: 알 수 없는 LLM 호출 오류")

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
        skills_config = self._get_skills_config()
        valid_ids = list(skills_config.keys())
        resolved_mode = self._normalize_mode(state.mode)

        if resolved_mode != "auto":
            logger.info(f"[{resolved_mode} 모드] 기존 스킬 리스트 검증 시작")
            mapped_ids = []
            invalid_ids = []
            for sid in state.skill_ids:
                mapped = await self._map_skill_id(sid, skills_config)
                mapped_ids.append(mapped)
                if mapped not in skills_config:
                    invalid_ids.append(sid)

            if resolved_mode == "manual" and invalid_ids:
                raise ValueError(
                    f"[manual 모드] 등록되지 않은 스킬 ID가 포함되어 있습니다: {invalid_ids}. "
                    f"사용 가능한 스킬: {valid_ids}"
                )
            return {"mode": resolved_mode, "skill_ids": mapped_ids}

        logger.info("--- [auto 모드] AI 스킬 계획 시작 ---")
        
        if not valid_ids:
            logger.warning("사용 가능한 스킬이 정의되어 있지 않습니다.")
            return {"mode": resolved_mode, "skill_ids": []}

        skills_info = "\n".join([f"- {sid}: {info.get('description', '')}" for sid, info in skills_config.items()])

        # [최신 기법] Dynamic Literal을 사용한 Structured Output으로 Hallucination 방지
        SkillPlanModel = self._create_structured_plan_model(valid_ids)
        structured_llm = self.llm.with_structured_output(SkillPlanModel)
        
        try:
            plan = await self._ainvoke_with_retry(
                structured_llm,
                [
                    ("system", PLANNER_SYSTEM_PROMPT),
                    ("user", f"질의: {state.query}\n\n사용 가능한 스킬 목록:\n{skills_info}")
                ],
                timeout=45.0,
                max_attempts=3,
                op_name="plan.structured_llm",
            )
            
            # Pydantic 모델이 리스트를 반환하므로 .skill_ids 접근
            result_ids = getattr(plan, "skill_ids", [])
            logger.info(f"AI 계획 결과: {result_ids}")
            return {"mode": resolved_mode, "skill_ids": result_ids}
        except Exception as e:
            logger.error(f"계획 수립 중 오류 발생: {e}. 기본 매핑을 시도합니다.")
            # 실패 시 Fallback: 텍스트 기반으로 받고 수동 매핑
            try:
                raw_res = await self._ainvoke_with_retry(
                    self.llm,
                    f"질의: {state.query}\n목록: {valid_ids}\n적절한 스킬 ID들을 콤마로 구분해 답하세요.",
                    timeout=30.0,
                    max_attempts=2,
                    op_name="plan.fallback_llm",
                )
            except Exception as fallback_e:
                logger.error("Fallback 계획 수립도 실패했습니다: %s", fallback_e)
                return {"mode": resolved_mode, "skill_ids": []}
            potential_ids = [s.strip() for s in raw_res.content.split(",") if s.strip()]
            mapped_ids = []
            for pid in potential_ids:
                mapped = await self._map_skill_id(pid, skills_config)
                if mapped in skills_config and mapped not in mapped_ids:
                    mapped_ids.append(mapped)
            return {"mode": resolved_mode, "skill_ids": mapped_ids}

    async def check_situation(self, state: AgentState):
        """현재 화면 상태를 분석하여 스킬 실행 가능 여부 체크"""
        current_skill_id = state.skill_ids[state.current_index]
        resolved_mode = self._normalize_mode(state.mode)
        logger.info(f"--- 상황 체크 시작: {current_skill_id} (Index: {state.current_index}) ---")
        
        if resolved_mode == "manual":
            logger.info("[manual 모드] 상황 체크를 건너뛰고 진행합니다.")
            return {"mode": resolved_mode, "check_status": "manual_bypass", "next_action": "proceed"}

        # [개선] 소스 수정이나 에디트 관련 스킬은 앱이 실행 중일 필요가 없으므로 상황 체크(앱 실행 트리거)를 건너뜁니다.
        # 앱 실행 전에 설정을 바꿔야 하는 경우를 대비한 로직입니다.
        source_keywords = ["edit", "source", "config", "replace", "find_text"]
        if any(kw in current_skill_id.lower() for kw in source_keywords):
            logger.info(f"[Bypass] 스킬 '{current_skill_id}'은 소스/설정 관련 작업이므로 화면 체크를 건너뜁니다.")
            return {"check_status": "source_edit_bypass", "next_action": "proceed"}

        try:
            raw_state_info = await asyncio.wait_for(
                self.mcp.call_tool("describe_current_state", {"include_components": False}),
                timeout=25.0,
            )
        except asyncio.TimeoutError:
            logger.error("상황 체크용 describe_current_state 호출이 시간 초과되어 proceed로 진행합니다.")
            return {
                "mode": resolved_mode,
                "check_status": "state_check_timeout",
                "next_action": "proceed",
            }
        except Exception as e:
            logger.error("상황 체크용 describe_current_state 호출 실패: %s", e)
            return {
                "mode": resolved_mode,
                "check_status": f"state_check_error: {e}",
                "next_action": "proceed",
            }

        state_info = self._decode_tool_output(raw_state_info)
        if isinstance(state_info, dict):
            state_info = {
                "focus": state_info.get("focus"),
                "app": state_info.get("app"),
                "screen_flags": state_info.get("screen_flags"),
                "target_window": state_info.get("target_window"),
                "error": state_info.get("error"),
            }
        
        skills_config = self._get_skills_config()
        valid_ids = list(skills_config.keys())
        
        prompt = (
            f"현재 화면 상태: {state_info}\n"
            f"실행할 스킬 ID: {current_skill_id}\n"
            f"사용 가능한 복구용 스킬 목록: {valid_ids}\n"
        )
        
        # [최신 기법] 상황 분석에서도 유효한 스킬 ID만 제안하도록 동적 모델 적용
        DynamicAnalysisModel = self._create_structured_analysis_model(valid_ids)
        structured_llm = self.llm.with_structured_output(DynamicAnalysisModel)
        try:
            analysis = await self._ainvoke_with_retry(
                structured_llm,
                [
                    ("system", ANALYST_SYSTEM_PROMPT),
                    ("user", prompt)
                ],
                timeout=40.0,
                max_attempts=3,
                op_name="check_situation.analysis_llm",
            )
        except asyncio.TimeoutError:
            logger.error("상황 분석 LLM 호출이 시간 초과되어 proceed로 진행합니다.")
            return {
                "mode": resolved_mode,
                "check_status": "situation_analysis_timeout",
                "next_action": "proceed",
            }
        except Exception as e:
            logger.error("상황 분석 LLM 호출 실패: %s", e)
            return {
                "mode": resolved_mode,
                "check_status": f"situation_analysis_error: {e}",
                "next_action": "proceed",
            }
        
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
            "mode": resolved_mode,
            "check_status": analysis.reason, 
            "next_action": next_action,
            "extra_skill": fallback_skill,
            "skill_ids": new_skill_ids,
            "history": history,
        }

    async def extract(self, state: AgentState):
        """현재 인덱스의 Skill ID를 기반으로 도구 순서를 로드하고 파라미터 추출"""
        current_skill_id = state.skill_ids[state.current_index]
        resolved_mode = self._normalize_mode(state.mode)
        
        skill = SequenceSkill(skill_name=current_skill_id)
        steps_metadata = skill.get_steps_with_metadata(state.model_dump())
        tool_sequence = [step["tool"] for step in steps_metadata]
        
        if not tool_sequence:
            logger.error(f"Skill '{current_skill_id}'에 유효한 도구가 없습니다.")
            raise ValueError(f"Skill '{current_skill_id}'에 유효한 도구가 없습니다.")

        if resolved_mode == "manual":
            # manual 모드는 사람이 정의한 스킬 시퀀스를 그대로 실행하므로
            # 단계별 기본/고정 인자만 사용하고 LLM 추출을 생략한다.
            manual_calls: List[ToolCall] = []
            for step in steps_metadata:
                args: Dict[str, Any] = {}
                for arg_name, arg_meta in step["args"].items():
                    args[arg_name] = arg_meta.get("value")
                manual_calls.append(ToolCall(tool=step["tool"], args=args))
            return {"mode": resolved_mode, "enriched_plan": manual_calls, "tool_sequence": tool_sequence}

        # 스킬별 특화 안내문(skill.md)이 있으면 추가
        skill_instruction = f"\n\n### CURRENT SKILL SPECIFIC GUIDE ###\n{skill.instruction}" if skill.instruction else ""
        mode_instruction = MODE_INSTRUCTIONS.get(resolved_mode, MODE_INSTRUCTIONS["semi"])
        
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", f"{EXTRACTOR_SYSTEM_PROMPT}\n\n{mode_instruction}{skill_instruction}"),
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
        try:
            enriched = await self._ainvoke_with_retry(
                chain,
                {
                    "query": state.query,
                    "check_status": state.check_status,
                    "skill_id": current_skill_id,
                    "tool_constraints": json.dumps(steps_metadata, indent=2, ensure_ascii=False),
                    "tools_info": tools_info
                },
                timeout=50.0,
                max_attempts=3,
                op_name=f"extract.{current_skill_id}",
            )
        except Exception as e:
            logger.error("도구 인자 추출 실패(%s). 기본 인자로 fallback 합니다.", e)
            fallback_calls: List[ToolCall] = []
            for step in steps_metadata:
                default_args: Dict[str, Any] = {}
                for arg_name, arg_meta in step["args"].items():
                    default_args[arg_name] = arg_meta.get("value")
                fallback_calls.append(ToolCall(tool=step["tool"], args=default_args))
            return {"mode": resolved_mode, "enriched_plan": fallback_calls, "tool_sequence": tool_sequence}
        
        # [Post-process] Fixed 값 강제 적용 및 AI 값 검증
        final_calls = []
        remaining_steps = list(steps_metadata)

        for i, call in enumerate(enriched.calls):
            # 도구 순서에 맞춰 메타데이터 적용 (수동/준자동 모드 대응)
            # 동일한 도구가 여러 번 있을 경우 순차적으로 매칭하기 위해 매칭된 단계는 제외함
            matching_idx = next((idx for idx, s in enumerate(remaining_steps) if s["tool"] == call.tool), None)
            
            if matching_idx is not None:
                matching_step = remaining_steps.pop(matching_idx)
                new_args = dict(call.args)
                for arg_name, arg_meta in matching_step["args"].items():
                    if arg_meta["mode"] == "fixed":
                        new_args[arg_name] = arg_meta["value"]
                    elif arg_meta["mode"] == "ai":
                        # [검증] 가이드에 정의된 경로가 있는 경우, AI가 추출한 값이 목록에 있는지 확인
                        current_val = new_args.get(arg_name)
                        # 경로 관련 인자이고 허용 목록이 있는 경우 강제 검증
                        is_path_arg = any(k in arg_name.lower() for k in ["path", "file", "executable"])
                        if is_path_arg and ALLOWED_PATHS:
                            if current_val not in ALLOWED_PATHS:
                                logger.warning(f"가이드에 없는 경로 감지: '{current_val}'. 기본값 '{arg_meta['value']}'로 대체합니다.")
                                new_args[arg_name] = arg_meta["value"]
                call.args = new_args
            final_calls.append(call)
            
        valid_calls = [call for call in final_calls if call.tool in tool_sequence]
        if len(valid_calls) < len(enriched.calls):
            removed = [call.tool for call in enriched.calls if call.tool not in tool_sequence]
            logger.warning(f"스킬 '{current_skill_id}'에 정의되지 않은 도구 호출이 제외되었습니다: {removed}")

        return {"mode": resolved_mode, "enriched_plan": valid_calls, "tool_sequence": tool_sequence}

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
            try:
                analysis_res = await self._ainvoke_with_retry(
                    self.llm,
                    analysis_prompt,
                    timeout=45.0,
                    max_attempts=2,
                    op_name="report.clipboard_analysis",
                )
                clipboard_analysis = analysis_res.content
            except Exception as e:
                logger.error("클립보드 LLM 분석 실패: %s", e)
                clipboard_analysis = "LLM 분석 실패로 요약을 생성하지 못했습니다."

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
        try:
            res = await self._ainvoke_with_retry(
                self.llm,
                prompt,
                timeout=45.0,
                max_attempts=2,
                op_name="report.final",
            )
            final_report = res.content
        except Exception as e:
            logger.error("최종 리포트 LLM 호출 실패: %s", e)
            status = execution_summary.get("status", "unknown")
            failed_steps = execution_summary.get("failed_steps", [])
            final_report = (
                f"수행 여부: {status}\n"
                f"- 실패 단계 수: {len(failed_steps)}\n"
                f"- 참고: LLM 응답 지연/오류(예: 504)로 자동 요약 생성에 실패하여 기본 리포트를 반환합니다."
            )
        return {"report": final_report, "report_details": report_details}
