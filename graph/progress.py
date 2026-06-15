"""automation graph 진행 상황을 CLI 등에 표시하기 위한 포맷터."""

from __future__ import annotations

from typing import Any, Dict, List


_NODE_LABELS = {
    "plan": "계획",
    "check_situation": "상황 체크",
    "extract": "인자 준비",
    "run": "실행",
    "next": "다음 스킬",
    "report": "보고",
}


def _decode_tool_output(output: Any) -> Any:
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        text = output.strip()
        if not text:
            return output
        try:
            import json

            return json.loads(text)
        except Exception:
            return output
    return output


def _tool_status_symbol(output: Any) -> str:
    decoded = _decode_tool_output(output)
    if isinstance(decoded, dict):
        if decoded.get("success") is True or str(decoded.get("result", "")).lower() == "success":
            return "ok"
        if decoded.get("success") is False or str(decoded.get("result", "")).lower() in {
            "error",
            "failed",
            "timeout",
            "not_found",
        }:
            return "err"
    return "muted"


def _tool_status_text(output: Any) -> str:
    decoded = _decode_tool_output(output)
    if not isinstance(decoded, dict):
        return ""
    for key in ("message", "error", "reason"):
        value = str(decoded.get(key, "")).strip()
        if value:
            return value[:120]
    return ""


def format_graph_progress_event(
    node_name: str,
    update: Dict[str, Any],
    *,
    context: Dict[str, Any],
) -> List[str]:
    """LangGraph updates 청크 하나를 사람이 읽을 수 있는 진행 로그로 변환합니다."""
    label = _NODE_LABELS.get(node_name, node_name)
    lines: List[str] = []

    if node_name == "plan":
        skill_ids = update.get("skill_ids") or []
        if update.get("execution_halted"):
            reason = str(update.get("halt_reason", "")).strip() or "스킬 계획 실패"
            lines.append(f"[{label}] 중단 — {reason}")
        elif skill_ids:
            lines.append(f"[{label}] 스킬 선택: {', '.join(skill_ids)}")
        else:
            lines.append(f"[{label}] 스킬 계획 완료")

    elif node_name == "check_situation":
        next_action = str(update.get("next_action", "proceed"))
        status = str(update.get("check_status", "")).strip()
        if next_action == "manual_bypass":
            lines.append(f"[{label}] manual 모드 — 건너뜀")
        elif status == "user_skip":
            lines.append(f"[{label}] 사용자 스킵")
        elif status == "user_stop":
            lines.append(f"[{label}] 사용자 중지|err")
        elif status:
            lines.append(f"[{label}] {next_action} — {status[:100]}")
        else:
            lines.append(f"[{label}] {next_action}")

    elif node_name == "extract":
        tools = update.get("tool_sequence") or [
            call.get("tool")
            for call in (update.get("enriched_plan") or [])
            if isinstance(call, dict) and call.get("tool")
        ]
        if tools:
            lines.append(f"[{label}] 도구 순서: {' → '.join(tools)}")
        else:
            lines.append(f"[{label}] 도구 순서 준비")

    elif node_name == "run":
        history = update.get("history") or []
        prev_len = int(context.get("history_len", 0))
        for entry in history[prev_len:]:
            if not isinstance(entry, dict):
                continue
            tool_name = str(entry.get("tool", ""))
            skill_name = str(entry.get("skill", ""))
            symbol = _tool_status_symbol(entry.get("output"))
            detail = _tool_status_text(entry.get("output"))
            prefix = f"[{label}]"
            if skill_name:
                prefix += f" ({skill_name})"
            line = f"{prefix} {tool_name}"
            if detail:
                line += f" — {detail}"
            lines.append(f"{line}|{symbol}")
        context["history_len"] = len(history)

        if update.get("execution_halted"):
            reason = str(update.get("halt_reason", "")).strip()
            if reason:
                lines.append(f"[{label}] 중단 — {reason}|err")

    elif node_name == "next":
        index = update.get("current_index")
        if index is not None:
            lines.append(f"[{label}] index → {index}")

    elif node_name == "report":
        if update.get("execution_halted"):
            reason = str(update.get("halt_reason", "")).strip()
            if reason:
                lines.append(f"[{label}] halted — {reason}|err")
            else:
                lines.append(f"[{label}] 최종 보고 생성")
        else:
            lines.append(f"[{label}] 최종 보고 생성")

    else:
        lines.append(f"[{label}] 완료")

    return lines
