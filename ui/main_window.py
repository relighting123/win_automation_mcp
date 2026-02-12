"""
메인 윈도우 UI 클래스 (Page Object Pattern)

메인 애플리케이션 윈도우의 UI 요소에 대한 접근만 담당합니다.
업무 로직은 Actions 계층에서 수행합니다.
"""

import logging
from typing import Optional, List

from core.app_session import AppSession
from ui.base_window import BaseWindow

logger = logging.getLogger(__name__)


class MainWindow(BaseWindow):
    """
    메인 윈도우 UI 클래스
    
    메인 애플리케이션 화면의 UI 요소에 대한 접근 메서드를 제공합니다.
    
    Example:
        >>> main_window = MainWindow()
        >>> main_window.wait_until_exists()
        >>> main_window.click_run_button()
        >>> status = main_window.get_status_text()
    """
    
    WINDOW_NAME = "main_window"
    
    def __init__(self, session: Optional[AppSession] = None):
        super().__init__(session)
    
    # ==================== 요소 접근 메서드 ====================
    
    def get_menu_bar(self):
        """메뉴바 반환"""
        return self.find_element("menu_bar")
    
    def get_toolbar(self):
        """툴바 반환"""
        return self.find_element("toolbar")
    
    def get_run_button(self):
        """실행 버튼 반환"""
        return self.find_element("run_button")
    
    def get_stop_button(self):
        """중지 버튼 반환"""
        return self.find_element("stop_button")
    
    def get_export_button(self):
        """내보내기 버튼 반환"""
        return self.find_element("export_button")
    
    def get_status_bar(self):
        """상태바 반환"""
        return self.find_element("status_bar")
    
    def get_data_grid(self):
        """데이터 그리드 반환"""
        return self.find_element_safe("data_grid")
    
    def get_tree_view(self):
        """트리 뷰 반환"""
        return self.find_element_safe("tree_view")
    
    def get_search_input(self):
        """검색 입력 필드 반환"""
        return self.find_element_safe("search_input")
    
    def get_search_button(self):
        """검색 버튼 반환"""
        return self.find_element_safe("search_button")
    
    # ==================== 버튼 클릭 메서드 ====================
    
    def click_run_button(self) -> None:
        """실행 버튼 클릭"""
        self.click("run_button")
        logger.debug("실행 버튼 클릭")
    
    def click_stop_button(self) -> None:
        """중지 버튼 클릭"""
        self.click("stop_button")
        logger.debug("중지 버튼 클릭")
    
    def click_export_button(self) -> None:
        """내보내기 버튼 클릭"""
        self.click("export_button")
        logger.debug("내보내기 버튼 클릭")
    
    def click_search_button(self) -> None:
        """검색 버튼 클릭"""
        self.click("search_button")
        logger.debug("검색 버튼 클릭")
    
    # ==================== 메뉴 메서드 ====================
    
    def click_menu_item(self, menu_path: List[str]) -> None:
        """
        메뉴 항목 클릭
        
        Args:
            menu_path: 메뉴 경로 (예: ["File", "Open"])
        """
        try:
            menu_bar = self.get_menu_bar()
            
            for item in menu_path:
                menu_item = menu_bar.child_window(title=item, control_type="MenuItem")
                menu_item.click_input()
                logger.debug(f"메뉴 클릭: {item}")
                
        except Exception as e:
            from errors.automation_error import wrap_pywinauto_error
            raise wrap_pywinauto_error(e, "메뉴 클릭", "->".join(menu_path))
    
    def select_file_menu(self, menu_item: str) -> None:
        """
        파일 메뉴 선택
        
        Args:
            menu_item: 메뉴 항목 이름 (예: "Open", "Save", "Exit")
        """
        self.click_menu_item(["File", menu_item])
    
    # ==================== 입력 메서드 ====================
    
    def input_search_text(self, text: str) -> None:
        """
        검색어 입력
        
        Args:
            text: 검색할 텍스트
        """
        self.set_text("search_input", text)
        logger.debug(f"검색어 입력: {text}")
    
    def search(self, text: str) -> None:
        """
        검색 수행 (입력 + 버튼 클릭)
        
        Args:
            text: 검색할 텍스트
        """
        self.input_search_text(text)
        self.click_search_button()
    
    # ==================== 상태 확인 메서드 ====================
    
    def get_status_text(self) -> str:
        """
        상태바 텍스트 반환
        
        Returns:
            상태바에 표시된 텍스트
        """
        try:
            return self.get_text("status_text")
        except Exception:
            # status_text가 없으면 status_bar에서 가져오기 시도
            try:
                status_bar = self.get_status_bar()
                return status_bar.window_text()
            except Exception:
                return ""
    
    def is_run_button_enabled(self) -> bool:
        """실행 버튼 활성화 여부"""
        return self.is_element_enabled("run_button")
    
    def is_stop_button_enabled(self) -> bool:
        """중지 버튼 활성화 여부"""
        return self.is_element_enabled("stop_button")
    
    def is_export_button_enabled(self) -> bool:
        """내보내기 버튼 활성화 여부"""
        return self.is_element_enabled("export_button")
    
    def is_running(self) -> bool:
        """
        작업 실행 중 여부 (중지 버튼 활성화 상태로 판단)
        
        Returns:
            실행 중 여부
        """
        return self.is_stop_button_enabled()
    
    # ==================== 데이터 그리드 메서드 ====================
    
    def get_grid_row_count(self) -> int:
        """
        데이터 그리드 행 개수 반환
        
        Returns:
            행 개수
        """
        try:
            grid = self.get_data_grid()
            if grid and grid.exists():
                # DataGrid의 행 개수 가져오기
                items = grid.children(control_type="DataItem")
                return len(items)
        except Exception as e:
            logger.debug(f"그리드 행 개수 가져오기 실패: {e}")
        return 0
    
    def select_grid_row(self, row_index: int) -> None:
        """
        데이터 그리드 행 선택
        
        Args:
            row_index: 선택할 행 인덱스 (0부터 시작)
        """
        try:
            grid = self.get_data_grid()
            if grid and grid.exists():
                items = grid.children(control_type="DataItem")
                if 0 <= row_index < len(items):
                    items[row_index].click()
                    logger.debug(f"그리드 행 선택: {row_index}")
        except Exception as e:
            from errors.automation_error import wrap_pywinauto_error
            raise wrap_pywinauto_error(e, "그리드 행 선택", f"row_{row_index}")
    
    # ==================== 트리 뷰 메서드 ====================
    
    def select_tree_item(self, item_path: List[str]) -> None:
        """
        트리 뷰 항목 선택
        
        Args:
            item_path: 항목 경로 (예: ["Root", "Child1", "SubChild"])
        """
        try:
            tree = self.get_tree_view()
            if tree and tree.exists():
                current = tree
                for item_name in item_path:
                    item = current.child_window(title=item_name, control_type="TreeItem")
                    item.expand()
                    current = item
                
                # 마지막 항목 선택
                current.select()
                logger.debug(f"트리 항목 선택: {' > '.join(item_path)}")
        except Exception as e:
            from errors.automation_error import wrap_pywinauto_error
            raise wrap_pywinauto_error(e, "트리 항목 선택", " > ".join(item_path))
    
    # ==================== 대기 메서드 ====================
    
    def wait_until_ready_to_run(self, timeout: Optional[float] = None) -> None:
        """실행 버튼이 활성화될 때까지 대기"""
        self.wait_for_element("run_button", timeout=timeout, condition="ready")
    
    def wait_until_running(self, timeout: Optional[float] = None) -> None:
        """작업이 시작될 때까지 대기 (중지 버튼 활성화)"""
        self.wait_for_element("stop_button", timeout=timeout, condition="ready")
    
    def wait_until_completed(self, timeout: Optional[float] = None) -> None:
        """
        작업이 완료될 때까지 대기 (중지 버튼 비활성화)
        
        Args:
            timeout: 대기 시간 (기본: long_wait)
        """
        from core.wait_utils import wait_until
        
        timeout = timeout or self._session.get_timeout("long_wait")
        
        wait_until(
            condition=lambda: not self.is_stop_button_enabled(),
            timeout=timeout,
            timeout_message="작업 완료 대기"
        )
    
    def wait_for_status_text(
        self,
        expected_text: str,
        timeout: Optional[float] = None,
        contains: bool = True
    ) -> bool:
        """
        특정 상태 텍스트가 나타날 때까지 대기
        
        Args:
            expected_text: 기대하는 텍스트
            timeout: 대기 시간
            contains: True면 포함 여부 확인, False면 정확히 일치
        
        Returns:
            텍스트 확인 성공 여부
        """
        from core.wait_utils import wait_until
        
        timeout = timeout or self._session.get_timeout("default_wait")
        
        def check_status():
            status = self.get_status_text()
            if contains:
                return expected_text in status
            return status == expected_text
        
        result = wait_until(
            condition=check_status,
            timeout=timeout,
            timeout_message=f"상태 텍스트 대기: {expected_text}",
            raise_on_timeout=False
        )
        
        return result.success
