import asyncio
import unittest
from unittest.mock import MagicMock
from skills.feature_execution_skill import FeatureExecutionSkill
from actions.app_ui_action import AppUIActionResult

class TestFeatureExecutionSkill(unittest.IsolatedAsyncioTestCase):
    async def test_execute_skill_sequence(self):
        # 1. Action Layer Mock 생성
        mock_action = MagicMock()
        
        # ensure_focus 성공 결과
        mock_action.ensure_focus.return_value = AppUIActionResult(result="success", message="Focus OK")
        
        # press_shortcut 성공 결과
        mock_action.press_shortcut.return_value = AppUIActionResult(result="success")
        
        # 2. Skill 인스턴스 생성 (Mock 주입)
        skill = FeatureExecutionSkill(action=mock_action)
        
        # 3. 실행
        result = await skill.execute()
        
        # 4. 검증
        print(f"Skill Execution Result: {result}")
        self.assertTrue(result["success"])
        
        # ensure_focus가 호출되었는지 확인
        mock_action.ensure_focus.assert_called_once()
        
        # press_shortcut이 총 7번 (4 + 2 + 1) 호출되었는지 확인
        self.assertEqual(mock_action.press_shortcut.call_count, 7)
        
        # 호출 순서 검증
        calls = mock_action.press_shortcut.call_args_list
        # Right 4번
        for i in range(4):
            self.assertEqual(calls[i][0][0], "right")
        # Down 2번
        for i in range(4, 6):
            self.assertEqual(calls[i][0][0], "down")
        # Enter 1번
        self.assertEqual(calls[6][0][0], "enter")
        
        print("모든 호출 순서 검증 완료 (Right x4 -> Down x2 -> Enter x1)")

if __name__ == "__main__":
    unittest.main()
