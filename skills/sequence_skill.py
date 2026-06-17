import inspect
import json
import logging
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from core.app_session import AppSession
from core.launch_paths import pick_launch_target, resolve_launch_paths
from skills.base_skill import BaseSkill
from tools.tool_registry import get_skill_tool_registry
from core.mcp_client import get_shared_extra_mcp_hub

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

class SequenceSkill(BaseSkill):
    """
    YAML 정의를 기반으로 여러 단계를 실행하는 범용 시퀀스 스킬
    """
    
    def __init__(self, skill_name: str, config_path: str = "config/skills.yaml", action=None):
        super().__init__(action)
        self.skill_name = skill_name
        self.config_path = config_path
        self._load_config()

    def _load_config(self):
        # 1. 개별 폴더 기반 스킬 확인 (New Structure)
        folder_path = _PROJECT_ROOT / "skills" / self.skill_name
        folder_yaml = folder_path / "skill.yaml"
        folder_md = folder_path / "skill.md"
        
        if folder_path.is_dir() and folder_yaml.exists():
            logger.info(f"Loading skill '{self.skill_name}' from folder: {folder_path}")
            with open(folder_yaml, "r", encoding="utf-8") as f:
                skill_config = yaml.safe_load(f)
                self.steps = skill_config.get("tools", skill_config.get("steps", [])) or []
                self.description = skill_config.get("description", "")
            
            # skill.md 내용 로드 (프롬프트 주입용)
            self.instruction = ""
            if folder_md.exists():
                self.instruction = folder_md.read_text(encoding="utf-8")
            return

        # 2. 레거시 중앙 집중식 설정 확인 (Legacy Structure)
        path = _PROJECT_ROOT / self.config_path
        if not path.exists():
            raise FileNotFoundError(
                f"Skill '{self.skill_name}' not found: "
                f"no folder at skills/{self.skill_name}/skill.yaml "
                f"and no legacy config at {self.config_path}"
            )
            
        with open(path, "r", encoding="utf-8") as f:
            full_config = yaml.safe_load(f)
            skill_config = full_config.get("skills", {}).get(self.skill_name, {})
            self.steps = skill_config.get("tools", skill_config.get("steps", [])) or []
            self.description = skill_config.get("description", "")
            self.instruction = ""

    def _normalize_step_args(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """step에서 args dict를 추출합니다. YAML의 빈 args: 는 None이 될 수 있어 {}로 정규화합니다."""
        if "args" in step:
            raw_args = step.get("args")
            if raw_args is None:
                return {}
            if not isinstance(raw_args, dict):
                raise ValueError(f"step.args는 dict 또는 null 이어야 합니다: {step}")
            return raw_args

        return {
            k: v
            for k, v in step.items()
            if k not in {"tool", "type", "action"}
        }

    def _render_template(self, value: Any, runtime_kwargs: Dict[str, Any]) -> Any:
        """step args 내부 문자열 템플릿을 런타임 인자 기준으로 치환"""
        if isinstance(value, str):
            try:
                return value.format(**runtime_kwargs)
            except (KeyError, IndexError, ValueError):
                return value
        if isinstance(value, dict):
            return {k: self._render_template(v, runtime_kwargs) for k, v in value.items()}
        if isinstance(value, list):
            return [self._render_template(v, runtime_kwargs) for v in value]
        return value

    def get_steps_with_metadata(self, runtime_kwargs: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        각 스텝의 도구와 인자별 고정(fixed)/AI(ai) 여부 메타데이터를 반환
        """
        metadata_steps = []
        for raw_step in self.steps:
            tool_name = raw_step.get("tool") or raw_step.get("type") or raw_step.get("action")
            if not tool_name:
                continue

            raw_args = self._normalize_step_args(raw_step)

            processed_args = {}
            for k, v in raw_args.items():
                if isinstance(v, dict) and "mode" in v:
                    mode = v.get("mode", "fixed")
                    if mode == "fixed":
                        processed_args[k] = {
                            "mode": "fixed",
                            "value": self._render_template(v.get("value"), runtime_kwargs)
                        }
                    else:
                        processed_args[k] = {
                            "mode": mode,
                            "value": self._render_template(v.get("value"), runtime_kwargs)
                        }
                else:
                    # 기본값은 fixed로 간주
                    processed_args[k] = {
                        "mode": "fixed",
                        "value": self._render_template(v, runtime_kwargs)
                    }

            metadata_steps.append({
                "tool": tool_name,
                "args": processed_args
            })
        return metadata_steps

    def _parse_step(self, step: Dict[str, Any], runtime_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """
        step schema:
          - 신규: {tool: "...", args: {...}}
          - 호환: {type: "...", ...flat args...}
        """
        tool_name = step.get("tool") or step.get("type") or step.get("action")
        if not tool_name:
            raise ValueError(f"step에 tool/type/action 중 하나가 필요합니다: {step}")

        tool_args = self._normalize_step_args(step)

        final_args = {}
        for k, v in tool_args.items():
            if isinstance(v, dict) and "mode" in v:
                mode = v.get("mode", "fixed")
                if mode == "fixed":
                    final_args[k] = self._render_template(v.get("value"), runtime_kwargs)
                elif mode == "ai":
                    # AI 모드인 경우 runtime_kwargs에서 값을 우선적으로 찾음
                    # (그래프 실행 시 LLM이 추출한 값이 runtime_kwargs에 포함됨)
                    val = runtime_kwargs.get(k)
                    if val is None:
                        val = self._render_template(v.get("value"), runtime_kwargs)
                    final_args[k] = val
                else:
                    final_args[k] = self._render_template(v.get("value"), runtime_kwargs)
            else:
                final_args[k] = self._render_template(v, runtime_kwargs)

        if tool_name == "launch_application" and (
            pick_launch_target(final_args) or final_args.get("connect_path")
        ):
            try:
                app_config = AppSession.get_instance().config.get("application", {})
                _, _, final_args = resolve_launch_paths(
                    final_args,
                    app_config.get("connect_path"),
                )
            except Exception as e:
                logger.warning("launch_application 인자 정규화 실패: %s", e)

        return {
            "tool": tool_name,
            "args": final_args,
        }

    def _normalize_result(self, raw_result: Any) -> Dict[str, Any]:
        """tool 반환값(JSON 문자열/딕셔너리/MCP content)을 공통 딕셔너리 형태로 통일"""
        if isinstance(raw_result, dict):
            if "error" in raw_result and "content" not in raw_result:
                return {"success": False, "message": str(raw_result.get("error"))}

            content_blocks = raw_result.get("content")
            if isinstance(content_blocks, list):
                text_blocks = [
                    block.get("text")
                    for block in content_blocks
                    if isinstance(block, dict)
                    and block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                ]
                if text_blocks:
                    combined = "\n".join(text_blocks).strip()
                    try:
                        parsed = json.loads(combined)
                        return parsed if isinstance(parsed, dict) else {"success": True, "result": parsed}
                    except json.JSONDecodeError:
                        return {"success": True, "text": combined}

            if raw_result.get("isError") is True:
                return {"success": False, "message": str(raw_result)}
            return raw_result
        if isinstance(raw_result, str):
            try:
                parsed = json.loads(raw_result)
                return parsed if isinstance(parsed, dict) else {"success": True, "result": parsed}
            except json.JSONDecodeError:
                return {"success": True, "result": raw_result}
        if hasattr(raw_result, "to_dict") and callable(raw_result.to_dict):
            return raw_result.to_dict()
        return {"success": True, "result": raw_result}

    async def execute(self, **kwargs) -> Dict[str, Any]:
        logger.info(f"MacroSkill 실행 시작: {self.skill_name} ({self.description})")

        try:
            tool_registry = get_skill_tool_registry()
            step_results: List[Dict[str, Any]] = []

            for index, raw_step in enumerate(self.steps):
                step = self._parse_step(raw_step, kwargs)
                tool_name = step["tool"]
                tool_args = step["args"]

                tool_func = tool_registry.get(tool_name)
                if tool_func is None:
                    extra_hub = await get_shared_extra_mcp_hub()
                    if extra_hub is None and (
                        tool_name.startswith("browsermcp/")
                        or tool_name.startswith("browsermcp:")
                        or tool_name.startswith("chrome-devtools/")
                        or tool_name.startswith("chrome-devtools:")
                    ):
                        raise ValueError(
                            "Browser MCP가 활성화되지 않았습니다. "
                            ".env에 MCP_BROWSER_MCP_ENABLED=true 를 설정하고 "
                            "Chrome 확장에서 Connect를 누른 뒤 chatRTD를 재시작하세요."
                        )
                    if extra_hub is not None and extra_hub.has_tool(tool_name):
                        raw_result = await extra_hub.call_tool(tool_name, tool_args)
                        normalized = self._normalize_result(raw_result)
                        step_results.append(
                            {
                                "index": index,
                                "tool": tool_name,
                                "args": tool_args,
                                "result": normalized,
                            }
                        )
                        if isinstance(normalized, dict) and normalized.get("success") is False:
                            raise RuntimeError(f"step 실패: tool={tool_name}, detail={normalized}")
                        continue
                    raise ValueError(f"알 수 없는 tool 이름입니다: {tool_name}")

                if inspect.iscoroutinefunction(tool_func):
                    raw_result = await tool_func(**tool_args)
                else:
                    raw_result = tool_func(**tool_args)

                normalized = self._normalize_result(raw_result)
                step_results.append(
                    {
                        "index": index,
                        "tool": tool_name,
                        "args": tool_args,
                        "result": normalized,
                    }
                )

                if isinstance(normalized, dict) and normalized.get("success") is False:
                    raise RuntimeError(f"step 실패: tool={tool_name}, detail={normalized}")

            return {
                "success": True,
                "skill": self.skill_name,
                "message": "성공적으로 수행되었습니다.",
                "steps": step_results,
            }

        except Exception as e:
            logger.error(f"MacroSkill '{self.skill_name}' 실행 중 오류: {e}")
            return {"success": False, "message": str(e)}
