import json
import logging
from inspect import Parameter, Signature
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import yaml
from skills.sequence_skill import SequenceSkill

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_skill_definitions(config_path: str = "config/skills.yaml") -> dict:
    """config/skills.yaml + skills/*/skill.yaml 에서 스킬 목록을 수집합니다."""
    skills: dict = {}

    path = _PROJECT_ROOT / config_path
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
                skills.update(config.get("skills", {}))
        except Exception as e:
            logger.warning(f"Skill 설정 로드 실패 ({config_path}): {e}")

    skills_dir = _PROJECT_ROOT / "skills"
    if skills_dir.is_dir():
        for folder in sorted(skills_dir.iterdir()):
            if not folder.is_dir():
                continue
            yaml_path = folder / "skill.yaml"
            if not yaml_path.exists():
                continue
            skill_id = folder.name
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    folder_cfg = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"스킬 YAML 로드 실패 ({yaml_path}): {e}")
                continue

            entry = skills.setdefault(skill_id, {})
            entry.setdefault("description", folder_cfg.get("description", skill_id))

    return skills


def _load_skill_steps(skill_id: str, config_path: str = "config/skills.yaml") -> List[Dict[str, Any]]:
    """스킬 YAML에서 step 목록을 로드합니다."""
    folder_yaml = _PROJECT_ROOT / "skills" / skill_id / "skill.yaml"
    if folder_yaml.exists():
        with open(folder_yaml, "r", encoding="utf-8") as f:
            skill_config = yaml.safe_load(f) or {}
        return skill_config.get("tools", skill_config.get("steps", [])) or []

    path = _PROJECT_ROOT / config_path
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            full_config = yaml.safe_load(f) or {}
        skill_config = full_config.get("skills", {}).get(skill_id, {})
        return skill_config.get("tools", skill_config.get("steps", [])) or []

    return []


def _normalize_step_args(step: Dict[str, Any]) -> Dict[str, Any]:
    if "args" in step:
        raw_args = step.get("args")
        if raw_args is None:
            return {}
        if not isinstance(raw_args, dict):
            return {}
        return raw_args

    return {
        k: v
        for k, v in step.items()
        if k not in {"tool", "type", "action"}
    }


def extract_skill_ai_param_specs(steps: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    step.args에서 mode=ai 인자를 MCP tool 스키마용으로 추출합니다.

    Returns:
        {param_name: {"required": bool, "default": value|Parameter.empty}}
    """
    specs: Dict[str, Dict[str, Any]] = {}
    for step in steps:
        for name, raw in _normalize_step_args(step).items():
            if not isinstance(raw, dict) or raw.get("mode") != "ai":
                continue
            if name in specs:
                continue
            has_default = "value" in raw
            specs[name] = {
                "required": not has_default,
                "default": raw.get("value") if has_default else Parameter.empty,
            }
    return specs


def _annotation_for_param(default: Any) -> Any:
    if default is Parameter.empty:
        return str
    if isinstance(default, bool):
        return bool
    if isinstance(default, int) and not isinstance(default, bool):
        return int
    if isinstance(default, float):
        return float
    if isinstance(default, dict):
        return dict
    if isinstance(default, list):
        return list
    return str


def _build_skill_tool_signature(param_specs: Dict[str, Dict[str, Any]]) -> Signature:
    parameters: List[Parameter] = []
    for name, spec in param_specs.items():
        default = spec["default"]
        annotation = _annotation_for_param(default)
        if default is Parameter.empty:
            parameters.append(
                Parameter(name, Parameter.KEYWORD_ONLY, annotation=annotation)
            )
        else:
            parameters.append(
                Parameter(
                    name,
                    Parameter.KEYWORD_ONLY,
                    default=default,
                    annotation=annotation,
                )
            )
    return Signature(parameters)


def _format_skill_param_doc(param_specs: Dict[str, Dict[str, Any]]) -> str:
    if not param_specs:
        return ""
    lines = ["", "Parameters:"]
    for name, spec in param_specs.items():
        if spec["required"]:
            lines.append(f"  - {name} (required)")
        else:
            lines.append(f"  - {name} (optional, default={spec['default']!r})")
    return "\n".join(lines)


def _make_skill_func(
    skill_id: str,
    description: str,
    param_specs: Dict[str, Dict[str, Any]],
    config_path: str,
):
    async def skill_func(**runtime_kwargs) -> str:
        logger.info(f"[Tool] {skill_id} 호출")
        executor = SequenceSkill(skill_name=skill_id, config_path=config_path)
        result = await executor.execute(**runtime_kwargs)
        return json.dumps(result, ensure_ascii=False)

    skill_func.__name__ = skill_id
    skill_func.__doc__ = description + _format_skill_param_doc(param_specs)

    if param_specs:
        annotations = {
            name: _annotation_for_param(spec["default"])
            for name, spec in param_specs.items()
        }
        annotations["return"] = str
        skill_func.__annotations__ = annotations
        skill_func.__signature__ = _build_skill_tool_signature(param_specs)  # type: ignore[attr-defined]

    return skill_func


def register_skill_tools(mcp: "FastMCP", config_path: str = "config/skills.yaml") -> None:
    """YAML 설정을 읽어 모든 스킬을 MCP Tool로 동적 등록"""
    try:
        skills = _load_skill_definitions(config_path)
        if not skills:
            logger.warning("등록할 스킬이 없습니다.")
            return

        for skill_id, skill_info in skills.items():
            description = skill_info.get("description", f"{skill_id} skill")
            steps = _load_skill_steps(skill_id, config_path)
            param_specs = extract_skill_ai_param_specs(steps)
            tool_func = _make_skill_func(skill_id, description, param_specs, config_path)
            mcp.tool()(tool_func)

        logger.info(f"{len(skills)}개의 고수준 Skill 도구 등록 완료 (YAML 기반)")

    except Exception as e:
        logger.error(f"Skill 도구 등록 중 오류 발생: {e}")
