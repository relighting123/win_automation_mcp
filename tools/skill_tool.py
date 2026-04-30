import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from skills.sequence_skill import SequenceSkill

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

def register_skill_tools(mcp: "FastMCP", config_path: str = "config/skills.yaml") -> None:
    """YAML 설정을 읽어 모든 스킬을 MCP Tool로 동적 등록"""
    path = Path(config_path)
    if not path.exists():
        logger.warning(f"Skill 설정을 찾을 수 없어 등록을 건너뜁니다: {config_path}")
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            skills = config.get("skills", {})

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

