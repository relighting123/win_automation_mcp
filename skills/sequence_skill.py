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
                
                if step_type == "wait":
                    seconds = step.get("seconds", 0.5)
                    await asyncio.sleep(seconds)
                    
                # AppUIAction(action) 내의 모든 public 메서드 동적 매핑
                elif hasattr(self.action, step_type):
                    func = getattr(self.action, step_type)
                    if callable(func):
                        func_kwargs = {}
                        for k, v in step.items():
                            if k == "type":
                                continue
                            if isinstance(v, str):
                                try:
                                    func_kwargs[k] = v.format(**kwargs)
                                except KeyError:
                                    func_kwargs[k] = v
                            else:
                                func_kwargs[k] = v
                                
                        import inspect
                        if inspect.iscoroutinefunction(func):
                            await func(**func_kwargs)
                        else:
                            func(**func_kwargs)
                    else:
                        logger.warning(f"속성 '{step_type}'은 호출할 수 없는 액션 멤버입니다.")
                else:
                    logger.warning(f"알 수 없는 step type 또는 액션 메서드: {step_type}")
                    
            return {"success": True, "skill": self.skill_name, "message": "성공적으로 수행되었습니다."}
            
        except Exception as e:
            logger.error(f"MacroSkill '{self.skill_name}' 실행 중 오류: {e}")
            return {"success": False, "message": str(e)}
