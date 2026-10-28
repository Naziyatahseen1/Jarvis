"""
Windows/core/action_verifier.py

Never claim success without checking. Cheap structural checks per action
type rather than re-screenshotting everything.
"""

from typing import Optional
import time

from . import ui_inspector, window_manager
from .computer_context import context


class VerificationResult:
    def __init__(self, success: bool, reason: str):
        self.success = success
        self.reason = reason

    def __bool__(self):
        return self.success

    def __repr__(self):
        return f"<Verification success={self.success} reason={self.reason!r}>"


def _snapshot_names(force_refresh=True) -> set:
    return {e.name for e in ui_inspector.inspect_ui(force_refresh=force_refresh) if e.name}


def verify_click(target: str, before_names: set, settle_seconds: float = 0.4) -> VerificationResult:
    time.sleep(settle_seconds)
    after_names = _snapshot_names()
    if after_names != before_names:
        return VerificationResult(True, "UI changed after click.")
    return VerificationResult(False, "No detectable UI change after click; may still have worked.")


def verify_type_text(target_text: str) -> VerificationResult:
    summary = ui_inspector.describe_ui_for_planner()
    if target_text.strip() and target_text.strip() in summary:
        return VerificationResult(True, "Typed text found in current UI.")
    return VerificationResult(False, "Typed text not found in visible UI elements.")


def verify_close_window(hwnd: Optional[int]) -> VerificationResult:
    if hwnd is None:
        return VerificationResult(False, "No handle to verify against.")
    still_open = any(w["hwnd"] == hwnd for w in window_manager.list_top_level_windows())
    return VerificationResult(not still_open, "Window closed." if not still_open else "Window still open.")


def verify_switch_window(app_fragment: str) -> VerificationResult:
    if context.active and app_fragment.lower() in context.active.window_title.lower():
        return VerificationResult(True, f"Active window is now {context.active.window_title}.")
    if context.active and app_fragment.lower() in context.active.process_name.lower():
        return VerificationResult(True, f"Active process is now {context.active.process_name}.")
    return VerificationResult(False, "Active app/window does not match expected target.")


def verify_save(before_title: str) -> VerificationResult:
    time.sleep(0.5)
    if not context.active:
        return VerificationResult(False, "No active window to check.")
    after_title = context.active.window_title
    if before_title != after_title and ("*" in before_title and "*" not in after_title):
        return VerificationResult(True, "Unsaved-changes marker cleared from title bar.")
    if before_title == after_title:
        return VerificationResult(False, "Window title unchanged; save outcome unclear.")
    return VerificationResult(True, "Window title changed after save action.")