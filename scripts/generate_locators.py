import argparse
import json
import logging
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


def node_to_record(wrapper: Any, *, index: int) -> Dict[str, Any]:
    return {
        "index": index,
        "title": _get_window_text(wrapper),
        "auto_id": _get_auto_id(wrapper),
        "control_id": _get_control_id(wrapper),
        "uia_control_type": _get_uia_control_type(wrapper),
        "visible": bool(_safe_call(wrapper.is_visible, False)),
    }


def collect_all_descendant_records(window_spec: Any, *, include_root: bool = True) -> List[Dict[str, Any]]:
    """선택한 top window의 root(옵션) + descendants 전체를 레코드로 반환합니다."""
    wrapper = _to_wrapper(window_spec)
    nodes = iter_search_nodes(wrapper, include_root=include_root)
    return [node_to_record(node, index=i) for i, node in enumerate(nodes)]


def print_descendant_records(records: List[Dict[str, Any]]) -> None:
    print(f"descendants dump: total_nodes={len(records)}")
    for record in records:
        print(
            f"  [{record['index']}] title={record['title'] or '-'}, "
            f"auto_id={record['auto_id'] or '-'}, "
            f"control_id={record['control_id'] or '-'}, "
            f"uia_type={record['uia_control_type'] or '-'}, "
            f"visible={record['visible']}"
        )


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
    """주요 UI 요소 추출 (descendants 순회)"""
    wrapper = _to_wrapper(window_spec)
    elements: Dict[str, Any] = {}

    descendants = _safe_call(wrapper.descendants, []) or []
    logger.info("descendants count (wrapper.descendants only): %d", len(descendants))
    logger.info("search nodes count (root+descendants): %d", len(iter_search_nodes(wrapper)))

    for child in descendants:
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
            "description": f"{name} ({uia_type})" if name else uia_type,
        }

    return elements


def update_locator_yaml(window_type: str, window_info: Dict[str, Any], elements: Dict[str, Any]) -> Path:
    """locator.yaml 업데이트"""
    locator_path = project_root / "config" / "locator.yaml"
    if locator_path.exists():
        with open(locator_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    data[window_type] = {
        "window": window_info,
        "elements": elements,
    }

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate UI Locators for the target application")
    parser.add_argument(
        "--type",
        default="active_window",
        help="저장할 윈도우 키 이름 (기본: active_window)",
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
        "--print-all-descendants",
        action="store_true",
        help="선택 top window의 root+descendants 전체를 콘솔에 출력",
    )
    parser.add_argument(
        "--include-root",
        action="store_true",
        help="--print-all-descendants 시 top window(root)도 목록에 포함",
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

        target_window = _pick_target_window(
            windows,
            window_index=args.window_index,
            title_contains=args.title_contains,
        )
        wrapper = _to_wrapper(target_window)
        print(f"선택된 window: {_format_window_summary(wrapper, -1)}")

        records = collect_all_descendant_records(target_window, include_root=args.include_root)
        if args.print_all_descendants or args.json_out:
            print_descendant_records(records)
            if args.json_out:
                out_path = Path(args.json_out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"JSON 저장: {out_path}")

        if args.dump_only:
            return 0

        window_info = extract_window_info(target_window)
        elements = extract_elements(
            target_window,
            include_without_auto_id=args.include_no_auto_id,
            all_types=args.all_types,
        )
        print(f"yaml elements 추출: {len(elements)}개 (필터 적용됨)")

        locator_path = update_locator_yaml(args.type, window_info, elements)
        print(f"SUCCESS: {args.type} -> {locator_path}")
        return 0

    except Exception as e:
        print(f"ERROR: 추출 중 예외 발생: {e}")
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
