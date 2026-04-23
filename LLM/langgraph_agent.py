import json
import operator
import re
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, Sequence, Tuple, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph
from openai import OpenAI

class AgentState(TypedDict):
    """기본 순차 실행 에이전트 상태."""
    input: str
    plan: List[Dict[str, Any]]  # [{"tool": "...", "args": {...}}]
    current_step: int
    results: List[Any]
    memory: Dict[str, str]
    aborted: bool
    abort_reason: str
    messages: Annotated[Sequence[BaseMessage], operator.add]
    final_response: str

def create_mcp_agent(api_key: str, base_url: str, model_name: str, tools_metadata: List[Dict[str, Any]], call_tool_func):
    """
    가장 기본적인 LangGraph 순차 실행 에이전트를 생성합니다.
    - 입력 plan 형식: [{"tool": "도구명", "args": {...}}, ...]
    - plan 순서대로 도구를 1개씩 호출합니다.
    """
    llm_client: Optional[OpenAI] = None
    if api_key:
        llm_client = OpenAI(api_key=api_key, base_url=base_url)

    available_tool_names = set()
    for item in tools_metadata:
        fn_meta = item.get("function", {}) if isinstance(item, dict) else {}
        tool_name = fn_meta.get("name")
        if isinstance(tool_name, str) and tool_name.strip():
            available_tool_names.add(tool_name.strip())

    def _strip_fences(text: str) -> str:
        raw = (text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?", "", raw).strip()
            raw = re.sub(r"```$", "", raw).strip()
        return raw

    def _safe_json_loads(raw: str) -> Dict[str, Any]:
        candidate = _strip_fences(raw)
        loaded = json.loads(candidate)
        return loaded if isinstance(loaded, dict) else {}

    def _parse_datetime_parts(value: str) -> Tuple[str, str, str]:
        if not value:
            return "", "", ""

        value = value.strip()
        normalized = value
        normalized = normalized.replace("년", "-").replace("월", "-").replace("일", " ")
        normalized = normalized.replace("시", ":").replace("분", "")
        normalized = normalized.replace(".", "-").replace("/", "-")
        normalized = re.sub(r"\s+", " ", normalized).strip()

        for fmt in (
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H",
            "%Y-%m-%d",
            "%Y%m%d%H%M",
            "%Y%m%d",
        ):
            try:
                parsed = datetime.strptime(normalized, fmt)
                date_str = parsed.strftime("%Y-%m-%d")
                time_str = parsed.strftime("%H:%M")
                minute = parsed.strftime("%M")
                return f"{date_str} {time_str}", date_str, time_str if "H" in fmt else ""
            except ValueError:
                continue
        return value, "", ""

    def _extract_memory_with_llm(user_input: str) -> Dict[str, str]:
        default = {"id": "", "datetime": ""}
        if not llm_client:
            return default

        prompt = (
            "아래 사용자 질의에서 id와 날짜시간(연-월-일 시:분)을 추출해 주세요.\n"
            "반드시 JSON object만 응답하세요.\n"
            "형식: {\"id\":\"...\", \"datetime\":\"...\"}\n"
            "값이 없으면 빈 문자열로 채우세요."
        )
        try:
            response = llm_client.chat.completions.create(
                model=model_name,
                temperature=0,
                messages=[
                    {"role": "system", "content": "당신은 정보 추출기입니다. JSON만 출력하세요."},
                    {"role": "user", "content": f"{prompt}\n\n[질의]\n{user_input}"},
                ],
            )
            text = response.choices[0].message.content if response.choices else "{}"
            loaded = _safe_json_loads(text or "{}")
            return {
                "id": str(loaded.get("id", "") or "").strip(),
                "datetime": str(loaded.get("datetime", "") or "").strip(),
            }
        except Exception:
            return default

    def _extract_request_memory(user_input: str) -> Dict[str, str]:
        query = (user_input or "").strip()

        id_match = re.search(r"\b(?:id|ID)\s*[:=]?\s*([A-Za-z0-9_-]{2,})\b", query)
        if not id_match:
            id_match = re.search(r"\b([A-Z]{2,}-\d{2,})\b", query)

        datetime_match = re.search(
            r"(20\d{2}[./-]\d{1,2}[./-]\d{1,2}(?:\s+\d{1,2}:\d{1,2})?)",
            query,
        )
        if not datetime_match:
            datetime_match = re.search(
                r"(20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일(?:\s*\d{1,2}\s*시)?(?:\s*\d{1,2}\s*분)?)",
                query,
            )

        llm_memory = _extract_memory_with_llm(query)
        extracted_id = (id_match.group(1).strip() if id_match else "") or llm_memory["id"]
        extracted_datetime_raw = (
            datetime_match.group(1).strip() if datetime_match else ""
        ) or llm_memory["datetime"]

        datetime_full, date_only, time_only = _parse_datetime_parts(extracted_datetime_raw)
        minute = ""
        if time_only and ":" in time_only:
            minute = time_only.split(":")[1]

        memory = {
            "raw_input": query,
            "id": extracted_id,
            "request_id": extracted_id,
            "datetime": datetime_full,
            "requested_at": datetime_full,
            "date": date_only,
            "time": time_only,
            "minute": minute,
        }
        return memory

    def _render_template(data: Any, memory: Dict[str, str]) -> Any:
        if isinstance(data, str):
            rendered = data
            for key, value in memory.items():
                token = f"{{{{{key}}}}}"
                rendered = rendered.replace(token, value)
                rendered = rendered.replace(f"{{{{memory.{key}}}}}", value)
            return rendered
        if isinstance(data, dict):
            return {k: _render_template(v, memory) for k, v in data.items()}
        if isinstance(data, list):
            return [_render_template(v, memory) for v in data]
        return data

    def _run_tool(tool_name: str, tool_args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
        try:
            tool_result = call_tool_func(tool_name, tool_args)
        except Exception as exc:
            return None, str(exc)

        if isinstance(tool_result, dict):
            if tool_result.get("error"):
                return tool_result, str(tool_result.get("error"))
            if tool_result.get("isError") is True:
                return tool_result, str(tool_result)
            if str(tool_result.get("status", "")).lower() in {"error", "failed", "failure"}:
                return tool_result, str(tool_result)
        return tool_result, None

    def _build_error_action(
        state: AgentState,
        step_idx: int,
        tool_name: str,
        tool_args: Dict[str, Any],
        error_message: str,
    ) -> Dict[str, Any]:
        default = {
            "action": "abort",
            "reason": "복구 가능한 방법을 찾지 못해 중단합니다.",
            "retry_args": {},
            "recovery_tool": "",
            "recovery_args": {},
        }
        if not llm_client:
            return default

        payload = {
            "input": state.get("input", ""),
            "memory": state.get("memory", {}),
            "failed_step": {
                "step": step_idx + 1,
                "tool": tool_name,
                "args": tool_args,
                "error": error_message,
            },
            "results_so_far": state.get("results", []),
            "available_tools": sorted(available_tool_names),
            "decision_schema": {
                "action": "abort | retry | tool_then_retry | skip",
                "reason": "string",
                "retry_args": "object",
                "recovery_tool": "string",
                "recovery_args": "object",
            },
        }
        try:
            response = llm_client.chat.completions.create(
                model=model_name,
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "당신은 자동화 실행기의 에러 복구 의사결정기입니다. "
                            "반드시 JSON object만 출력하세요."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "아래 실행 상태를 보고 다음 행동을 결정하세요.\n"
                            "- action: abort | retry | tool_then_retry | skip\n"
                            "- tool_then_retry일 때 recovery_tool은 반드시 available_tools 중 하나여야 함\n"
                            "- 복구 가능성이 낮으면 abort\n\n"
                            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
                        ),
                    },
                ],
            )
            text = response.choices[0].message.content if response.choices else "{}"
            decision = _safe_json_loads(text or "{}")
            action = str(decision.get("action", "")).strip()
            if action not in {"abort", "retry", "tool_then_retry", "skip"}:
                return default

            recovery_tool = str(decision.get("recovery_tool", "") or "").strip()
            if action == "tool_then_retry" and recovery_tool not in available_tool_names:
                return default

            retry_args = decision.get("retry_args")
            recovery_args = decision.get("recovery_args")
            if not isinstance(retry_args, dict):
                retry_args = {}
            if not isinstance(recovery_args, dict):
                recovery_args = {}

            return {
                "action": action,
                "reason": str(decision.get("reason", "") or "").strip() or default["reason"],
                "retry_args": retry_args,
                "recovery_tool": recovery_tool,
                "recovery_args": recovery_args,
            }
        except Exception:
            return default

    # 2. 노드 정의
    def planner_node(state: AgentState):
        """사용자 제공 plan을 검증하고 실행 준비를 합니다."""
        plan = state.get("plan", []) or []
        memory = _extract_request_memory(state.get("input", ""))
        if not plan:
            return {
                "plan": [],
                "current_step": 0,
                "results": [],
                "memory": memory,
                "aborted": False,
                "abort_reason": "",
                "final_response": (
                    "실행할 plan이 없습니다. "
                    "[{\"tool\":\"tool_name\", \"args\": {...}}] 형식의 리스트를 전달해주세요."
                ),
                "messages": [AIMessage(content="plan이 비어 있어 실행을 종료합니다.")],
            }

        normalized_plan: List[Dict[str, Any]] = []
        for idx, step in enumerate(plan):
            if not isinstance(step, dict) or "tool" not in step:
                return {
                    "plan": [],
                    "current_step": 0,
                    "results": [],
                    "memory": memory,
                    "aborted": True,
                    "abort_reason": f"{idx + 1}번째 step 형식이 잘못되었습니다.",
                    "final_response": f"{idx + 1}번째 step 형식이 잘못되었습니다. (필수 키: tool)",
                    "messages": [AIMessage(content=f"{idx + 1}번째 step 검증 실패")],
                }

            args = step.get("args", {})
            if not isinstance(args, dict):
                return {
                    "plan": [],
                    "current_step": 0,
                    "results": [],
                    "memory": memory,
                    "aborted": True,
                    "abort_reason": f"{idx + 1}번째 step의 args 타입이 잘못되었습니다.",
                    "final_response": f"{idx + 1}번째 step의 args는 dict여야 합니다.",
                    "messages": [AIMessage(content=f"{idx + 1}번째 step args 타입 오류")],
                }

            normalized_plan.append({"tool": step["tool"], "args": args})

        return {
            "plan": normalized_plan,
            "current_step": 0,
            "results": [],
            "memory": memory,
            "aborted": False,
            "abort_reason": "",
            "messages": [
                AIMessage(
                    content=(
                        f"{len(normalized_plan)}개 step 순차 실행을 시작합니다. "
                        f"(id={memory.get('id', '')}, datetime={memory.get('datetime', '')})"
                    )
                )
            ],
        }

    def executor_node(state: AgentState):
        """계획된 단계 중 현재 단계를 실행합니다."""
        if state.get("aborted"):
            return {}

        step_idx = state["current_step"]
        if step_idx >= len(state["plan"]):
            return {}

        step = state["plan"][step_idx]
        tool_name = step["tool"]
        raw_args = step.get("args", {})
        memory = state.get("memory", {})
        tool_args = _render_template(raw_args, memory)

        tool_result, tool_error = _run_tool(tool_name, tool_args)
        if not tool_error:
            result_entry = {
                "step": step_idx + 1,
                "tool": tool_name,
                "raw_args": raw_args,
                "args": tool_args,
                "status": "ok",
                "result": tool_result,
            }
            msg = f"step {step_idx + 1} 완료: {tool_name}"
            return {
                "results": state.get("results", []) + [result_entry],
                "current_step": step_idx + 1,
                "messages": [AIMessage(content=msg)],
            }

        error_entry: Dict[str, Any] = {
            "step": step_idx + 1,
            "tool": tool_name,
            "raw_args": raw_args,
            "args": tool_args,
            "status": "error",
            "error": tool_error,
        }

        action = _build_error_action(state, step_idx, tool_name, tool_args, tool_error)
        action_type = action["action"]

        if action_type == "skip":
            error_entry["recovery_decision"] = action
            error_entry["status"] = "skipped"
            return {
                "results": state.get("results", []) + [error_entry],
                "current_step": step_idx + 1,
                "messages": [
                    AIMessage(
                        content=(
                            f"step {step_idx + 1} 실패 후 skip: {tool_name} "
                            f"({action.get('reason', '')})"
                        )
                    )
                ],
            }

        if action_type == "retry":
            retry_args = action.get("retry_args") or tool_args
            if not isinstance(retry_args, dict):
                retry_args = tool_args
            retry_args = _render_template(retry_args, memory)
            retry_result, retry_error = _run_tool(tool_name, retry_args)
            if not retry_error:
                success_entry = {
                    "step": step_idx + 1,
                    "tool": tool_name,
                    "raw_args": raw_args,
                    "args": retry_args,
                    "status": "ok",
                    "result": retry_result,
                    "recovery_decision": action,
                    "attempt": 2,
                }
                return {
                    "results": state.get("results", []) + [success_entry],
                    "current_step": step_idx + 1,
                    "messages": [
                        AIMessage(
                            content=f"step {step_idx + 1} 재시도 성공: {tool_name}"
                        )
                    ],
                }

            error_entry["retry_error"] = retry_error
            error_entry["recovery_decision"] = action
            return {
                "results": state.get("results", []) + [error_entry],
                "aborted": True,
                "abort_reason": f"step {step_idx + 1} 재시도 실패: {retry_error}",
                "messages": [AIMessage(content=f"step {step_idx + 1} 중단: 재시도 실패")],
            }

        if action_type == "tool_then_retry":
            recovery_tool = action.get("recovery_tool", "")
            recovery_args = action.get("recovery_args", {})
            if not isinstance(recovery_args, dict):
                recovery_args = {}
            recovery_args = _render_template(recovery_args, memory)

            recovery_result, recovery_error = _run_tool(recovery_tool, recovery_args)
            recovery_entry = {
                "step": step_idx + 1,
                "tool": recovery_tool,
                "args": recovery_args,
                "status": "ok" if not recovery_error else "error",
                "result": recovery_result,
                "error": recovery_error,
                "type": "recovery_tool",
            }
            if recovery_error:
                error_entry["recovery_decision"] = action
                error_entry["recovery_error"] = recovery_error
                return {
                    "results": state.get("results", []) + [recovery_entry, error_entry],
                    "aborted": True,
                    "abort_reason": f"복구 tool 실패: {recovery_error}",
                    "messages": [AIMessage(content=f"step {step_idx + 1} 중단: 복구 tool 실패")],
                }

            retry_args = action.get("retry_args") or tool_args
            if not isinstance(retry_args, dict):
                retry_args = tool_args
            retry_args = _render_template(retry_args, memory)
            retry_result, retry_error = _run_tool(tool_name, retry_args)
            if not retry_error:
                success_entry = {
                    "step": step_idx + 1,
                    "tool": tool_name,
                    "raw_args": raw_args,
                    "args": retry_args,
                    "status": "ok",
                    "result": retry_result,
                    "recovery_decision": action,
                    "attempt": 2,
                }
                return {
                    "results": state.get("results", []) + [recovery_entry, success_entry],
                    "current_step": step_idx + 1,
                    "messages": [AIMessage(content=f"step {step_idx + 1} 복구 후 성공: {tool_name}")],
                }

            error_entry["retry_error"] = retry_error
            error_entry["recovery_decision"] = action
            return {
                "results": state.get("results", []) + [recovery_entry, error_entry],
                "aborted": True,
                "abort_reason": f"복구 후 재시도 실패: {retry_error}",
                "messages": [AIMessage(content=f"step {step_idx + 1} 중단: 복구 후 재시도 실패")],
            }

        # abort 또는 알 수 없는 액션은 안전하게 중단
        error_entry["recovery_decision"] = action
        return {
            "results": state.get("results", []) + [error_entry],
            "aborted": True,
            "abort_reason": action.get("reason", "에러 복구 판단 결과 중단"),
            "messages": [AIMessage(content=f"step {step_idx + 1} 중단: {tool_name}")],
        }

    def final_node(state: AgentState):
        """실행 결과를 간단히 문자열로 반환합니다."""
        plan = state.get("plan", [])
        results = state.get("results", [])
        success_count = sum(1 for item in results if item.get("status") == "ok")
        fail_count = len(results) - success_count

        summary = {
            "input": state.get("input", ""),
            "memory": state.get("memory", {}),
            "requested_steps": len(plan),
            "executed_steps": len(results),
            "success": success_count,
            "failed": fail_count,
            "aborted": state.get("aborted", False),
            "abort_reason": state.get("abort_reason", ""),
            "results": results,
        }
        return {
            "final_response": json.dumps(summary, ensure_ascii=False, indent=2),
            "messages": [AIMessage(content="모든 step 실행이 종료되었습니다.")],
        }

    # 3. 그래프 구축
    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("finalizer", final_node)

    workflow.set_entry_point("planner")

    def should_execute(state: AgentState):
        if state.get("plan"):
            return "execute"
        return "end"

    workflow.add_conditional_edges(
        "planner",
        should_execute,
        {
            "execute": "executor",
            "end": "finalizer",
        },
    )

    def should_continue(state: AgentState):
        if state.get("aborted"):
            return "end"
        if state["current_step"] < len(state["plan"]):
            return "continue"
        return "end"

    workflow.add_conditional_edges(
        "executor",
        should_continue,
        {
            "continue": "executor",
            "end": "finalizer",
        },
    )
    workflow.add_edge("finalizer", END)

    return workflow.compile()
