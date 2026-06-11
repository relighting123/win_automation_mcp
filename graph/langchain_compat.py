"""LangChain runtime compatibility helpers for the automation graph."""

from __future__ import annotations

from typing import Any

import importlib

_lc_load_module = importlib.import_module("langchain_core.load.load")

_original_load = _lc_load_module.load
_original_loads = _lc_load_module.loads
_original_reviver_init = _lc_load_module.Reviver.__init__


def _load_with_explicit_allowed_objects(obj: Any, **kwargs: Any) -> Any:
    if kwargs.get("allowed_objects") is None:
        kwargs["allowed_objects"] = "core"
    return _original_load(obj, **kwargs)


def _loads_with_explicit_allowed_objects(text: str, **kwargs: Any) -> Any:
    if kwargs.get("allowed_objects") is None:
        kwargs["allowed_objects"] = "core"
    return _original_loads(text, **kwargs)


def _reviver_with_explicit_allowed_objects(self, allowed_objects=None, *args, **kwargs):
    if allowed_objects is None:
        allowed_objects = "core"
    return _original_reviver_init(self, allowed_objects, *args, **kwargs)


def apply_langchain_compat() -> None:
    """Suppress langchain_core load() default allowlist deprecation warnings."""
    _lc_load_module.load = _load_with_explicit_allowed_objects  # type: ignore[assignment]
    _lc_load_module.loads = _loads_with_explicit_allowed_objects  # type: ignore[assignment]
    _lc_load_module.Reviver.__init__ = _reviver_with_explicit_allowed_objects  # type: ignore[assignment]

    # `from langchain_core.load import load` keeps a separate eager import reference.
    import langchain_core.load as _lc_load_package

    _lc_load_package.load = _load_with_explicit_allowed_objects


apply_langchain_compat()
