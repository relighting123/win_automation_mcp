from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from actions.app_ui_action import AppUIAction, get_app_ui_action

class BaseSkill(ABC):
    """
    Base class for all skills.
    A skill is a semantic operation that combines multiple actions or tools.
    """
    
    def __init__(self, action: Optional[AppUIAction] = None):
        self.action = action or get_app_ui_action()
    
    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the skill.
        """
        pass
