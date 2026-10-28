"""
Windows/core/computer_context.py

Tracks which application/window JARVIS is currently "talking to", so the
user doesn't have to repeat "in PowerPoint" on every command. Also keeps a
short history of previously focused apps so JARVIS can support
"go back to Chrome" style context switching.
"""

from dataclasses import dataclass, field
from typing import Optional, List
import time


@dataclass
class AppRef:
    process_name: str          # e.g. "POWERPNT.EXE"
    window_title: str          # e.g. "Presentation1 - PowerPoint"
    hwnd: Optional[int] = None # native window handle, filled by window_manager
    last_seen: float = field(default_factory=time.time)


class ComputerContext:
    """Singleton-style context. Import `context` from this module elsewhere."""

    def __init__(self):
        self.active: Optional[AppRef] = None
        self.history: List[AppRef] = []   # most-recent-first, excludes active
        self.last_action: Optional[dict] = None
        self.last_target: Optional[str] = None
        self.last_error: Optional[str] = None

    def set_active(self, app_ref: AppRef):
        """Called by window_manager whenever focus changes (open, switch, click-to-focus)."""
        if self.active and self.active.hwnd != app_ref.hwnd:
            self.history = [a for a in self.history if a.hwnd != self.active.hwnd]
            self.history.insert(0, self.active)
            self.history = self.history[:10]
        self.active = app_ref

    def get_previous(self) -> Optional[AppRef]:
        return self.history[0] if self.history else None

    def find_in_history(self, name_fragment: str) -> Optional[AppRef]:
        name_fragment = name_fragment.lower()
        candidates = [self.active] if self.active else []
        candidates += self.history
        for ref in candidates:
            if ref and (name_fragment in ref.process_name.lower()
                        or name_fragment in ref.window_title.lower()):
                return ref
        return None

    def record_action(self, action: dict, target: Optional[str], error: Optional[str] = None):
        self.last_action = action
        self.last_target = target
        self.last_error = error

    def snapshot(self) -> dict:
        return {
            "active_application": self.active.process_name if self.active else None,
            "active_window_title": self.active.window_title if self.active else None,
            "last_action": self.last_action,
            "last_target": self.last_target,
            "last_error": self.last_error,
        }


context = ComputerContext()