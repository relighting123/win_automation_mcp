import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

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


def register_skill_tools(mcp: "FastMCP", config_path: str = "config/skills.yaml") -> None:
    """YAML 설정을 읽어 모든 스킬을 MCP Tool로 동적 등록"""
    try:
        skills = _load_skill_definitions(config_path)
        if not skills:
            logger.warning("등록할 스킬이 없습니다.")
            return

        for skill_id, skill_info in skills.items():
            description = skill_info.get("description", f"{skill_id} skill")
            
            # 클로저를 사용하여 각각의 스킬 함수 생성
            def make_skill_func(s_id, desc):
                async def skill_func(**kwargs) -> str:
                    # docstring이 MCP 도구 설명으로 사용됨
                    logger.info(f"[Tool] {s_id} 호출")
                    executor = SequenceSkill(skill_name=s_id, config_path=config_path)
                    result = await executor.execute(**kwargs)
                    return json.dumps(result, ensure_ascii=False)
                
                skill_func.__name__ = s_id
                skill_func.__doc__ = desc
                return skill_func

            tool_func = make_skill_func(skill_id, description)
            mcp.tool()(tool_func)
            
        logger.info(f"{len(skills)}개의 고수준 Skill 도구 등록 완료 (YAML 기반)")
        
    except Exception as e:
        logger.error(f"Skill 도구 등록 중 오류 발생: {e}")

