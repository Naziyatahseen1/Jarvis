"""
context_manager.py
-------------------
A tiny, thread-safe piece of shared state that tells the Gesture Controller
what the "active context" currently is (e.g. "browser watching youtube",
"powerpoint presenting", etc).

This is intentionally dumb. It does NOT talk to the LLM, Computer Agent, or
Browser Agent directly. Instead:

    1. User says "Open YouTube"
    2. Your existing LLM/command-understanding layer routes this to
       Browser Agent, which opens YouTube.
    3. Right after that succeeds, YOUR EXISTING CODE calls:

           context.set(app_type="browser", app_name="youtube")

    4. The Gesture Controller (running in its own thread) reads
       context.get() every time it recognizes a gesture, and uses it to
       decide what the gesture should DO.

This keeps the gesture module decoupled from your LLM/agent internals -
it only needs read access to "what's active right now".
"""

from dataclasses import dataclass
from threading import Lock
import time


@dataclass
class ActiveContext:
    app_type: str = "none"     # "browser" | "computer" | "none"
    app_name: str = "none"     # e.g. "youtube", "powerpoint", "chrome", "vscode"
    updated_at: float = 0.0


class ContextManager:
    """Singleton-style shared context. One instance shared across your app."""

    def __init__(self):
        self._lock = Lock()
        self._context = ActiveContext()

    def set(self, app_type: str, app_name: str = "none"):
        with self._lock:
            self._context = ActiveContext(
                app_type=app_type.lower(),
                app_name=app_name.lower(),
                updated_at=time.time(),
            )
        print(f"[ContextManager] Active context -> {app_type}:{app_name}")

    def clear(self):
        self.set("none", "none")

    def get(self) -> ActiveContext:
        with self._lock:
            return self._context


# A single shared instance your whole app can import.
# from context_manager import global_context
global_context = ContextManager()


if __name__ == "__main__":
    # quick manual test
    global_context.set("browser", "youtube")
    print(global_context.get())
    global_context.set("computer", "powerpoint")
    print(global_context.get())