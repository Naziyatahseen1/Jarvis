"""
Windows/core/ui_inspector.py

Walks the active window's UI Automation tree and returns a flat list of
actionable elements. This is what makes JARVIS application-independent —
it asks Windows what's on screen instead of hardcoding per-app selectors.

Install: pip install pywinauto
"""

from dataclasses import dataclass
from typing import List, Optional
import time

from pywinauto import Desktop
from pywinauto.findwindows import ElementNotFoundError

from .computer_context import context

ACTIONABLE_TYPES = {
    "Button", "Edit", "ComboBox", "CheckBox", "RadioButton", "MenuItem",
    "Tab", "TabItem", "TreeItem", "ListItem", "Hyperlink", "Text",
    "Document", "Pane", "ToolBar", "Menu",
}

_cache = {"hwnd": None, "elements": [], "ts": 0.0}
_CACHE_TTL = 1.5


@dataclass
class UIElement:
    name: str
    control_type: str
    automation_id: str
    rectangle: tuple
    depth: int
    wrapper: object


def inspect_ui(max_depth: int = 6, force_refresh: bool = False) -> List[UIElement]:
    if not context.active or not context.active.hwnd:
        return []

    now = time.time()
    if (not force_refresh
            and _cache["hwnd"] == context.active.hwnd
            and now - _cache["ts"] < _CACHE_TTL):
        return _cache["elements"]

    try:
        window = Desktop(backend="uia").window(handle=context.active.hwnd)
    except ElementNotFoundError:
        return []

    elements: List[UIElement] = []

    def _walk(elem, depth):
        if depth > max_depth:
            return
        try:
            info = elem.element_info
            ctrl_type = info.control_type
            if ctrl_type in ACTIONABLE_TYPES:
                name = (info.name or "").strip()
                rect = info.rectangle
                elements.append(UIElement(
                    name=name,
                    control_type=ctrl_type,
                    automation_id=info.automation_id or "",
                    rectangle=(rect.left, rect.top, rect.right, rect.bottom),
                    depth=depth,
                    wrapper=elem,
                ))
            for child in elem.children():
                _walk(child, depth + 1)
        except Exception:
            pass

    _walk(window, 0)

    _cache.update({"hwnd": context.active.hwnd, "elements": elements, "ts": now})
    return elements


def find_element(
    target_text: str,
    control_type: Optional[str] = None,
    nth: Optional[int] = None,
) -> Optional[UIElement]:
    elements = inspect_ui()
    if control_type:
        elements = [e for e in elements if e.control_type.lower() == control_type.lower()]

    target_lower = target_text.lower().strip()

    if nth is not None:
        matching = [e for e in elements if not target_lower or target_lower in e.name.lower()]
        return matching[nth] if 0 <= nth < len(matching) else None

    for e in elements:
        if e.name.lower() == target_lower:
            return e
    for e in elements:
        if target_lower in e.name.lower():
            return e
    for e in elements:
        if target_lower in e.automation_id.lower():
            return e
    return None


def describe_ui_for_planner(max_items: int = 40) -> str:
    elements = inspect_ui()
    lines = [f'{e.control_type} "{e.name}"' for e in elements[:max_items] if e.name]
    if not lines:
        return "No labeled UI elements detected (may need visual fallback)."
    return "; ".join(lines)