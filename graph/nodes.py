import json
import logging
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal, Union
from pydantic import BaseModel, Field, create_model
from langchain_core.prompts import ChatPromptTemplate
from core.app_session import AppSession
from core.state import AgentState, ToolCall, ToolCalls, SituationAnalysis
from graph.prompts import (
    PLANNER_SYSTEM_PROMPT, 
    ANALYST_SYSTEM_PROMPT, 
    EXTRACTOR_SYSTEM_PROMPT, 
    MODE_INSTRUCTIONS,
    ALLOWED_PATHS
)
from core.launch_paths import resolve_launch_paths
from skills.sequence_skill import SequenceSkill

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)

class GraphNodes:
    def __init__(self, mcp, execution_llm, planner_llm=None, analyst_llm=None, reporter_llm=None):
        self.mcp = mcp
        self.execution_llm = execution_llm
        self.planner_llm = planner_llm or execution_llm
        self.analyst_llm = analyst_llm or self.planner_llm
        self.reporter_llm = reporter_llm or self.planner_llm
        # 하위 호환: 기존 코드가 self.llm을 참조할 수 있도록 유지
        self.llm = self.execution_llm
        self._skills_cache: Optional[Dict[str, Any]] = None
        self._mcp_tools_cache: Optional[List[Dict[str, Any]]] = None

    async def _get_mcp_tools(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """MCP 도구 목록을 그래프 실행 동안 캐시합니다."""
        if self._mcp_tools_cache is not None and not refresh:
            return self._mcp_tools_cache
        self._mcp_tools_cache = await self.mcp.list_tools(refresh=refresh)
        return self._mcp_tools_cache

    def _get_skills_config(self) -> Dict[str, Any]:
        """skills.yaml 및 skills/ 디렉토리에서 스킬 설정들을 로드합니다."""
        all_skills = {}
        
        # 1. Legacy skills.yaml 로드
        try:
            with open(_PROJECT_ROOT / "config" / "skills.yaml", "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                all_skills.update(config.get("skills", {}))
        except Exception as e:
            logger.warning(f"Legacy skills.yaml 로드 실패: {e}")

        # 2. 개별 폴더 기반 스킬 로드 (skills/*/skill.yaml)
        try:
            skills_dir = _PROJECT_ROOT / "skills"
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
    def _skill_has_tools(skill_config: Any) -> bool:
        """스킬 정의에 실행 가능한 tool/step이 있는지 확인합니다."""
        if not isinstance(skill_config, dict):
            return False
        tools = skill_config.get("tools", skill_config.get("steps", [])) or []
        return bool(tools)

    def _get_runnable_skill_ids(self, skills_config: Dict[str, Any]) -> List[str]:
        """tools/steps가 정의된 실행 가능한 스킬 ID만 반환합니다."""
        return [sid for sid, cfg in skills_config.items() if self._skill_has_tools(cfg)]

    async def _map_skill_id(self, skill_id: str, valid_skills: Dict[str, Any]) -> str:
        """스킬 ID를 정확 일치 또는 구분자 차이만 보정합니다."""
        if not skill_id:
            return skill_id

        # 1. 완전 일치 확인 (Case-insensitive)
        skill_id_lower = skill_id.lower().strip()
        valid_ids = list(valid_skills.keys())
        
        # 정확히 일치하는 키 찾기 (대소문자 무시)
        exact_match = next((sid for sid in valid_ids if sid.lower() == skill_id_lower), None)
        if exact_match:
            return exact_match

        # 2. 정규화 일치 확인 (언더바, 하이픈 제거 후 비교)
        def normalize(s):
            return s.lower().replace("_", "").replace("-", "").strip()
        
        norm_id = normalize(skill_id)
        norm_match = next((sid for sid in valid_ids if normalize(sid) == norm_id), None)
        if norm_match:
            logger.info(f"스킬 ID 정규화 매핑: '{skill_id}' -> '{norm_match}'")
            return norm_match

        logger.warning("정의되지 않은 스킬 ID 감지: '%s'. 무시합니다.", skill_id)
        return ""

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
            if decoded_output.get("error") and decoded_output.get("success") is not True:
                return True
            status = str(decoded_output.get("status", "")).lower()
            result = str(decoded_output.get("result", "")).lower()
            if status in {"error", "failed", "aborted", "timeout"}:
                return True
            if result in {"error", "failed", "timeout"}:
                return True
        return False

    @staticmethod
    def _extract_failure_reason(decoded_output: Any) -> str:
        """도구 실패 메시지를 사람이 읽을 수 있는 문자열로 반환합니다."""
        if isinstance(decoded_output, dict):
            for key in ("message", "error", "reason", "result"):
                value = str(decoded_output.get(key, "")).strip()
                if value and value.lower() not in {"error", "failed", "timeout"}:
                    return value
            if decoded_output.get("error"):
                return str(decoded_output["error"])
        return str(decoded_output)

    @staticmethod
    def _is_path_arg_name(arg_name: str) -> bool:
        lowered = arg_name.lower()
        return any(token in lowered for token in ["path", "file", "executable"])

    def _apply_step_arg_constraints(
        self,
        step_args: Dict[str, Any],
        arg_meta_map: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """스킬 메타데이터 기준으로 fixed/ai 인자를 정규화합니다."""
        normalized = dict(step_args)
        for arg_name, arg_meta in arg_meta_map.items():
            if arg_meta.get("mode") == "fixed":
                normalized[arg_name] = arg_meta.get("value")
                continue

            if arg_meta.get("mode") == "ai":
                current_val = normalized.get(arg_name)
                if current_val is None:
                    normalized[arg_name] = arg_meta.get("value")

                if self._is_path_arg_name(arg_name) and ALLOWED_PATHS:
                    candidate = normalized.get(arg_name)
                    if candidate and candidate not in ALLOWED_PATHS:
                        logger.warning(
                            "가이드에 없는 경로 감지: '%s'. 기본값 '%s'로 대체합니다.",
                            candidate,
                            arg_meta.get("value"),
                        )
                        normalized[arg_name] = arg_meta.get("value")
        return normalized

    def _normalize_launch_tool_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """launch_application 호출 인자의 경로 별칭을 canonical key로 통합합니다."""
        try:
            app_config = AppSession.get_instance().config.get("application", {})
            config_exe = app_config.get("executable_path")
            config_connect = app_config.get("connect_path")
        except Exception:
            config_exe = None
            config_connect = None

        _, _, normalized = resolve_launch_paths(args, config_exe, config_connect)
        return normalized

    def _build_calls_from_steps(
        self,
        steps_metadata: List[Dict[str, Any]],
        llm_calls: Optional[List[ToolCall]] = None,
    ) -> List[ToolCall]:
        """skills.yaml에 정의된 모든 도구를 순서대로 실행하도록 호출 목록을 구성합니다."""
        llm_pool = list(llm_calls or [])
        final_calls: List[ToolCall] = []

        for step in steps_metadata:
            tool_name = step["tool"]
            match_idx = next((idx for idx, call in enumerate(llm_pool) if call.tool == tool_name), None)
            llm_call = llm_pool.pop(match_idx) if match_idx is not None else None

            args: Dict[str, Any] = {}
            if llm_call:
                args.update(llm_call.args or {})

            args = self._apply_step_arg_constraints(args, step.get("args", {}))
            if tool_name == "launch_application":
                args = self._normalize_launch_tool_args(args)
            final_calls.append(ToolCall(tool=tool_name, args=args))

        if llm_calls is not None and len(llm_calls) > len(final_calls):
            skipped = [call.tool for call in llm_pool]
            if skipped:
                logger.warning("스킬 순서 밖의 LLM 도구 호출은 무시됩니다: %s", skipped)

        return final_calls

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

    async def _plan_skills_auto(self, state: AgentState, skills_config: Dict[str, Any], valid_ids: List[str]) -> Dict[str, Any]:
        """질의와 스킬 목록을 기반으로 실행할 skill_ids를 AI가 선정합니다."""
        logger.info("--- [%s 계획] AI 스킬 계획 시작 ---", state.mode)

        runnable_ids = self._get_runnable_skill_ids(skills_config)
        if not runnable_ids:
            logger.warning("실행 가능한 스킬(tools/steps 정의)이 없습니다.")
            return {
                "skill_ids": [],
                "execution_halted": True,
                "halt_reason": (
                    "실행 가능한 스킬이 없습니다. config/skills.yaml 또는 skills/*/skill.yaml 에 "
                    "tools/steps가 정의된 스킬을 등록하세요."
                ),
            }

        skills_info = "\n".join(
            [f"- {sid}: {skills_config.get(sid, {}).get('description', '')}" for sid in runnable_ids]
        )

        SkillPlanModel = self._create_structured_plan_model(runnable_ids)
        structured_llm = self.planner_llm.with_structured_output(SkillPlanModel)

        try:
            plan = await structured_llm.ainvoke([
                ("system", PLANNER_SYSTEM_PROMPT),
                ("user", f"질의: {state.query}\n\n사용 가능한 스킬 목록:\n{skills_info}")
            ])

            result_ids = [sid for sid in getattr(plan, "skill_ids", []) if sid in runnable_ids]
            logger.info(f"AI 계획 결과: {result_ids}")
            if not result_ids:
                return {
                    "skill_ids": [],
                    "execution_halted": True,
                    "halt_reason": (
                        f"질의 '{state.query}'에 맞는 스킬을 찾지 못했습니다. "
                        f"/skills 로 확인 후 /analyze manual <질의> 를 사용하세요."
                    ),
                }
            return {"skill_ids": result_ids}
        except Exception as e:
            logger.error(f"계획 수립 중 오류 발생: {e}. 기본 매핑을 시도합니다.")
            raw_res = await self.planner_llm.ainvoke(
                f"질의: {state.query}\n목록: {runnable_ids}\n"
                "위 목록에 있는 스킬 ID만 콤마로 구분해 답하세요. 질의 문장 자체는 답하지 마세요."
            )
            potential_ids = [s.strip() for s in raw_res.content.split(",") if s.strip()]
            mapped_ids = []
            for pid in potential_ids:
                mapped = await self._map_skill_id(pid, skills_config)
                if mapped and mapped in runnable_ids:
                    mapped_ids.append(mapped)
            if not mapped_ids:
                return {
                    "skill_ids": [],
                    "execution_halted": True,
                    "halt_reason": (
                        f"스킬 계획 실패: {e}. /analyze manual <질의> 형식을 사용하세요."
                    ),
                }
            return {"skill_ids": mapped_ids}

    async def plan(self, state: AgentState):
        """실행할 skill_ids를 결정합니다."""
        skills_config = self._get_skills_config()
        valid_ids = list(skills_config.keys())

        use_ai_plan = (
            state.mode == "auto"
            or (state.mode in {"semi", "manual"} and not state.skill_ids)
        )
        if use_ai_plan:
            if state.mode == "semi" and not state.skill_ids:
                logger.info("[semi 모드] skill_ids 미지정 — AI 스킬 계획으로 fallback")
            elif state.mode == "manual" and not state.skill_ids:
                logger.info("[manual 모드] skill_ids 미지정 — AI 스킬 계획으로 스킬 선택")
            return await self._plan_skills_auto(state, skills_config, valid_ids)

        logger.info(f"[{state.mode} 모드] 기존 스킬 리스트 검증 및 매핑 시작")
        mapped_ids = []
        for sid in state.skill_ids:
            mapped = await self._map_skill_id(sid, skills_config)
            if mapped:
                mapped_ids.append(mapped)
        runnable_ids = self._get_runnable_skill_ids(skills_config)
        mapped_ids = [sid for sid in mapped_ids if sid in runnable_ids]
        if not mapped_ids:
            return {
                "skill_ids": [],
                "execution_halted": True,
                "halt_reason": (
                    f"{state.mode} 모드에서 유효한 skill_id를 찾지 못했습니다. "
                    f"/skills 로 확인하고 /analyze manual <질의> 를 사용하세요."
                ),
            }
        return {"skill_ids": mapped_ids}

    async def check_situation(self, state: AgentState):
        """현재 화면 상태를 분석하여 스킬 실행 가능 여부 체크"""
        if state.execution_halted or not state.skill_ids:
            logger.warning("실행할 스킬이 없어 상황 체크를 건너뜁니다.")
            return {
                "check_status": state.halt_reason or "no skills to run",
                "next_action": "abort",
                "execution_halted": True,
                "halt_reason": state.halt_reason or "실행할 스킬이 없습니다.",
            }

        current_skill_id = state.skill_ids[state.current_index]
        logger.info(f"--- 상황 체크 시작: {current_skill_id} (Index: {state.current_index}) ---")
        
        if state.mode == "manual":
            logger.info("[manual 모드] 상황 체크를 건너뛰고 진행합니다.")
            return {"check_status": "manual_bypass", "next_action": "proceed"}

        # [개선] 소스 수정이나 에디트 관련 스킬은 앱이 실행 중일 필요가 없으므로 상황 체크(앱 실행 트리거)를 건너뜁니다.
        # 앱 실행 전에 설정을 바꿔야 하는 경우를 대비한 로직입니다.
        source_keywords = ["edit", "source", "config", "replace", "find_text", "fetch", "url", "oracle", "query"]
        if any(kw in current_skill_id.lower() for kw in source_keywords):
            logger.info(f"[Bypass] 스킬 '{current_skill_id}'은 소스/설정 관련 작업이므로 화면 체크를 건너뜁니다.")
            return {"check_status": "source_edit_bypass", "next_action": "proceed"}

        state_info = await self.mcp.call_tool("describe_current_state", {"include_components": False})
        
        skills_config = self._get_skills_config()
        valid_ids = list(skills_config.keys())
        
        prompt = (
            f"현재 화면 상태: {state_info}\n"
            f"실행할 스킬 ID: {current_skill_id}\n"
            f"사용 가능한 복구용 스킬 목록: {valid_ids}\n"
        )
        
        # [최신 기법] 상황 분석에서도 유효한 스킬 ID만 제안하도록 동적 모델 적용
        DynamicAnalysisModel = self._create_structured_analysis_model(valid_ids)
        structured_llm = self.analyst_llm.with_structured_output(DynamicAnalysisModel)
        
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

        execution_halted = state.execution_halted
        halt_reason = state.halt_reason

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
            execution_halted = True
            halt_reason = f"상황 체크 중단: {analysis.reason}"
        
        return {
            "check_status": analysis.reason, 
            "next_action": next_action,
            "extra_skill": fallback_skill,
            "skill_ids": new_skill_ids,
            "history": history,
            "execution_halted": execution_halted,
            "halt_reason": halt_reason,
        }

    async def extract(self, state: AgentState):
        """현재 인덱스의 Skill ID를 기반으로 도구 순서를 로드하고 파라미터 추출"""
        current_skill_id = state.skill_ids[state.current_index]
        
        skill = SequenceSkill(skill_name=current_skill_id)
        steps_metadata = skill.get_steps_with_metadata(state.model_dump())
        tool_sequence = [step["tool"] for step in steps_metadata]
        
        if not tool_sequence:
            available = self._get_runnable_skill_ids(self._get_skills_config())
            logger.error(f"Skill '{current_skill_id}'에 유효한 도구가 없습니다.")
            raise ValueError(
                f"Skill '{current_skill_id}'에 유효한 도구가 없습니다. "
                f"질의 문장을 skill_id로 쓰지 말고 /skills 에서 확인한 ID를 사용하세요. "
                f"예: /analyze manual {state.query!r}. "
                f"사용 가능 스킬: {available}"
            )

        if state.mode == "manual":
            # manual 모드는 사람이 정의한 스킬 시퀀스를 그대로 실행하므로
            # 단계별 기본/고정 인자만 사용하고 LLM 추출을 생략한다.
            manual_calls: List[ToolCall] = []
            for step in steps_metadata:
                args: Dict[str, Any] = {}
                for arg_name, arg_meta in step["args"].items():
                    args[arg_name] = arg_meta.get("value")
                if step["tool"] == "launch_application":
                    args = self._normalize_launch_tool_args(args)
                manual_calls.append(ToolCall(tool=step["tool"], args=args))
            return {"enriched_plan": manual_calls, "tool_sequence": tool_sequence}

        # 스킬별 특화 안내문(skill.md)이 있으면 추가
        skill_instruction = f"\n\n### CURRENT SKILL SPECIFIC GUIDE ###\n{skill.instruction}" if skill.instruction else ""
        mode_instruction = MODE_INSTRUCTIONS.get(state.mode, MODE_INSTRUCTIONS["semi"])
        
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", f"{EXTRACTOR_SYSTEM_PROMPT}\n\n{mode_instruction}{skill_instruction}"),
            ("user", (
                "질의: {query}\n"
                "현재 상황: {check_status}\n"
                "현재 스킬({skill_id})의 도구 순서 및 인자 제약: {tool_constraints}\n"
                "허용된 도구명(정확히 이 문자열만 사용): {allowed_tool_names}\n"
                "사용 가능한 도구 정보:\n{tools_info}"
            ))
        ])

        structured_llm = self.execution_llm.with_structured_output(ToolCalls, method="function_calling", strict=False)
        
        all_tools = await self._get_mcp_tools()
        skill_tools = [t for t in all_tools if t['name'] in tool_sequence]
        tools_info = json.dumps(skill_tools, indent=2, ensure_ascii=False)
        
        chain = prompt_template | structured_llm
        enriched = await chain.ainvoke({
            "query": state.query,
            "check_status": state.check_status,
            "skill_id": current_skill_id,
            "tool_constraints": json.dumps(steps_metadata, indent=2, ensure_ascii=False),
            "allowed_tool_names": json.dumps(tool_sequence, ensure_ascii=False),
            "tools_info": tools_info
        })

        llm_calls = [call for call in enriched.calls if call.tool in tool_sequence]
        if len(llm_calls) < len(enriched.calls):
            removed = [call.tool for call in enriched.calls if call.tool not in tool_sequence]
            logger.warning(f"스킬 '{current_skill_id}'에 정의되지 않은 도구 호출이 제외되었습니다: {removed}")

        final_calls = self._build_calls_from_steps(steps_metadata, llm_calls)
        if len(llm_calls) < len(tool_sequence):
            logger.warning(
                "스킬 '%s': LLM이 %d개 도구만 반환해 YAML 정의 %d단계 전체를 보강합니다.",
                current_skill_id,
                len(llm_calls),
                len(tool_sequence),
            )

        return {"enriched_plan": final_calls, "tool_sequence": tool_sequence}

    async def run(self, state: AgentState):
        """추출된 파라미터로 MCP 도구 순차 실행"""
        results = list(state.history)
        current_skill_id = state.skill_ids[state.current_index]
        
        execution_halted = state.execution_halted
        halt_reason = state.halt_reason

        for call in state.enriched_plan:
            logger.info("[Run] %s 실행 시작 (args=%s)", call.tool, call.args)
            out = await self.mcp.call_tool(call.tool, call.args)
            decoded = self._decode_tool_output(out)
            results.append({
                "skill": current_skill_id,
                "tool": call.tool,
                "output": out,
            })

            if self._is_failed_output(decoded):
                reason = self._extract_failure_reason(decoded)
                halt_reason = f"{call.tool} 실패: {reason or 'unknown error'}"
                execution_halted = True
                logger.error("[Run] %s 실패 - 이후 단계 중단: %s", call.tool, halt_reason)
                break

            logger.info("[Run] %s 성공", call.tool)

        return {
            "history": results,
            "execution_halted": execution_halted,
            "halt_reason": halt_reason,
        }

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
        clipboard_entry = next(
            (h for h in reversed(history) if h.get("tool") == "read_clipboard_as_dataframe"),
            None,
        )

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
            analysis_res = await self.analyst_llm.ainvoke(analysis_prompt)
            clipboard_analysis = analysis_res.content

        if state.execution_halted:
            execution_summary["status"] = "halted"
            execution_summary["halt_reason"] = state.halt_reason

        report_details = {
            "execution": execution_summary,
            "clipboard": clipboard_data,
            "clipboard_analysis": clipboard_analysis,
            "execution_halted": state.execution_halted,
            "halt_reason": state.halt_reason,
        }

        halt_note = (
            f"\n중단 사유: {state.halt_reason}\n"
            "도구 실행 실패로 자동화가 중단되었습니다. 이 사실을 사용자에게 명확히 알려주세요."
            if state.execution_halted
            else ""
        )
        prompt = (
            f"요청: {state.query}\n"
            f"실행 요약: {json.dumps(execution_summary, ensure_ascii=False)}\n"
            f"클립보드 분석: {clipboard_analysis or clipboard_data.get('message', '없음')}\n"
            f"전체 실행 이력: {history}\n"
            f"{halt_note}\n"
            "최종 답변은 한국어로 작성하세요. 반드시 '수행 여부'를 먼저 명시하고, "
            "그 다음 클립보드 데이터(DataFrame) 분석 결과를 자연스럽게 이어서 설명하세요."
        )
        res = await self.reporter_llm.ainvoke(prompt)
        return {"report": res.content, "report_details": report_details}
