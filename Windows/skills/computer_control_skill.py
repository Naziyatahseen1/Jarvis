"""
Windows/skills/computer_control_skill.py

This is the piece you register with your existing LLM tool/function-calling
layer in Windows/core/engine.py (or wherever that loop lives). It exposes
ONE tool to the planner — `computer_control` — that accepts the structured
action JSON from the spec, dispatches it to action_executor, verifies it,
and returns a plain-language result the LLM can relay to the user.

Register it the same way you register your other Windows/skills modules —
match whatever decorator/registration pattern skill.py / registry.py
already use (e.g. `@register_skill(...)`) once you share those two files.
"""

from typing import Optional, List
import time

from Windows.core import action_executor as exe
from Windows.core import action_verifier as ver
from Windows.core import ui_inspector, window_manager
from Windows.core.computer_context import context

DESTRUCTIVE_ACTIONS = {
    "delete_file", "delete_folder", "close_window",
    "send_email", "submit_form", "purchase", "run_command", "modify_settings",
}

def _needs_confirmation(action: dict) -> bool:
    name = action.get("action")
    if name == "close_window":
        title = context.active.window_title if context.active else ""
        return "*" in title or "unsaved" in title.lower()
    return name in DESTRUCTIVE_ACTIONS - {"close_window"}


class PendingConfirmation(Exception):
    def __init__(self, action: dict, message: str):
        self.action = action
        self.message = message
        super().__init__(message)


def computer_control(action: dict) -> dict:
    name = action.get("action")
    target = action.get("target")

    if _needs_confirmation(action) and not action.get("confirmed"):
        raise PendingConfirmation(
            action,
            f'This action ("{name}"{f" on \"{target}\"" if target else ""}) '
            f"is irreversible or sensitive. Confirm to proceed?"
        )

    try:
        result = _dispatch(action)
        verification = _verify(action, result)
        success = verification.success if verification else True
        message = "Done." if success else f"Action ran, but I couldn't confirm it worked: {verification.reason}"
        return {"success": success, "message": message,
                "verification": verification.reason if verification else "not verified"}
    except exe.ActionError as e:
        return {"success": False, "message": str(e), "verification": "failed before verification"}
    except Exception as e:
        return {"success": False, "message": f"Unexpected error: {e}", "verification": "error"}


def _dispatch(action: dict):
    name = action.get("action")
    target = action.get("target")

    if name == "click":
        before = {e.name for e in ui_inspector.inspect_ui(force_refresh=True) if e.name}
        exe.click(target, action.get("control_type"), action.get("nth"))
        return {"before_names": before}

    if name == "double_click":
        exe.double_click(target, action.get("control_type"), action.get("nth"))
    elif name == "right_click":
        exe.right_click(target, action.get("control_type"), action.get("nth"))
    elif name == "type_text":
        exe.type_text(action.get("text", ""), target)
    elif name == "press_key":
        exe.press_key(action.get("key", ""))
    elif name == "hotkey":
        exe.hotkey(action.get("keys", []))
    elif name == "scroll":
        exe.scroll(action.get("direction", "down"), action.get("amount", 3))
    elif name == "drag":
        exe.drag(action.get("source"), action.get("dest"))
    elif name == "select_text":
        exe.select_text(target)
    elif name == "copy":
        exe.copy()
    elif name == "paste":
        exe.paste()
    elif name == "open_menu":
        exe.open_menu(target)
    elif name == "close_window":
        title_before = context.active.window_title if context.active else ""
        hwnd_before = context.active.hwnd if context.active else None
        exe.close_window()
        return {"title_before": title_before, "hwnd_before": hwnd_before}
    elif name == "switch_window" or name == "focus_window":
        exe.switch_window(target)
    elif name == "wait":
        exe.wait(action.get("seconds", 1.0))
    elif name == "read_screen":
        return {"text": exe.read_screen()}
    elif name == "inspect_ui":
        return {"elements": exe.inspect_ui_action()}
    elif name == "open_application":
        window_manager.open_application(action.get("path_or_name", target))
    else:
        raise exe.ActionError(f'Unknown action "{name}".')

    return {}


def _verify(action: dict, dispatch_result: dict):
    name = action.get("action")
    if name == "click":
        return ver.verify_click(action.get("target", ""), dispatch_result.get("before_names", set()))
    if name == "type_text":
        return ver.verify_type_text(action.get("text", ""))
    if name == "close_window":
        return ver.verify_close_window(dispatch_result.get("hwnd_before"))
    if name in ("switch_window", "focus_window"):
        return ver.verify_switch_window(action.get("target", ""))
    if name == "hotkey" and action.get("keys", []) == ["CTRL", "S"]:
        return ver.verify_save(dispatch_result.get("title_before", ""))
    return None


def plan_and_execute(actions: List[dict]) -> List[dict]:
    results = []
    for action in actions:
        outcome = computer_control(action)
        results.append(outcome)
        if not outcome["success"]:
            break
        time.sleep(0.15)
    return results