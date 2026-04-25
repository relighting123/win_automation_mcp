import asyncio
import logging
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from skills.base_skill import BaseSkill

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
            self.steps = full_config.get("skills", {}).get(self.skill_name, {}).get("steps", [])
            self.description = full_config.get("skills", {}).get(self.skill_name, {}).get("description", "")

    async def execute(self, **kwargs) -> Dict[str, Any]:
        logger.info(f"MacroSkill 실행 시작: {self.skill_name} ({self.description})")
        
        try:
            for step in self.steps:
                step_type = step.get("type")
                
                if step_type == "ensure_focus":
                    self.action.ensure_focus()
                    
                elif step_type == "press" or step_type == "press_shortcut":
                    key = step.get("key")
                    repeat = step.get("repeat", 1)
                    for _ in range(repeat):
                        self.action.press_shortcut(key)
                        await asyncio.sleep(0.1)
                        
                elif step_type == "type":
                    text = step.get("text", "").format(**kwargs)
                    self.action.type_text(text)
                    
                elif step_type == "find_text":
                    keyword = step.get("keyword", "").format(**kwargs)
                    await self.action.find_text_position(keyword)
                    
                elif step_type == "wait":
                    seconds = step.get("seconds", 0.5)
                    await asyncio.sleep(seconds)
                
                else:
                    logger.warning(f"알 수 없는 step type: {step_type}")
                    
            return {"success": True, "skill": self.skill_name, "message": "성공적으로 수행되었습니다."}
            
        except Exception as e:
            logger.error(f"MacroSkill '{self.skill_name}' 실행 중 오류: {e}")
            return {"success": False, "message": str(e)}
