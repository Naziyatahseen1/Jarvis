"""
Windows/core/action_executor.py

Generic action set: click, double_click, right_click, type_text, press_key,
hotkey, scroll, drag, select_text, copy, paste, open_menu, close_window,
switch_window, focus_window, wait, read_screen, inspect_ui.

Priority: UI Automation element first -> keyboard shortcut -> mouse/coordinate
fallback (Step 6 visual fallback lives at the bottom).

Install: pip install pywinauto pyautogui
"""

from typing import Optional
import time

import pyautogui
from pywinauto.keyboard import send_keys

from . import window_manager, ui_inspector
from .computer_context import context

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


class ActionError(Exception):
    pass


def _click_element(el: ui_inspector.UIElement, method: str = "left"):
    try:
        if method == "left":
            el.wrapper.click_input()
        elif method == "double":
            el.wrapper.double_click_input()
        elif method == "right":
            el.wrapper.right_click_input()
        return
    except Exception:
        pass
    l, t, r, b = el.rectangle
    cx, cy = (l + r) // 2, (t + b) // 2
    if method == "left":
        pyautogui.click(cx, cy)
    elif method == "double":
        pyautogui.doubleClick(cx, cy)
    elif method == "right":
        pyautogui.rightClick(cx, cy)


def _resolve(target: str, control_type: Optional[str] = None, nth: Optional[int] = None):
    el = ui_inspector.find_element(target, control_type=control_type, nth=nth)
    if not el:
        raise ActionError(f'Could not find UI element matching "{target}".')
    return el


def click(target: str, control_type: Optional[str] = None, nth: Optional[int] = None):
    el = _resolve(target, control_type, nth)
    _click_element(el, "left")
    context.record_action({"action": "click"}, target)


def double_click(target: str, control_type: Optional[str] = None, nth: Optional[int] = None):
    el = _resolve(target, control_type, nth)
    _click_element(el, "double")
    context.record_action({"action": "double_click"}, target)


def right_click(target: str, control_type: Optional[str] = None, nth: Optional[int] = None):
    el = _resolve(target, control_type, nth)
    _click_element(el, "right")
    context.record_action({"action": "right_click"}, target)


def type_text(text: str, target: Optional[str] = None):
    if target:
        el = _resolve(target, control_type="Edit")
        try:
            el.wrapper.set_focus()
        except Exception:
            _click_element(el, "left")
    send_keys(text.replace(" ", "{SPACE}"), with_spaces=True)
    context.record_action({"action": "type_text", "text": text}, target)


def press_key(key: str):
    send_keys(f"{{{key.upper()}}}")
    context.record_action({"action": "press_key", "key": key}, None)


def hotkey(keys: list):
    combo = "+".join(k.lower() for k in keys)
    pyautogui.hotkey(*[k.lower() for k in keys])
    context.record_action({"action": "hotkey", "keys": keys}, combo)


def scroll(direction: str = "down", amount: int = 3):
    clicks = amount if direction == "up" else -amount
    pyautogui.scroll(clicks)
    context.record_action({"action": "scroll", "direction": direction}, None)


def drag(source_target: str, dest_target: str):
    src = _resolve(source_target)
    dst = _resolve(dest_target)
    sl, st, sr, sb = src.rectangle
    dl, dt, dr, db = dst.rectangle
    pyautogui.moveTo((sl + sr) // 2, (st + sb) // 2)
    pyautogui.dragTo((dl + dr) // 2, (dt + db) // 2, duration=0.4)
    context.record_action({"action": "drag"}, f"{source_target} -> {dest_target}")


def select_text(target: Optional[str] = None):
    if target:
        el = _resolve(target, control_type="Edit")
        el.wrapper.set_focus()
    pyautogui.hotkey("ctrl", "a")
    context.record_action({"action": "select_text"}, target)


def copy():
    pyautogui.hotkey("ctrl", "c")
    context.record_action({"action": "copy"}, None)


def paste():
    pyautogui.hotkey("ctrl", "v")
    context.record_action({"action": "paste"}, None)


def open_menu(menu_name: str):
    el = _resolve(menu_name, control_type=None)
    _click_element(el, "left")
    context.record_action({"action": "open_menu"}, menu_name)


def close_window():
    ok = window_manager.close_window()
    context.record_action({"action": "close_window"}, None, error=None if ok else "close failed")


def switch_window(app_fragment: str):
    ok = window_manager.switch_to(app_fragment)
    context.record_action({"action": "switch_window"}, app_fragment, error=None if ok else "not found")
    if not ok:
        raise ActionError(f'Could not find a window matching "{app_fragment}".')


def focus_window(app_fragment: str):
    switch_window(app_fragment)


def wait(seconds: float = 1.0):
    time.sleep(seconds)
    context.record_action({"action": "wait", "seconds": seconds}, None)


def read_screen() -> str:
    return ui_inspector.describe_ui_for_planner()


def inspect_ui_action():
    return ui_inspector.inspect_ui(force_refresh=True)


def visual_click_fallback(description: str, screenshot_path: str = None):
    """
    Used only when ui_inspector finds nothing usable. Takes a screenshot;
    wire this to your existing screenshot_ops.py / a vision model call to
    turn `description` + the image into an (x, y) point, then click it.
    """
    path = screenshot_path or "_jarvis_fallback_screenshot.png"
    pyautogui.screenshot(path)
    raise ActionError(
        f'No UI Automation element found for "{description}". '
        f'Screenshot saved to {path} for visual analysis — '
        f'wire this function to your vision model to complete the fallback.'
    )