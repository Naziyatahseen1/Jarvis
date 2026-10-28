"""
Windows/core/window_manager.py

Finds, focuses, switches, and closes windows. Uses pywinauto (wraps UIA +
Win32) plus win32gui/psutil for handle-level control.

Install: pip install pywinauto pywin32 psutil
"""

from typing import Optional, List
import time

from pywinauto.application import Application
import win32gui
import win32process
import psutil

from .computer_context import context, AppRef


def _proc_name_from_hwnd(hwnd: int) -> str:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name()
    except Exception:
        return "unknown"


def list_top_level_windows() -> List[dict]:
    results = []

    def _enum_cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            results.append({
                "hwnd": hwnd,
                "title": win32gui.GetWindowText(hwnd),
                "process": _proc_name_from_hwnd(hwnd),
            })
        return True

    win32gui.EnumWindows(_enum_cb, None)
    return results


def find_window(name_or_title_fragment: str) -> Optional[dict]:
    fragment = name_or_title_fragment.lower()
    for w in list_top_level_windows():
        if fragment in w["title"].lower() or fragment in w["process"].lower():
            return w
    return None


def focus_window(hwnd: int) -> bool:
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
        win32gui.SetForegroundWindow(hwnd)
        title = win32gui.GetWindowText(hwnd)
        process = _proc_name_from_hwnd(hwnd)
        context.set_active(AppRef(process_name=process, window_title=title, hwnd=hwnd))
        return True
    except Exception as e:
        context.record_action({"action": "focus_window"}, str(hwnd), error=str(e))
        return False


def switch_to(name_fragment: str) -> bool:
    ref = context.find_in_history(name_fragment)
    if ref and ref.hwnd and win32gui.IsWindow(ref.hwnd):
        return focus_window(ref.hwnd)

    found = find_window(name_fragment)
    if found:
        return focus_window(found["hwnd"])
    return False


def open_application(path_or_name: str, wait_seconds: float = 2.0) -> Optional[dict]:
    """
    NOTE: your project already has Windows/skills/open_any_app.py for this.
    Prefer calling that existing logic instead of this function where possible —
    this is only here so window_manager works standalone. Once you share
    open_any_app.py, I'll fold its logic in here (or have this call it) so
    there's one app-opening code path instead of two.
    """
    app = Application(backend="uia").start(path_or_name)
    time.sleep(wait_seconds)
    windows = [w for w in list_top_level_windows()
               if w["process"].lower() in path_or_name.lower()
               or path_or_name.lower() in w["process"].lower()]
    if windows:
        focus_window(windows[0]["hwnd"])
        return windows[0]
    return None


def close_window(hwnd: Optional[int] = None) -> bool:
    target_hwnd = hwnd or (context.active.hwnd if context.active else None)
    if not target_hwnd:
        return False
    try:
        win32gui.PostMessage(target_hwnd, 0x0010, 0, 0)  # WM_CLOSE
        return True
    except Exception as e:
        context.record_action({"action": "close_window"}, str(target_hwnd), error=str(e))
        return False