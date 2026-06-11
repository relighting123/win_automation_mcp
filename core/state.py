from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class ToolCall(BaseModel):
    tool: str = Field(description="실행할 도구의 이름")
    args: Dict[str, Any] = Field(default_factory=dict, description="도구에 주입할 파라미터")

class ToolCalls(BaseModel):
    calls: List[ToolCall] = Field(description="도구 호출 목록")

class SituationAnalysis(BaseModel):
    category: str = Field(description="상황 카테고리: 'normal', 'login_required', 'error_state', 'other'")
    reason: str = Field(description="상황 판단 근거 (사용자에게 보고할 내용)")
    next_action: str = Field(
        default="proceed",
        description="다음 동작: 'proceed'|'skip'|'insert_recovery'|'abort'",
    )
    recovery_skill_id: Optional[str] = Field(None, description="필요 시 자동 실행할 복구 스킬 ID (예: 'login_skill')")

class AgentState(BaseModel):
    query: str
    skill_ids: List[str] # 시퀀스 실행할 스킬 리스트
    mode: str = "semi" # 실행 모드: auto, semi, manual
    current_index: int = 0 # 현재 실행 중인 스킬 인덱스
    check_status: str = ""  # AI 상황 체크 결과 요약
    next_action: str = "proceed"  # 상황 체크 후 다음 동작
    extra_skill: str = ""  # 자동 삽입된 대체 스킬 ID (예: login_required)
    history: List[Dict[str, Any]] = Field(default_factory=list) # 실행 이력
    enriched_plan: List[ToolCall] = Field(default_factory=list) # 추출된 도구 호출 목록
    tool_sequence: List[str] = Field(default_factory=list) # 현재 스킬의 도구 순서
    report: str = ""  # 최종 자연어 분석 결과
    report_details: Dict[str, Any] = Field(default_factory=dict)  # 구조화된 최종 리포트
    execution_halted: bool = False  # 도구 실패 시 이후 단계 중단 여부
    halt_reason: str = ""  # 중단 사유
