import os
import time

import pyautogui
import win32gui
import win32con
import win32com.client

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(HERE, "icons")


# ---------------------------------------------------------------- focus
def _find_whatsapp_hwnd():
    found = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd).strip() == "WhatsApp":
            found.append(hwnd)

    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def focus_whatsapp(timeout=8):
    """Bring the WhatsApp desktop app to the front."""
    shell = win32com.client.Dispatch("WScript.Shell")
    end = time.time() + timeout
    launched = False
    while time.time() < end:
        hwnd = _find_whatsapp_hwnd()
        if hwnd:
            shell.SendKeys("%")  # tapping Alt lets SetForegroundWindow succeed
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            time.sleep(0.5)
            if win32gui.GetForegroundWindow() == hwnd:
                return hwnd
        elif not launched:
            os.startfile("whatsapp://")
            launched = True
        time.sleep(0.4)
    return None


# ---------------------------------------------------------------- search
def _query_variants(spoken):
    """
    Speech recognition often adds or drops letters ('hemanth' vs 'Hemant').
    Try the full spoken name first, then shorter prefixes of the first word.
    """
    spoken = spoken.strip()
    variants = [spoken]
    first = spoken.split()[0] if spoken.split() else spoken
    for cut in range(len(first) - 1, 2, -1):
        variants.append(first[:cut])
    seen, out = set(), []
    for v in variants:
        if v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _search_has_results():
    """Best effort: check if the search list shows any chat row."""
    try:
        from pywinauto import Desktop
        win = Desktop(backend="uia").window(title_re="^WhatsApp$")
        items = win.descendants(control_type="ListItem")
        return len(items) > 0
    except Exception:
        return True  # can't tell, so just try the first query


def open_chat(spoken_name):
    if not focus_whatsapp():
        return False

    for query in _query_variants(spoken_name):
        pyautogui.hotkey("ctrl", "f")      # focus WhatsApp search box
        time.sleep(0.6)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        pyautogui.write(query, interval=0.04)
        time.sleep(1.5)
        if _search_has_results():
            print(f"[CALL] Searching WhatsApp for '{query}'")
            pyautogui.press("down")
            pyautogui.press("enter")
            time.sleep(1.2)
            return True
    return False


# ---------------------------------------------------------------- call button
def _click_with_uia(video):
    try:
        from pywinauto import Desktop
        win = Desktop(backend="uia").window(title_re="^WhatsApp$")
        names = (["Video call", "Start video call"] if video
                 else ["Voice call", "Start voice call", "Call"])
        for n in names:
            btn = win.child_window(title=n, control_type="Button")
            if btn.exists(timeout=1):
                btn.click_input()
                return True
    except Exception as e:
        print(f"[CALL] UIA failed: {e}")
    return False


def _click_with_image(video):
    prefix = "video_call" if video else "voice_call"
    if not os.path.isdir(ICON_DIR):
        return False
    for fn in sorted(os.listdir(ICON_DIR)):
        if fn.startswith(prefix) and fn.endswith(".png"):
            for conf in (0.9, 0.8, 0.7):
                try:
                    pos = pyautogui.locateCenterOnScreen(os.path.join(ICON_DIR, fn), confidence=conf)
                except Exception:
                    pos = None
                if pos:
                    pyautogui.click(pos)
                    return True
    return False


def call_contact(spoken_name, video=False):
    spoken_name = (spoken_name or "").strip()
    if not spoken_name:
        return "I didn't catch who to call."

    if not open_chat(spoken_name):
        return "I couldn't find that contact in WhatsApp."

    if not focus_whatsapp():
        return "WhatsApp lost focus, so I did not start the call."

    if _click_with_uia(video) or _click_with_image(video):
        return f"Calling {spoken_name} on WhatsApp."

    return "I opened the chat but couldn't find the call button. Run capture_icon.py to save the call icon."