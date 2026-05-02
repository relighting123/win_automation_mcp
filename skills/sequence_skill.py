import asyncio
import inspect
import json
import logging
import yaml
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from skills.base_skill import BaseSkill
from tools.tool_registry import get_skill_tool_registry

logger = logging.getLogger(__name__)

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
        path = Path(self.config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
            
        with open(path, "r", encoding="utf-8") as f:
            full_config = yaml.safe_load(f)
            skill_config = full_config.get("skills", {}).get(self.skill_name, {})
            self.steps = skill_config.get("tools", skill_config.get("steps", []))
            self.description = skill_config.get("description", "")

    _PLACEHOLDER_PATTERN = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")

    def _to_bool_arg_mutability(self, value: Any) -> bool:
        """arg_policy 값을 bool 형태(변경 가능 여부)로 정규화"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"mutable", "dynamic", "runtime", "ai", "allow", "true", "yes"}:
                return True
            if normalized in {"fixed", "immutable", "locked", "static", "const", "deny", "false", "no"}:
                return False
        raise ValueError(
            "arg_policy 값은 bool 또는 'mutable'/'fixed' 계열 문자열이어야 합니다."
        )

    def _normalize_arg_policy(self, raw_policy: Any) -> Dict[str, bool]:
        """step별 arg_policy를 {arg_name: is_mutable} 형태로 변환"""
        if raw_policy is None:
            return {}
        if not isinstance(raw_policy, dict):
            raise ValueError(f"step.arg_policy는 dict 이어야 합니다: {raw_policy}")
        return {str(arg_name): self._to_bool_arg_mutability(value) for arg_name, value in raw_policy.items()}

    def _parse_step_base(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """
        step schema:
          - 신규: {tool: "...", args: {...}, arg_policy: {...}}
          - 호환: {type: "...", ...flat args...}
        """
        tool_name = step.get("tool") or step.get("type") or step.get("action")
        if not tool_name:
            raise ValueError(f"step에 tool/type/action 중 하나가 필요합니다: {step}")

        if "args" in step:
            if not isinstance(step["args"], dict):
                raise ValueError(f"step.args는 dict 이어야 합니다: {step}")
            tool_args = step["args"]
        else:
            tool_args = {
                k: v
                for k, v in step.items()
                if k not in {"tool", "type", "action", "arg_policy"}
            }

        arg_policy = self._normalize_arg_policy(step.get("arg_policy"))
        unknown_policy_args = [arg_name for arg_name in arg_policy if arg_name not in tool_args]
        if unknown_policy_args:
            raise ValueError(
                f"step.arg_policy에 args에 없는 키가 포함되어 있습니다: {unknown_policy_args}. "
                f"(tool={tool_name})"
            )
        return {"tool": tool_name, "args": tool_args, "arg_policy": arg_policy}

    def get_step_definitions(self) -> List[Dict[str, Any]]:
        """YAML 단계 정의를 실행 친화적 구조로 정규화해 반환"""
        return [self._parse_step_base(step) for step in self.steps]

    def _contains_template_placeholder(self, value: Any) -> bool:
        if isinstance(value, str):
            return bool(self._PLACEHOLDER_PATTERN.search(value))
        if isinstance(value, dict):
            return any(self._contains_template_placeholder(v) for v in value.values())
        if isinstance(value, list):
            return any(self._contains_template_placeholder(v) for v in value)
        return False

    def _render_template(self, value: Any, runtime_kwargs: Dict[str, Any]) -> Any:
        """step args 내부 문자열 템플릿을 런타임 인자 기준으로 치환"""
        if isinstance(value, str):
            try:
                return value.format(**runtime_kwargs)
            except KeyError:
                return value
        if isinstance(value, dict):
            return {k: self._render_template(v, runtime_kwargs) for k, v in value.items()}
        if isinstance(value, list):
            return [self._render_template(v, runtime_kwargs) for v in value]
        return value

    def _parse_step(self, step: Dict[str, Any], runtime_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        parsed = self._parse_step_base(step)
        rendered_args: Dict[str, Any] = {}
        for arg_name, arg_value in parsed["args"].items():
            is_mutable = parsed["arg_policy"].get(arg_name, True)
            if is_mutable:
                rendered_args[arg_name] = self._render_template(arg_value, runtime_kwargs)
            else:
                if self._contains_template_placeholder(arg_value):
                    logger.warning(
                        "고정 인자(%s.%s)에 placeholder가 포함되어 치환하지 않습니다: %s",
                        parsed["tool"],
                        arg_name,
                        arg_value,
                    )
                rendered_args[arg_name] = arg_value

        return {"tool": parsed["tool"], "args": rendered_args, "arg_policy": parsed["arg_policy"]}

    def _normalize_result(self, raw_result: Any) -> Dict[str, Any]:
        """tool 반환값(JSON 문자열/딕셔너리 등)을 공통 딕셔너리 형태로 통일"""
        if isinstance(raw_result, dict):
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

                if tool_name == "wait":
                    seconds = float(tool_args.get("seconds", 0.5))
                    await asyncio.sleep(seconds)
                    step_results.append(
                        {
                            "index": index,
                            "tool": tool_name,
                            "args": tool_args,
                            "result": {"success": True, "message": f"{seconds}초 대기 완료"},
                        }
                    )
                    continue

                tool_func = tool_registry.get(tool_name)
                if tool_func is None:
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
