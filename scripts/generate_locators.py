import argparse
import json
import logging
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.app_launcher import get_launcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TARGET_TYPES = {
    "button",
    "edit",
    "text",
    "checkbox",
    "combobox",
    "menuitem",
    "datagrid",
    "tree",
    "treeitem",
}

CHILD_SEARCH_ROOT_TYPES = {"window", "pane", "document", "group", "custom", "dialog"}


def _to_wrapper(window_spec: Any) -> Any:
    if hasattr(window_spec, "wrapper_object"):
        return window_spec.wrapper_object()
    return window_spec


def _safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _get_window_text(wrapper: Any) -> str:
    return str(_safe_call(wrapper.window_text, "") or "").strip()


def _get_uia_control_type(wrapper: Any) -> str:
    """UIA ControlType (예: Button, Edit). element_info.control_type 속성만 사용합니다."""
    return str(_safe_call(lambda: wrapper.element_info.control_type, "") or "").strip()


def _get_control_id(wrapper: Any) -> str:
    """UIA/Win32 ControlId (숫자 ID). wrapper.control_type()가 아닌 element_info.control_id 입니다."""
    value = _safe_call(lambda: wrapper.element_info.control_id, None)
    if value is None:
        return ""
    return str(value).strip()


def _get_auto_id(wrapper: Any) -> str:
    """AutomationId (UIA auto_id)."""
    return str(_safe_call(lambda: wrapper.element_info.automation_id, "") or "").strip()


def _format_window_summary(wrapper: Any, index: int) -> str:
    handle = _safe_call(lambda: wrapper.handle, None) or _safe_call(lambda: wrapper.element_info.handle, None)
    return (
        f"[{index}] title={_get_window_text(wrapper) or '-'}, "
        f"auto_id={_get_auto_id(wrapper) or '-'}, "
        f"control_id={_get_control_id(wrapper) or '-'}, "
        f"uia_type={_get_uia_control_type(wrapper) or '-'}, "
        f"hwnd={handle or '-'}, "
        f"visible={_safe_call(wrapper.is_visible, False)}"
    )


def _node_identity(node: Any) -> str:
    """중복 제거용 노드 식별자."""
    runtime_id = _safe_call(lambda: tuple(node.element_info.runtime_id or ()), None)
    if runtime_id:
        return f"runtime:{runtime_id}"
    handle = _safe_call(lambda: node.element_info.handle, None) or _safe_call(lambda: node.handle, None)
    if handle:
        return f"hwnd:{handle}"
    return f"obj:{id(node)}"


def _list_child_search_roots(wrapper: Any) -> List[Any]:
    """
    Inspect에서 보이는 Find 같은 child window를 별도 search root로 수집합니다.
    click_app_by_attr의 child window 탐색과 동일하게 visible 필터는 쓰지 않습니다.
    """
    candidates: List[Any] = []
    raw_nodes = list(_safe_call(lambda: wrapper.children(), []) or [])
    raw_nodes.extend(_safe_call(lambda: wrapper.descendants(), []) or [])

    seen_ids: set[str] = set()
    for child in raw_nodes:
        node = _to_wrapper(child)
        if not _safe_call(lambda: node.exists(), False):
            continue

        node_id = _node_identity(node)
        if node_id in seen_ids:
            continue

        uia_type = _get_uia_control_type(node).lower()
        if uia_type and uia_type not in CHILD_SEARCH_ROOT_TYPES:
            continue

        seen_ids.add(node_id)
        candidates.append(node)
    return candidates


def _search_root_label(wrapper: Any, *, kind: str, index: int = 0) -> str:
    title = _get_window_text(wrapper) or "-"
    auto_id = _get_auto_id(wrapper) or "-"
    return f"{kind}[{index}](title={title}, auto_id={auto_id})"


def iter_search_roots(top_wrapper: Any) -> List[tuple[str, Any]]:
    """top + child window(Find 등) 각각을 search root로 반환합니다."""
    roots: List[tuple[str, Any]] = [(_search_root_label(top_wrapper, kind="top"), top_wrapper)]
    for index, child in enumerate(_list_child_search_roots(top_wrapper)):
        roots.append((_search_root_label(child, kind="child", index=index), child))
    return roots


def iter_search_nodes(wrapper: Any, *, include_root: bool = True) -> List[Any]:
    """
    click_app_by_attr와 동일하게 search_root + descendants() 노드를 반환합니다.
    """
    nodes: List[Any] = []
    if include_root:
        nodes.append(wrapper)
    descendants = _safe_call(wrapper.descendants, []) or []
    nodes.extend(descendants)
    return nodes


def node_to_record(wrapper: Any, *, index: int, search_root: str = "top") -> Dict[str, Any]:
    return {
        "index": index,
        "search_root": search_root,
        "title": _get_window_text(wrapper),
        "auto_id": _get_auto_id(wrapper),
        "control_id": _get_control_id(wrapper),
        "uia_control_type": _get_uia_control_type(wrapper),
        "visible": bool(_safe_call(wrapper.is_visible, False)),
    }


def collect_all_descendant_records(window_spec: Any, *, include_root: bool = True) -> List[Dict[str, Any]]:
    """
    선택한 top window와 그 아래 child window(Find 등) 각각에서
    root+descendants 노드를 수집합니다. Inspect 트리와의 차이를 줄이기 위함입니다.
    """
    top_wrapper = _to_wrapper(window_spec)
    records: List[Dict[str, Any]] = []
    seen_nodes: set[str] = set()
    global_index = 0

    for search_root, root_wrapper in iter_search_roots(top_wrapper):
        nodes = iter_search_nodes(root_wrapper, include_root=include_root)
        logger.info("search_root=%s nodes=%d", search_root, len(nodes))
        for node in nodes:
            node_id = _node_identity(node)
            if node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)
            records.append(node_to_record(node, index=global_index, search_root=search_root))
            global_index += 1

    return records


def print_descendant_records(records: List[Dict[str, Any]], *, window_label: str = "") -> None:
    prefix = f"{window_label} " if window_label else ""
    print(f"{prefix}descendants dump: total_nodes={len(records)}")
    for record in records:
        print(
            f"  [{record['index']}] search_root={record.get('search_root', '-')}, "
            f"title={record['title'] or '-'}, "
            f"auto_id={record['auto_id'] or '-'}, "
            f"control_id={record['control_id'] or '-'}, "
            f"uia_type={record['uia_control_type'] or '-'}, "
            f"visible={record['visible']}"
        )


def make_locator_key(wrapper: Any, index: int) -> str:
    """locator.yaml 키 이름을 window title/auto_id 기준으로 생성합니다."""
    title = _get_window_text(wrapper)
    if title:
        slug = re.sub(r"[^\w가-힣]+", "_", title, flags=re.UNICODE).strip("_").lower()
        if slug:
            return slug[:48]

    auto_id = _get_auto_id(wrapper)
    if auto_id:
        slug = re.sub(r"[^\w]+", "_", auto_id.lower()).strip("_")
        if slug:
            return slug[:48]

    return f"top_{index}"


def extract_window_info(window_spec: Any) -> Dict[str, Any]:
    """윈도우 기본 정보 추출"""
    wrapper = _to_wrapper(window_spec)
    return {
        "title": _get_window_text(wrapper),
        "control_id": _get_control_id(wrapper),
        "auto_id": _get_auto_id(wrapper),
        "uia_control_type": _get_uia_control_type(wrapper),
    }


def extract_elements(
    window_spec: Any,
    *,
    include_without_auto_id: bool = False,
    all_types: bool = False,
) -> Dict[str, Any]:
    """top 및 child search root별 descendants에서 주요 UI 요소를 추출합니다."""
    top_wrapper = _to_wrapper(window_spec)
    elements: Dict[str, Any] = {}
    seen_nodes: set[str] = set()

    for search_root, root_wrapper in iter_search_roots(top_wrapper):
        descendants = _safe_call(root_wrapper.descendants, []) or []
        logger.info("extract search_root=%s descendants=%d", search_root, len(descendants))

        for child in descendants:
            node_id = _node_identity(child)
            if node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)

            uia_type = _get_uia_control_type(child)
            auto_id = _get_auto_id(child)
            control_id = _get_control_id(child)
            name = _get_window_text(child)

            if not all_types and uia_type.lower() not in TARGET_TYPES:
                continue
            if not auto_id and not control_id and not include_without_auto_id:
                continue

            element_key = (
                auto_id
                or (f"control_id_{control_id}" if control_id else "")
                or f"{uia_type.lower()}_{name or len(elements)}"
            ).lower().replace(" ", "_")
            if element_key in elements:
                element_key = f"{element_key}_{len(elements)}"

            elements[element_key] = {
                "auto_id": auto_id,
                "control_id": control_id,
                "title": name,
                "uia_control_type": uia_type,
                "search_root": search_root,
                "description": f"{name} ({uia_type})" if name else uia_type,
            }

    return elements


def update_locator_yaml_entries(entries: Dict[str, Dict[str, Any]]) -> Path:
    """locator.yaml에 여러 top window 항목을 저장합니다."""
    locator_path = project_root / "config" / "locator.yaml"
    if locator_path.exists():
        with open(locator_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    for window_type, payload in entries.items():
        data[window_type] = payload

    locator_path.parent.mkdir(parents=True, exist_ok=True)
    with open(locator_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return locator_path


def _pick_target_window(windows: list[Any], *, window_index: Optional[int], title_contains: Optional[str]) -> Any:
    if window_index is not None:
        if window_index < 0 or window_index >= len(windows):
            raise IndexError(f"window-index {window_index} is out of range (0..{len(windows) - 1})")
        return windows[window_index]

    if title_contains:
        needle = title_contains.casefold()
        for win in windows:
            wrapper = _to_wrapper(win)
            title = _get_window_text(wrapper).casefold()
            if needle in title:
                return win

    for win in windows:
        wrapper = _to_wrapper(win)
        if _safe_call(wrapper.is_visible, False):
            return win

    return windows[0]


def resolve_target_windows(
    windows: list[Any],
    *,
    window_index: Optional[int],
    title_contains: Optional[str],
    single_window: bool,
) -> list[Any]:
    """기본은 모든 top window, --single/--window-index/--title-contains 시 1개만 선택."""
    if window_index is not None or title_contains or single_window:
        return [
            _pick_target_window(
                windows,
                window_index=window_index,
                title_contains=title_contains,
            )
        ]
    return list(windows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate UI Locators for the target application")
    parser.add_argument(
        "--type",
        default="active_window",
        help="단일 window 모드에서 locator.yaml 키 이름 (기본: active_window)",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="첫 visible top window 1개만 처리 (기본: 모든 top window)",
    )
    parser.add_argument(
        "--window-index",
        type=int,
        default=None,
        help="추출할 top window 인덱스 (app.windows() 순서)",
    )
    parser.add_argument(
        "--title-contains",
        default=None,
        help="제목에 포함된 문자열로 top window 선택",
    )
    parser.add_argument(
        "--list-windows",
        action="store_true",
        help="top window 목록만 출력하고 종료",
    )
    parser.add_argument(
        "--no-print-descendants",
        action="store_true",
        help="descendants dump 콘솔 출력 생략 (기본: 전체 출력)",
    )
    parser.add_argument(
        "--exclude-root",
        action="store_true",
        help="descendants dump 시 top window(root) 제외 (기본: root 포함)",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="descendants dump를 JSON 파일로 저장 (예: /tmp/descendants.json)",
    )
    parser.add_argument(
        "--include-no-auto-id",
        action="store_true",
        help="auto_id/control_id 없는 컨트롤도 yaml elements에 포함",
    )
    parser.add_argument(
        "--all-types",
        action="store_true",
        help="Button/Edit 등 필터 없이 모든 UIA 타입을 yaml elements에 포함",
    )
    parser.add_argument(
        "--dump-only",
        action="store_true",
        help="descendants dump만 출력하고 locator.yaml 은 갱신하지 않음",
    )
    args = parser.parse_args()

    config_path = project_root / "config" / "app_config.yaml"
    if not config_path.exists():
        print("ERROR: config/app_config.yaml 이 없습니다.")
        print("       config/app_config.yaml.example 을 복사해 executable_path 등을 설정하세요.")
        return 1

    try:
        import pywinauto  # noqa: F401
    except ImportError:
        print("ERROR: pywinauto가 설치되지 않았습니다. pip install -r requirements.txt")
        return 1

    launcher = get_launcher()
    try:
        print("애플리케이션 연결/실행 시도 중...")
        launcher.ensure_running()
        session = launcher.session
        print("연결 성공.")
    except Exception as e:
        print(f"ERROR: 애플리케이션 연결 실패: {e}")
        return 1

    try:
        windows = session.app.windows()
        print(f"top window {len(windows)}개 발견:")
        for i, win in enumerate(windows):
            print(f"  {_format_window_summary(_to_wrapper(win), i)}")

        if args.list_windows:
            return 0

        if not windows:
            print("ERROR: 대상 애플리케이션 윈도우가 없습니다.")
            return 1

        target_windows = resolve_target_windows(
            windows,
            window_index=args.window_index,
            title_contains=args.title_contains,
            single_window=args.single,
        )
        single_mode = len(target_windows) == 1 and (
            args.single or args.window_index is not None or bool(args.title_contains)
        )
        print(f"처리 대상 top window: {len(target_windows)}개")

        include_root = not args.exclude_root
        yaml_entries: Dict[str, Dict[str, Any]] = {}
        json_payload: List[Dict[str, Any]] = []

        for i, target_window in enumerate(target_windows):
            wrapper = _to_wrapper(target_window)
            window_label = _format_window_summary(wrapper, i)
            print(f"\n===== top window {i} =====")
            print(window_label)

            records = collect_all_descendant_records(target_window, include_root=include_root)
            if not args.no_print_descendants:
                print_descendant_records(records, window_label=f"[{i}]")

            locator_key = args.type if single_mode else make_locator_key(wrapper, i)
            json_payload.append(
                {
                    "locator_key": locator_key,
                    "window": extract_window_info(target_window),
                    "records": records,
                }
            )

            if args.dump_only:
                continue

            elements = extract_elements(
                target_window,
                include_without_auto_id=args.include_no_auto_id,
                all_types=args.all_types,
            )
            print(f"[{i}] yaml elements 추출: {len(elements)}개 (키={locator_key}, 필터 적용됨)")
            yaml_entries[locator_key] = {
                "window": extract_window_info(target_window),
                "elements": elements,
            }

        if args.json_out:
            out_path = Path(args.json_out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"JSON 저장: {out_path}")

        if args.dump_only:
            return 0

        locator_path = update_locator_yaml_entries(yaml_entries)
        print(f"SUCCESS: {len(yaml_entries)}개 window -> {locator_path}")
        for key in yaml_entries:
            print(f"  - {key}")
        return 0

    except Exception as e:
        print(f"ERROR: 추출 중 예외 발생: {e}")
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
