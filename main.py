import os
import sys
import argparse
import threading
import time
import re
import json
import math
import ctypes
import difflib
import shutil
import subprocess
from collections import Counter, deque
import webbrowser
import urllib.error
import urllib.parse
import urllib.request

import pyautogui
import pyperclip
import pygetwindow as gw

from dotenv import load_dotenv

from core.voice import speak, listen
from core.registry import SkillRegistry
from core.engine import JarvisEngine
from core.context_manager import global_context
from gui.app import run_gui as run_gui_app


# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv()

if not os.environ.get("GROQ_API_KEY"):
    print("Error: GROQ_API_KEY not found.")
    sys.exit(1)


# ============================================================
# FIND AND FOCUS BROWSER / YOUTUBE
# (used by the YouTube "play" command)
# ============================================================

def focus_browser_window():
    browser_window = None

    try:
        # First try to find YouTube.
        for window in gw.getAllWindows():
            title = (window.title or "").lower()

            if "youtube" in title:
                browser_window = window
                break

        # Otherwise find any supported browser.
        if browser_window is None:
            for window in gw.getAllWindows():
                title = (window.title or "").lower()

                if any(
                    name in title
                    for name in ("chrome", "edge", "firefox", "brave")
                ):
                    browser_window = window
                    break

    except Exception as e:
        print(f"[JARVIS] Window search error: {e}")
        return False

    if browser_window is None:
        print("[JARVIS] YouTube/browser window not found.")
        return False

    try:
        if browser_window.isMinimized:
            browser_window.restore()

        browser_window.activate()
        time.sleep(0.3)
        return True

    except Exception as e:
        print(f"[JARVIS] Could not focus browser: {e}")
        return False


# ============================================================
# FIND FIRST YOUTUBE VIDEO
# ============================================================

def get_first_youtube_video_url(search_text):
    try:
        search_url = (
            "https://www.youtube.com/results?search_query="
            + urllib.parse.quote_plus(search_text)
            # "sp=EgIQAQ%3D%3D" filters results to videos only
            + "&sp=EgIQAQ%253D%253D"
        )

        request = urllib.request.Request(
            search_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

        with urllib.request.urlopen(request, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")

        match = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', html)

        if match:
            return (
                "https://www.youtube.com/watch?v="
                + match.group(1)
                + "&autoplay=1"
            )

    except Exception as e:
        print(f"YouTube lookup error: {e}")

    return None


# ============================================================
# YOUTUBE DIRECT COMMAND HANDLER
# ============================================================

# active:  True once YouTube was opened/played, so a plain "search ..."
#          goes to YouTube.
# results: videos of the last search, so "open the second video" works.
YOUTUBE_STATE = {"active": False, "results": []}

YOUTUBE_VIDEO_FILTER = "&sp=EgIQAQ%253D%253D"      # videos only (no shorts/ads)

ORDINALS = {
    "first": 1, "1st": 1, "one": 1,
    "second": 2, "2nd": 2, "two": 2,
    "third": 3, "3rd": 3, "three": 3,
    "fourth": 4, "4th": 4, "four": 4,
    "fifth": 5, "5th": 5, "five": 5,
    "sixth": 6, "6th": 6, "six": 6,
    "seventh": 7, "7th": 7, "seven": 7,
    "eighth": 8, "8th": 8, "eight": 8,
    "ninth": 9, "9th": 9, "nine": 9,
    "tenth": 10, "10th": 10, "ten": 10,
}


def parse_youtube_html(html, limit=15):
    """Pull (video_id, title) pairs, in page order, out of a results page."""
    results, seen = [], set()

    for m in re.finditer(
        r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})"', html
    ):
        vid = m.group(1)
        if vid in seen:
            continue
        seen.add(vid)

        title = vid
        t = re.search(
            r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"',
            html[m.end():m.end() + 3000],
        )
        if t:
            try:
                title = json.loads('"' + t.group(1) + '"')
            except Exception:
                title = t.group(1)

        results.append((vid, title))
        if len(results) >= limit:
            return results

    if not results:                       # fallback: any video id
        for vid in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html):
            if vid not in seen:
                seen.add(vid)
                results.append((vid, vid))
                if len(results) >= limit:
                    break

    return results


def get_youtube_results(search_text, limit=15):
    """Search YouTube (videos only). Returns [(video_id, title), ...]."""
    try:
        request = urllib.request.Request(
            "https://www.youtube.com/results?search_query="
            + urllib.parse.quote_plus(search_text)
            + YOUTUBE_VIDEO_FILTER,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")
        return parse_youtube_html(html, limit)
    except Exception as e:
        print(f"YouTube results error: {e}")
        return []


def youtube_watch_url(video_id):
    return "https://www.youtube.com/watch?v=" + video_id + "&autoplay=1"


_ORDINAL_PATTERN = "|".join(sorted(ORDINALS, key=len, reverse=True)) + r"|\d{1,2}"


def parse_video_pick(query):
    """"open the second video" -> 2   (None if it is not such a command)"""
    m = re.match(
        r"^(?:open|play|click(?: on)?|select|watch|choose|go to|start)"
        r"(?: the)? (?:video |result |number |no )*"
        r"(" + _ORDINAL_PATTERN + r")(?: video| one| result| link)?$",
        query.lower().strip(),
    )
    if not m:
        return None

    token = m.group(1)
    if token in ORDINALS:
        return ORDINALS[token]
    return int(token)


def handle_video_pick_command(query):
    """After "search java tutorial videos": "open the second video"."""
    n = parse_video_pick(query)
    if n is None:
        return False

    results = YOUTUBE_STATE["results"]

    if not results:
        if "video" in query or "result" in query:
            speak("Search for videos first, for example search java "
                  "tutorial videos.")
            return True
        return False

    if n < 1 or n > len(results):
        speak(f"I only have {len(results)} results.")
        return True

    video_id, title = results[n - 1]
    print(f"JARVIS: Opening result {n}: {title} ({video_id})")
    speak(f"Opening video {n}. {title[:70]}")
    webbrowser.open(youtube_watch_url(video_id))
    return True


# ---------- SCROLL + CLICK ----------
#   "scroll down" / "scroll up" / "scroll down a lot"
#   "scroll to top" / "scroll to bottom"
#   "click" / "double click" / "right click"   (at the mouse position)

SCROLL_STEP = 800        # about 6 mouse-wheel notches
SCROLL_BIG = 2400


def point_mouse_at_active_window():
    """Move the mouse to the middle of the window you are working in,
    because the wheel scrolls whatever is under the mouse."""
    try:
        window = gw.getActiveWindow()
        title = ((window.title if window else "") or "").lower()
    except Exception:
        window, title = None, ""

    # In a YouTube session, scroll the browser even if it lost focus.
    if YOUTUBE_STATE["active"] and not any(
        b in title for b in BROWSER_NAMES + ("youtube",)
    ):
        if focus_browser_window():
            try:
                window = gw.getActiveWindow()
            except Exception:
                window = None

    if window is not None:
        try:
            pyautogui.moveTo(
                window.left + window.width // 2,
                window.top + window.height // 2,
            )
        except Exception as e:
            print(f"[SCROLL] Could not move mouse: {e}")


def handle_scroll_click_command(query):
    q = " ".join(
        w for w in query.lower().split()
        if w not in ("the", "please", "a", "bit", "little")
    )

    m = re.match(r"^(?:scroll|go|move|page) (down|up)(?: (lot|far|fast|more))?$", q)
    if q == "scroll":
        m = re.match(r"^(scroll)$", q)

    if m:
        direction = m.group(1)
        big = bool(m.lastindex and m.lastindex >= 2 and m.group(2) in ("lot", "far", "fast"))
        amount = SCROLL_BIG if big else SCROLL_STEP

        point_mouse_at_active_window()
        old = pyautogui.FAILSAFE
        pyautogui.FAILSAFE = False
        try:
            pyautogui.scroll(amount if direction == "up" else -amount)
        finally:
            pyautogui.FAILSAFE = old
        print(f"[SCROLL] {direction} {amount}")
        return True

    m = re.match(r"^(?:scroll |go )to (top|bottom)(?: of page)?$", q)
    if m:
        point_mouse_at_active_window()
        sign = 1 if m.group(1) == "top" else -1
        old = pyautogui.FAILSAFE
        pyautogui.FAILSAFE = False
        try:
            for _ in range(15):
                pyautogui.scroll(sign * 3000)
                time.sleep(0.03)
        finally:
            pyautogui.FAILSAFE = old
        print(f"[SCROLL] to {m.group(1)}")
        return True

    clicks = {
        "click": pyautogui.click,
        "left click": pyautogui.click,
        "double click": pyautogui.doubleClick,
        "right click": pyautogui.rightClick,
    }
    if q in clicks:
        clicks[q]()
        print(f"[CLICK] {q}")
        speak("Clicked.")
        return True

    return False


def handle_youtube_command(query):
    query = query.lower().strip()

    # Open YouTube.
    if query in (
        "open youtube",
        "launch youtube",
        "start youtube",
        "youtube",
        "open you tube",
        "launch you tube",
        "open utube",
    ):
        webbrowser.open("https://www.youtube.com")
        YOUTUBE_STATE["active"] = True

        global_context.set(
            app_type="browser",
            app_name="youtube",
        )

        speak("YouTube has been opened.")
        return True

    # "play ..."   -> opens and plays the first matching video.
    # "search ..." -> opens the YouTube search results page.
    search_text = None
    results_only = False

    if query.startswith("play "):
        search_text = query[len("play "):].strip()
    else:
        m = (
            re.match(
                r"^(search|find|look up|look for)"
                r"(?: youtube for| on youtube for| youtube| on youtube| for)? (.+)$",
                query,
            )
            or re.match(r"^(youtube)(?: search| find) (.+)$", query)
        )
        if m:
            verb, text = m.group(1), m.group(2).strip()
            wants_youtube = (
                "youtube" in query
                or verb == "youtube"
                or re.search(r"\bvideos?$", text) is not None
                or (verb == "search" and YOUTUBE_STATE["active"])
            )
            if wants_youtube:
                search_text = text
                results_only = True

    if not search_text:
        return False

    # Clean search text.
    remove_words = (
        " on youtube",
        " in youtube",
        " on youtube videos",
        " youtube videos",
    )

    for word in remove_words:
        if search_text.endswith(word):
            search_text = search_text[:-len(word)].strip()

    # Music commands.
    if search_text in (
        "songs",
        "song",
        "music",
        "some songs",
        "some music",
    ):
        search_text = "popular songs"

    if not search_text:
        return False

    # Create YouTube search URL.
    encoded_query = urllib.parse.quote_plus(search_text)

    youtube_url = (
        "https://www.youtube.com/results?search_query="
        + encoded_query
    )

    print(f"JARVIS: Searching YouTube for {search_text}")
    YOUTUBE_STATE["active"] = True

    global_context.set(
        app_type="browser",
        app_name="youtube",
    )

    if results_only:
        speak(f"Searching YouTube for {search_text}.")

        # Remember the results so "open the second video" works.
        YOUTUBE_STATE["results"] = get_youtube_results(search_text)
        print(f"[YOUTUBE] {len(YOUTUBE_STATE['results'])} results found.")

        # Same filter as the lookup, so the numbering matches the page.
        webbrowser.open(youtube_url + YOUTUBE_VIDEO_FILTER)
        speak("Say open the first video, or scroll down to see more.")
        return True

    speak(f"Playing {search_text} on YouTube.")

    # Find the first video and open it directly (no keyboard automation).
    results = get_youtube_results(search_text)
    YOUTUBE_STATE["results"] = results
    video_url = youtube_watch_url(results[0][0]) if results else None

    if video_url:
        print(f"JARVIS: Opening video {video_url}")
        webbrowser.open(video_url)
    else:
        print("JARVIS: Could not find a video, opening search results.")
        webbrowser.open(youtube_url)
        speak(
            "I could not find a video to play, so I opened "
            "the search results."
        )

    return True


# ============================================================
# APP OPEN COMMAND HANDLER (notepad, excel, ppt, word ...)
# ============================================================

def handle_app_command(query):
    query = query.lower().strip()

    if not query.startswith(("open ", "launch ", "start ")):
        return False

    apps = {
        "notepad": ("notepad.exe", "Notepad"),
        "excel": ("excel", "Excel"),
        "powerpoint": ("powerpnt", "PowerPoint"),
        "ppt": ("powerpnt", "PowerPoint"),
        "word": ("winword", "Word"),
        "calculator": ("calc.exe", "Calculator"),
        "paint": ("mspaint.exe", "Paint"),
    }

    for key, (exe, label) in apps.items():
        if key in query:
            try:
                if exe.endswith(".exe"):
                    subprocess.Popen(exe)
                else:
                    os.startfile(exe)
                speak(f"Opening {label}.")
            except Exception as e:
                print(f"App open error: {e}")
                speak(f"I could not open {label}.")
            return True

    return False


# ============================================================
# WHATSAPP: SEND MESSAGE / CALL ANY CONTACT
#
# Examples:
#   "send hi message to naziya"
#   "send hello to 9876543210"
#   "call mom on whatsapp"
#   "video call john on whatsapp"
#
# Calls need two small screenshots in the project folder:
#   voice_call.png  and  video_call.png
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Speech recognition often mishears names. Add the spellings it gives
# you (look at the "You said:" lines in the console) on the left, and
# the EXACT name as saved in your WhatsApp on the right.
NAME_ALIASES = {
    "naziya tahsil": "Naziya Tahsil",
    "najiya tehsin": "Naziya Tahsil",
    "nazia tehsin": "Naziya Tahsil",
    "naziya tehsin": "Naziya Tahsil",
    "nazia tahsil": "Naziya Tahsil",
    # Replace the right side with the exact name in your WhatsApp:
    "hemant gc": "Hemant GEC",
    "hemant gec": "Hemant GEC",
    "heman": "Hemant GEC",
}


def resolve_name(spoken):
    """Map a misheard name to the real WhatsApp name (fuzzy)."""
    spoken = spoken.lower().strip()

    if spoken in NAME_ALIASES:
        return NAME_ALIASES[spoken]

    close = difflib.get_close_matches(
        spoken, NAME_ALIASES.keys(), n=1, cutoff=0.75
    )
    if close:
        return NAME_ALIASES[close[0]]

    return spoken


def paste_text(text):
    """Type text reliably by pasting it (handles any characters)."""
    pyperclip.copy(text)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)


WA_HWND = None   # window handle of WhatsApp Desktop once found

BROWSER_NAMES = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi")


def is_whatsapp_title(title):
    """True only for the WhatsApp Desktop app, not a browser tab."""
    t = (title or "").lower().strip()
    if "whatsapp" not in t:
        return False
    return not any(b in t for b in BROWSER_NAMES)


def find_whatsapp_window():
    try:
        for w in gw.getAllWindows():
            if is_whatsapp_title(w.title):
                return w
    except Exception as e:
        print(f"[WHATSAPP] Window search error: {e}")
    return None


def whatsapp_is_foreground():
    try:
        fg = ctypes.windll.user32.GetForegroundWindow()
        if WA_HWND and fg == WA_HWND:
            return True

        w = gw.getActiveWindow()
        title = (w.title if w else "") or ""
        if is_whatsapp_title(title):
            return True

        print(f"[WHATSAPP] Foreground window is: '{title}'")
        return False
    except Exception as e:
        print(f"[WHATSAPP] Foreground check error: {e}")
        return False


def force_foreground(window):
    """Windows-level fallback when window.activate() is refused."""
    try:
        user32 = ctypes.windll.user32
        hwnd = window._hWnd
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        user32.keybd_event(0x12, 0, 0, 0)       # ALT down (unlocks focus)
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 2, 0)       # ALT up
    except Exception as e:
        print(f"[WHATSAPP] force foreground error: {e}")


def focus_whatsapp():
    """Bring WhatsApp Desktop to the front. True only if VERIFIED."""
    window = find_whatsapp_window()

    if window is None:
        try:
            os.startfile("whatsapp:")
        except Exception as e:
            print(f"[WHATSAPP] start error: {e}")
            return False
        time.sleep(6)
        window = find_whatsapp_window()

    if window is None:
        print("[WHATSAPP] Desktop window not found.")
        return False

    global WA_HWND
    WA_HWND = window._hWnd

    for _ in range(3):
        try:
            if window.isMinimized:
                window.restore()
            window.activate()
        except Exception as e:
            print(f"[WHATSAPP] activate warning: {e}")

        time.sleep(0.6)
        if whatsapp_is_foreground():
            return True

        force_foreground(window)
        time.sleep(0.6)
        if whatsapp_is_foreground():
            return True

    print("[WHATSAPP] Could not bring WhatsApp to the front.")
    return False


def open_chat_by_name(name):
    """Search the name inside WhatsApp and open the first result."""
    real_name = resolve_name(name)
    print(f"[WHATSAPP] Spoken '{name}' -> searching '{real_name}'")

    if not focus_whatsapp():
        return False

    pyautogui.hotkey("ctrl", "f")      # focus the search box
    time.sleep(1.0)
    pyautogui.hotkey("ctrl", "a")      # clear any old search text
    paste_text(real_name)
    time.sleep(2.0)                    # let results appear
    pyautogui.press("down")            # select first result
    time.sleep(0.5)
    pyautogui.press("enter")           # open chat
    time.sleep(1.5)
    return True


def open_chat_by_number(number):
    """Open a chat directly from a phone number."""
    digits = re.sub(r"\D", "", number)

    if len(digits) == 10:              # assume India
        digits = "91" + digits

    try:
        os.startfile(f"whatsapp://send?phone={digits}")
    except Exception as e:
        print(f"WhatsApp number open error: {e}")
        return False

    time.sleep(6)
    return focus_whatsapp()


def is_phone_number(text):
    return re.sub(r"[\s\-]", "", text).isdigit()


def click_call_button(kind):
    """Start a call. Uses WhatsApp shortcuts (no images needed):
    Ctrl+Shift+C = voice call, Ctrl+Shift+V = video call.
    If voice_call.png / video_call.png exist, clicking them is tried first.
    """
    is_video = (kind == "video call")
    icon_name = "video_call.png" if is_video else "voice_call.png"
    icon_path = os.path.join(BASE_DIR, icon_name)

    time.sleep(2.0)  # let the chat finish opening

    if os.path.exists(icon_path):
        try:
            pos = pyautogui.locateCenterOnScreen(icon_path, confidence=0.8)
            if pos:
                print(f"[WHATSAPP] Clicking {icon_name} at {pos}")
                pyautogui.click(pos)
                return
            print(f"[WHATSAPP] {icon_name} not found on screen.")
        except Exception as e:
            print(f"[WHATSAPP] Call icon click error: {e}")

    if not whatsapp_is_foreground():
        speak("WhatsApp lost focus, so I did not start the call.")
        return

    key = "v" if is_video else "c"
    print(f"[WHATSAPP] Pressing Ctrl+Shift+{key.upper()} to start the {kind}")

    # Press the keys slowly: WhatsApp can miss a very fast hotkey.
    old = pyautogui.FAILSAFE
    pyautogui.FAILSAFE = False
    try:
        pyautogui.keyDown("ctrl")
        time.sleep(0.15)
        pyautogui.keyDown("shift")
        time.sleep(0.15)
        pyautogui.keyDown(key)
        time.sleep(0.2)
        pyautogui.keyUp(key)
        time.sleep(0.1)
        pyautogui.keyUp("shift")
        pyautogui.keyUp("ctrl")
    finally:
        pyautogui.FAILSAFE = old


SEND_PATTERNS = (
    # "send hi message to naziya in whatsapp"
    r"send (?:a |the )?(.+?) (?:message |msg )?to (.+?)"
    r"(?: on whatsapp| in whatsapp)?$",
    # "kaise ho message to naziya in whatsapp"
    r"(.+?) (?:message|msg) to (.+?)"
    r"(?: on whatsapp| in whatsapp)?$",
)


def handle_whatsapp_command(query):
    query = query.lower().strip()

    # ---------- SEND MESSAGE ----------
    for pattern in SEND_PATTERNS:
        m = re.match(pattern, query)
        if not m:
            continue

        text = re.sub(r"\s*(message|msg)$", "", m.group(1)).strip()
        target = m.group(2).strip()

        if not text or not target:
            continue

        speak(f"Sending {text} to {target}.")

        if is_phone_number(target):
            ok = open_chat_by_number(target)
        else:
            ok = open_chat_by_name(target)

        if not ok:
            speak(
                "I could not bring WhatsApp to the front, "
                "so I did not send anything."
            )
            return True

        # Safety: never type unless WhatsApp is still in front.
        if not whatsapp_is_foreground():
            speak("WhatsApp lost focus, so I did not send the message.")
            return True

        paste_text(text)
        time.sleep(0.5)
        pyautogui.press("enter")
        speak("Done.")
        return True

    # ---------- CALL ----------
    #   "call hari", "voice call hari", "video call hari on whatsapp",
    #   "make a call to hari", "start a video call with hari", "phone hari"
    m = re.match(
        r"^(?:please )?(?:make a |do a |start a |give a )?"
        r"(video call|video calling|voice call|voice calling|call|calling|phone|dial)"
        r"(?: to| with)? (.+?)"
        r"(?: on whatsapp| in whatsapp| using whatsapp| through whatsapp)?$",
        query,
    )

    if m:
        kind = "video call" if "video" in m.group(1) else "voice call"
        print(f"[WHATSAPP] Call request: {kind} -> '{m.group(2).strip()}'")
        target = m.group(2).strip()

        if not target:
            return False

        speak(f"Calling {target} on WhatsApp.")

        if is_phone_number(target):
            ok = open_chat_by_number(target)
        else:
            ok = open_chat_by_name(target)

        if not ok:
            speak("I could not bring WhatsApp to the front.")
            return True

        click_call_button(kind)
        return True

    return False


# ============================================================
# CREATE FILE COMMAND HANDLER (no AI needed)
#
# Examples:
#   "create a file"                     -> new_file_<time>.txt
#   "create a python file"              -> new_file_<time>.py
#   "create a hello file"               -> hello.txt
#   "create a python file named test"   -> test.py
#   "create a file called notes"        -> notes.txt
# The file is saved on your Desktop and opened in Notepad.
# ============================================================

FILE_TYPES = {
    "python": ".py",
    "text": ".txt",
    "notepad": ".txt",
    "html": ".html",
    "java": ".java",
    "javascript": ".js",
    "css": ".css",
    "json": ".json",
    "csv": ".csv",
    "markdown": ".md",
    "batch": ".bat",
}


FILE_TYPES["txt"] = ".txt"

# The file you created or opened most recently, so you can say
# "write hello in the created file" or "delete this file".
LAST_FILE = {"path": None}
LAST_WORDS = {
    "created", "new", "last", "same", "this", "that",
    "current", "opened", "recent", "latest",
}
LAST_WORD_PATTERN = "|".join(sorted(LAST_WORDS))


def get_desktop_folder():
    home = os.path.expanduser("~")
    for path in (
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "Desktop"),
    ):
        if os.path.isdir(path):
            return path
    return home


def handle_file_command(query):
    query = query.lower().strip()

    m = re.match(
        r"^(?:create|make|new|write|generate) (?:a |an |one )?(?:new )?"
        r"(?:(\w+) )?(?:(\w+) )?file"
        r"(?: (?:named|called|with name|name) (.+))?$",
        query,
    )

    if not m:
        return False

    tokens = [t for t in (m.group(1), m.group(2)) if t]
    name = m.group(3)
    ext = ".txt"

    # "create hello txt file" -> name hello, type txt
    # "create a python file"  -> type python, no name
    leftover = []
    for t in tokens:
        if t in FILE_TYPES:
            ext = FILE_TYPES[t]
        else:
            leftover.append(t)

    if leftover and not name:
        name = " ".join(leftover)

    if name:
        name = re.sub(r"[^\w\-]+", "_", name).strip("_")

    if not name:
        name = "new_file_" + time.strftime("%H%M%S")

    folder = get_desktop_folder()
    path = os.path.join(folder, name + ext)

    counter = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{name}_{counter}{ext}")
        counter += 1

    try:
        open(path, "w", encoding="utf-8").close()
        LAST_FILE["path"] = path
        subprocess.Popen(["notepad.exe", path])
        speak(f"Created {os.path.basename(path)} on your desktop.")
        print(f"JARVIS: Created {path}")
    except Exception as e:
        print(f"File create error: {e}")
        speak("I could not create the file.")

    return True


# ============================================================
# FILE ACTIONS: write / read / open / copy / rename / delete
# Works on files on your Desktop, no AI needed.
#
#   "write hello world in hello file"   (adds a line)
#   "add good morning to hello file"
#   "read hello file"
#   "open hello file"
#   "copy hello file"  /  "copy hello file to backup"
#   "rename hello file to world"
#   "delete hello file"   (asks yes/no, goes to Recycle Bin)
# ============================================================

TEXT_EXTENSIONS = (
    ".txt", ".py", ".md", ".json", ".html", ".css", ".js",
    ".java", ".c", ".cpp", ".log", ".bat",
)

FILE_WORD = r"(?: text file| text| file)"


def safe_file_name(name):
    return re.sub(r"[^\w\-]+", "_", name).strip("_")


def resolve_user_file(raw_name):
    """Find a file on the Desktop from a spoken name. -> (path, folder)"""
    folder = get_desktop_folder()

    base = raw_name.lower().strip()
    base = re.sub(r"^the\s+", "", base)
    base = re.sub(r"\s+(?:text\s+)?file$", "", base).strip()

    if not base:
        return None, folder

    # Try the full spoken name first ("my notes"), then without "my/a/an".
    candidates = [base]
    stripped = re.sub(r"^(?:my|a|an)\s+", "", base).strip()
    if stripped and stripped != base:
        candidates.append(stripped)

    try:
        files = [
            f for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f))
        ]
    except Exception as e:
        print(f"Desktop list error: {e}")
        return None, folder

    stems = {
        re.sub(r"[^\w]+", "", os.path.splitext(f)[0].lower()): f
        for f in files
    }

    for name in candidates:
        key = re.sub(r"[^\w]+", "", name)

        for f in files:
            if f.lower() == name:
                return os.path.join(folder, f), folder

        if key in stems:
            return os.path.join(folder, stems[key]), folder

    for name in candidates:
        key = re.sub(r"[^\w]+", "", name)
        close = difflib.get_close_matches(key, stems.keys(), n=1, cutoff=0.8)
        if close:
            return os.path.join(folder, stems[close[0]]), folder

    return None, folder


def open_in_editor(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXTENSIONS:
        subprocess.Popen(["notepad.exe", path])   # never runs .py/.bat
    else:
        os.startfile(path)


def unique_path(folder, stem, ext):
    path = os.path.join(folder, stem + ext)
    counter = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem}_{counter}{ext}")
        counter += 1
    return path


def open_found_file(path):
    """Open a found file safely and tell the user which one."""
    ext = os.path.splitext(path)[1].lower()

    if ext in BLOCKED_EXTENSIONS:
        speak("I do not open program files with this command.")
        return True

    try:
        open_in_editor(path)
        LAST_FILE["path"] = path
        print(f"JARVIS: Opening {path}")
        speak(f"Opening {os.path.basename(path)}.")
    except Exception as e:
        print(f"File open error: {e}")
        speak("I could not open the file.")
    return True


def find_notepad_window(path):
    """Find the Notepad window that has this file open (or None)."""
    if not path:
        return None
    name = os.path.basename(path).lower()
    stem = os.path.splitext(name)[0]
    try:
        windows = gw.getAllWindows()
    except Exception as e:
        print(f"[FILES] Window search error: {e}")
        return None

    for key in (name, stem):
        for w in windows:
            title = (w.title or "").lower()
            if "notepad" in title and key in title:
                return w
    return None


def find_any_notepad_window():
    try:
        for w in gw.getAllWindows():
            if "notepad" in (w.title or "").lower():
                return w
    except Exception as e:
        print(f"[FILES] Window search error: {e}")
    return None


def focus_window(window):
    """Bring a window to the front. True only if it is verified in front."""
    def in_front():
        try:
            active = gw.getActiveWindow()
            return bool(active and active._hWnd == window._hWnd)
        except Exception:
            return False

    try:
        if window.isMinimized:
            window.restore()
        window.activate()
    except Exception as e:
        print(f"[FILES] activate warning: {e}")

    time.sleep(0.5)
    if in_front():
        return True

    force_foreground(window)
    time.sleep(0.5)
    return in_front()


def file_contains(path, text):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return text in f.read()
    except Exception:
        return False


def write_text_to_file(path, text):
    """Add a line to a file and make sure it really reaches the disk.

    If the file is open in Notepad, the text is typed into that window
    and saved with Ctrl+S, so the window and the file stay in sync.
    Otherwise it is written to disk and then opened in Notepad.
    Returns True when the text is confirmed in the file.
    """
    has_content = os.path.exists(path) and os.path.getsize(path) > 0
    window = find_notepad_window(path)

    if window is not None and focus_window(window):
        try:
            pyautogui.hotkey("ctrl", "end")
            time.sleep(0.2)
            if has_content:
                press_key_safely("enter")
            paste_text(text)
            pyautogui.hotkey("ctrl", "s")
            time.sleep(1.0)
        except Exception as e:
            print(f"[FILES] Notepad write error: {e}")
            return False
        return file_contains(path, text)

    try:
        with open(path, "a", encoding="utf-8") as f:
            if has_content:
                f.write("\n")
            f.write(text)
        if window is None:
            subprocess.Popen(["notepad.exe", path])   # show the result
    except Exception as e:
        print(f"File write error: {e}")
        return False

    return file_contains(path, text)


def move_to_recycle_bin(path):
    """Send a file to the Recycle Bin. Uses send2trash if installed,
    otherwise falls back to the built-in Windows shell call."""
    path = os.path.abspath(path)

    try:
        from send2trash import send2trash
        send2trash(path)
        return not os.path.exists(path)
    except ImportError:
        pass
    except Exception as e:
        print(f"send2trash error: {e}")

    try:
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        op = SHFILEOPSTRUCTW()
        op.hwnd = 0
        op.wFunc = 3                      # FO_DELETE
        op.pFrom = path + "\0"            # double-null terminated
        op.pTo = None
        # ALLOWUNDO (Recycle Bin) | NOCONFIRMATION | SILENT | NOERRORUI
        op.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return result == 0 and not os.path.exists(path)
    except Exception as e:
        print(f"Recycle bin error: {e}")
        return False


def handle_file_action_command(query):
    query = query.lower().strip()

    # ---------- WRITE / ADD TEXT ----------
    #   "write hello in hello file"
    #   "hello world in the created file"   (no verb needed)
    m = re.match(
        r"^(?:write|add|append|type) (.+) (?:in|into|to|on) (?:the |this |that )?(.+?)"
        + FILE_WORD + "$",
        query,
    ) or re.match(
        r"^(.+) (?:in|into|to|on) (?:the |this |that )?(" + LAST_WORD_PATTERN + ")"
        + FILE_WORD + "$",
        query,
    )
    if m:
        text, name = m.group(1).strip(), m.group(2).strip()
        created = False

        if name in LAST_WORDS:
            path = LAST_FILE["path"]
            if not path or not os.path.exists(path):
                speak("I have not created or opened a file yet. "
                      "Say create a file first.")
                return True
        else:
            path, folder = resolve_user_file(name)
            if path is None:
                stem = safe_file_name(name)
                if not stem:
                    return False
                path = os.path.join(folder, stem + ".txt")
                created = True

        LAST_FILE["path"] = path

        if write_text_to_file(path, text):
            print(f"[FILES] Wrote '{text}' to {path}")
            if created:
                speak(f"Created {os.path.basename(path)} and wrote {text}.")
            else:
                speak(f"Added {text} to {os.path.basename(path)}.")
        else:
            speak("I could not confirm the text was saved. "
                  "Please check the Notepad window.")
        return True

    # ---------- SAVE ----------
    #   "save" / "save file" / "save hello file"
    m = (
        re.match(r"^save(?: (?:it|this|the file|this file|file))?$", query)
        or re.match(r"^save (?:the |my )?(.+?)(?: text)? file$", query)
    )
    if m:
        name = (m.group(1) if m.lastindex else "") or ""
        name = name.strip()
        use_last = (not name) or (name in LAST_WORDS)

        if use_last:
            path = LAST_FILE["path"]
        else:
            path, _ = resolve_user_file(name)
            if not path:
                speak(f"I could not find {name} on your desktop.")
                return True

        window = find_notepad_window(path)
        if window is None and use_last:
            window = find_any_notepad_window()

        if window is None:
            speak("I could not find that file open in Notepad. "
                  "Say open the file first.")
            return True

        if not focus_window(window):
            speak("I could not bring Notepad to the front.")
            return True

        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.6)
        print("[FILES] Ctrl+S sent to Notepad")
        speak("Saved.")
        return True

    # ---------- READ ----------
    m = re.match(r"^read (?:the )?(.+?)" + FILE_WORD + "$", query)
    if m:
        path = find_file_anywhere(m.group(1))
        if not path:
            speak(f"I could not find {m.group(1)} on your computer.")
            return True
        if os.path.splitext(path)[1].lower() not in TEXT_EXTENSIONS + (".csv",):
            speak("I can only read text files, so I will open it instead.")
            try:
                open_in_editor(path)
            except Exception as e:
                print(f"File open error: {e}")
            return True
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(400).strip()
            if content:
                speak(f"{os.path.basename(path)} says: {content}")
            else:
                speak(f"{os.path.basename(path)} is empty.")
        except Exception as e:
            print(f"File read error: {e}")
            speak("I could not read the file.")
        return True

    # ---------- OPEN (searches the whole PC) ----------
    hint_exts = None
    open_query = re.sub(r"\s+dot\s+", ".", query)          # "resume dot pdf"
    open_query, desktop_only = split_desktop_location(open_query)

    m = re.match(r"^open (?:the )?file (?:named |called |name )?(.+)$", open_query)

    if not m:
        # "open resume.pdf" (a real file extension was said)
        m = re.match(
            r"^open (?:the )?(.+\.(?:pdf|docx?|pptx?|xlsx?|csv|txt|py|md|json"
            r"|mp4|mkv|avi|mov|mp3|wav|jpe?g|png|gif))$",
            open_query,
        )

    if not m:
        # "open b6 powerpoint presentation", "open java notes pdf"
        m = re.match(
            r"^open (?:the |my )?(.+?)((?: (?:" + "|".join(OPEN_HINTS) + r"))+)(?: file)?$",
            open_query,
        )
        if m:
            hint_exts = []
            for word in m.group(2).split():
                hint_exts.extend(OPEN_HINTS[word])
            hint_exts = tuple(hint_exts)

    if not m:
        m = re.match(r"^open (?:the )?(.+?)" + FILE_WORD + "$", open_query)

    if m:
        name = m.group(1).strip()

        if name in ("explorer", "manager", "explorer window"):
            return False

        print(f"[FILES] Looking for '{name}' (types: {hint_exts}, desktop: {desktop_only})")

        path = None
        if desktop_only:
            path = find_file_anywhere(name, hint_exts, roots=get_desktop_roots())
        if not path:
            path = find_file_anywhere(name, hint_exts)

        if not path:
            if set(name.split()) & APP_WORDS:
                return False
            speak(f"I could not find {name} on your computer.")
            return True

        return open_found_file(path)

    # ---------- DELETE (to Recycle Bin, with confirmation) ----------
    m = re.match(
        r"^(?:delete|remove) (?:the |this |that )?(.+?)" + FILE_WORD + "$", query
    )
    if m:
        name = m.group(1).strip()

        if name in LAST_WORDS:
            path = LAST_FILE["path"]
            if path and not os.path.exists(path):
                path = None
        else:
            path, _ = resolve_user_file(name)

        if not path:
            speak(f"I could not find {name} on your desktop.")
            return True

        speak(f"Do you want me to delete {os.path.basename(path)}? "
              "Say yes or no.")
        answer = (listen() or "").lower()
        print(f"[FILES] Delete confirmation heard: '{answer}'")

        if any(w in answer.split() for w in (
            "yes", "yeah", "yep", "haan", "sure", "confirm", "ok", "okay",
        )):
            # Close its Notepad window first so it cannot re-save the file.
            window = find_notepad_window(path)
            if window is not None:
                try:
                    window.close()
                    time.sleep(0.6)
                except Exception as e:
                    print(f"[FILES] Could not close Notepad window: {e}")

            if move_to_recycle_bin(path):
                if LAST_FILE["path"] == path:
                    LAST_FILE["path"] = None
                print(f"[FILES] Deleted {path}")
                speak("Deleted. You can restore it from the Recycle Bin.")
            else:
                speak("I could not delete the file.")
        else:
            speak("Okay, I did not delete it.")
        return True

    # ---------- COPY ----------
    m = re.match(
        r"^copy (?:the )?(.+?)" + FILE_WORD
        + r"(?: (?:to|as|named|called) (.+?))?$",
        query,
    )
    if m:
        path = find_file_anywhere(m.group(1))
        if not path:
            speak(f"I could not find {m.group(1)} on your computer.")
            return True

        folder = os.path.dirname(path)
        stem, ext = os.path.splitext(os.path.basename(path))
        new_name = safe_file_name(m.group(2) or "")
        dest = unique_path(folder, new_name or stem + "_copy", ext)

        try:
            shutil.copy2(path, dest)
            speak(f"Copied to {os.path.basename(dest)}.")
        except Exception as e:
            print(f"File copy error: {e}")
            speak("I could not copy the file.")
        return True

    # ---------- RENAME ----------
    m = re.match(
        r"^rename (?:the )?(.+?)" + FILE_WORD
        + r" (?:to|as) (.+?)" + FILE_WORD + "?$",
        query,
    )
    if m:
        path, folder = resolve_user_file(m.group(1))
        if not path:
            speak(f"I could not find {m.group(1)} on your desktop.")
            return True

        new_name = safe_file_name(m.group(2))
        if not new_name:
            return False

        ext = os.path.splitext(path)[1]
        dest = os.path.join(folder, new_name + ext)

        if os.path.exists(dest):
            speak("A file with that name already exists.")
            return True

        try:
            os.rename(path, dest)
            speak(f"Renamed to {os.path.basename(dest)}.")
        except Exception as e:
            print(f"File rename error: {e}")
            speak("I could not rename the file.")
        return True

    return False


# ============================================================
# OPEN FOLDER COMMAND HANDLER (no AI needed)
#
#   "open downloads folder"
#   "open jarvis folder"      (finds Project_JARVIS-main etc.)
#   "open folder projects"
# Searches your Desktop, Documents, Downloads, Pictures, Music,
# Videos, the project folder and its parent (up to 3 levels deep).
# ============================================================

SKIP_DIRS = {
    "__pycache__", "node_modules", "site-packages", "venv", ".venv",
    "appdata", "$recycle.bin", "system volume information", "windows",
    "program files", "program files (x86)", "programdata",
}

# Also search other drives (D:\, E:\ ...) when finding files/folders.
# Set to False if searching is slow or you only use the C: drive.
SEARCH_OTHER_DRIVES = True

# Add any extra places to search, for example: [r"D:\Study", r"E:\Videos"]
EXTRA_SEARCH_FOLDERS = []

MAX_SEARCH_DEPTH = 4
MAX_SEARCH_ENTRIES = 60000


def norm_key(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def get_folder_roots():
    home = os.path.expanduser("~")
    roots = [BASE_DIR, os.path.dirname(BASE_DIR)]

    for sub in ("Desktop", "Documents", "Downloads",
                "Pictures", "Music", "Videos"):
        roots.append(os.path.join(home, "OneDrive", sub))
        roots.append(os.path.join(home, sub))

    roots.append(home)
    roots.extend(EXTRA_SEARCH_FOLDERS)

    if SEARCH_OTHER_DRIVES:
        for letter in "DEFGH":
            drive = letter + ":\\"
            if os.path.isdir(drive):
                roots.append(drive)

    unique, seen = [], set()
    for r in roots:
        r = os.path.normpath(r)
        if os.path.isdir(r) and r.lower() not in seen:
            seen.add(r.lower())
            unique.append(r)
    return unique


def find_folder(spoken, max_rank=3):
    key = norm_key(spoken)
    if not key:
        return None

    home = os.path.expanduser("~")
    roots = get_folder_roots()

    # Standard folders: open directly.
    special = {
        "download": "Downloads", "downloads": "Downloads",
        "document": "Documents", "documents": "Documents",
        "desktop": "Desktop",
        "picture": "Pictures", "pictures": "Pictures",
        "photos": "Pictures",
        "music": "Music", "songs": "Music",
        "video": "Videos", "videos": "Videos",
    }
    if key in special:
        sub = special[key]
        for base in (os.path.join(home, "OneDrive"), home):
            path = os.path.join(base, sub)
            if os.path.isdir(path):
                return path

    best = [None]
    scanned = [0]

    def consider(path, depth):
        k = norm_key(os.path.basename(path))
        if not k:
            return
        if k == key:
            rank = 0
        elif k.startswith(key):
            rank = 1
        elif key in k:
            rank = 2
        elif difflib.SequenceMatcher(None, key, k).ratio() >= 0.85:
            rank = 3
        else:
            return
        if rank > max_rank:
            return
        cand = (rank, depth, len(k), path)
        if best[0] is None or cand < best[0]:
            best[0] = cand

    def walk(path, depth):
        if depth > 3 or scanned[0] > 6000:
            return
        try:
            entries = list(os.scandir(path))
        except Exception:
            return
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except Exception:
                continue
            name = entry.name
            if name.startswith(".") or name.lower() in SKIP_DIRS:
                continue
            scanned[0] += 1
            consider(entry.path, depth)
            walk(entry.path, depth + 1)

    for root in roots:
        consider(root, 0)
        walk(root, 1)

    return best[0][3] if best[0] else None


# Words that tell Jarvis which kind of file you mean.
OPEN_HINTS = {
    "pdf": (".pdf",),
    "document": (".docx", ".doc"),
    "doc": (".docx", ".doc"),
    "word": (".docx", ".doc"),
    "presentation": (".pptx", ".ppt"),
    "ppt": (".pptx", ".ppt"),
    "powerpoint": (".pptx", ".ppt"),
    "excel": (".xlsx", ".xls", ".csv"),
    "spreadsheet": (".xlsx", ".xls", ".csv"),
    "python": (".py",),
    "video": (".mp4", ".mkv", ".avi", ".mov", ".wmv"),
    "music": (".mp3", ".wav", ".m4a", ".flac"),
    "song": (".mp3", ".wav", ".m4a", ".flac"),
    "image": (".jpg", ".jpeg", ".png", ".gif", ".webp"),
    "photo": (".jpg", ".jpeg", ".png", ".gif", ".webp"),
}

# Program files are never launched by "open ... file".
BLOCKED_EXTENSIONS = (".exe", ".msi", ".cmd", ".ps1", ".vbs", ".scr", ".com", ".jar")

# If a name contains one of these and no file is found, let the app
# or YouTube handlers deal with it instead.
APP_WORDS = {
    "notepad", "excel", "word", "powerpoint", "ppt", "calculator",
    "paint", "youtube", "whatsapp", "chrome", "explorer",
}


def get_desktop_roots():
    home = os.path.expanduser("~")
    roots = []
    for path in (
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "Desktop"),
    ):
        if os.path.isdir(path):
            roots.append(path)
    return roots


def split_desktop_location(text):
    """'b6 presentation on desktop' -> ('b6 presentation', True)"""
    m = re.search(
        r"\s+(?:on|in|from|at)\s+(?:the |my )?(?:desktop|destop|desk top|des)$",
        text,
    )
    if m:
        return text[:m.start()].strip(), True
    return text, False


def find_file_anywhere(spoken, hint_exts=None, roots=None, max_rank=3):
    """Search the PC for a file by spoken name. Returns a path or None."""
    name = re.sub(r"\s+dot\s+", ".", spoken.lower().strip())
    name = re.sub(r"^the\s+", "", name)
    name = re.sub(r"\s+(?:text\s+)?file$", "", name).strip()
    if not name:
        return None

    candidates = [name]
    stripped = re.sub(r"^(?:my|a|an)\s+", "", name).strip()
    if stripped and stripped != name:
        candidates.append(stripped)

    keys = [(c, norm_key(os.path.splitext(c)[0] if "." in c else c)) for c in candidates]
    keys = [(c, k) for c, k in keys if k]
    if not keys:
        return None

    best = [None]
    scanned = [0]
    visited = set()

    def consider(path, depth):
        fname = os.path.basename(path)
        stem, ext = os.path.splitext(fname)

        if hint_exts and ext.lower() not in hint_exts:
            return

        k = norm_key(stem)
        if not k:
            return

        for full, key in keys:
            if fname.lower() == full or k == key:
                rank = 0
            elif k.startswith(key):
                rank = 1
            elif key in k:
                rank = 2
            elif difflib.SequenceMatcher(None, key, k).ratio() >= 0.85:
                rank = 3
            else:
                continue

            if rank > max_rank:
                continue

            cand = (rank, depth, len(k), path)
            if best[0] is None or cand < best[0]:
                best[0] = cand

    def walk(path, depth):
        if depth > MAX_SEARCH_DEPTH or scanned[0] > MAX_SEARCH_ENTRIES:
            return

        real = os.path.normcase(os.path.abspath(path))
        if real in visited:
            return
        visited.add(real)

        try:
            entries = list(os.scandir(path))
        except Exception:
            return

        for entry in entries:
            scanned[0] += 1
            try:
                if entry.is_dir(follow_symlinks=False):
                    dname = entry.name.lower()
                    if dname.startswith(".") or dname in SKIP_DIRS:
                        continue
                    walk(entry.path, depth + 1)
                elif entry.is_file():
                    consider(entry.path, depth)
            except OSError:
                continue

    for root in (roots or get_folder_roots()):
        walk(root, 0)

    print(f"[FILES] Scanned {scanned[0]} items for '{spoken}'.")
    return best[0][3] if best[0] else None


def handle_folder_command(query):
    query = query.lower().strip()

    m = (
        re.match(r"^(?:open|show|launch|start) (?:the |my )?(.+?) folder$", query)
        or re.match(r"^(?:open|show) (?:the )?folder (?:named |called )?(.+)$", query)
    )
    if not m:
        return False

    name = m.group(1).strip()
    path = find_folder(name)

    if not path:
        speak(f"I could not find a folder named {name}.")
        return True

    try:
        os.startfile(path)
        print(f"JARVIS: Opening folder {path}")
        speak(f"Opening {os.path.basename(path)} folder.")
    except Exception as e:
        print(f"Folder open error: {e}")
        speak("I could not open the folder.")

    return True


def handle_open_anything_command(query):
    """"open b6", "open edu tutor on desktop": opens a matching file or
    folder if one exists. Otherwise returns False so the AI/engine can
    handle it (for example "open instagram")."""
    query = query.lower().strip()

    m = re.match(r"^open (?:the |my )?(.+)$", query)
    if not m:
        return False

    name, desktop_only = split_desktop_location(
        re.sub(r"\s+dot\s+", ".", m.group(1).strip())
    )

    if not name or set(name.split()) & APP_WORDS:
        return False

    # Only close matches (exact or "starts with") to avoid wrong opens.
    path = None
    if desktop_only:
        path = find_file_anywhere(name, roots=get_desktop_roots(), max_rank=1)
    if not path:
        path = find_file_anywhere(name, max_rank=1)

    if path:
        return open_found_file(path)

    folder = find_folder(name, max_rank=1)
    if folder:
        try:
            os.startfile(folder)
            print(f"JARVIS: Opening folder {folder}")
            speak(f"Opening {os.path.basename(folder)} folder.")
            return True
        except Exception as e:
            print(f"Folder open error: {e}")

    return False


# ============================================================
# PRESENTATION + HAND GESTURE CONTROL (slides)
#
# Voice commands (no camera needed):
#   "next slide" / "previous slide" / "first slide" / "last slide"
#   "go to slide 5"
#   "start slideshow" / "end slideshow"
#
# Gesture control (uses the webcam + MediaPipe):
#   "start gesture control"   /   "stop gesture control"
#
#   One finger up (index)         -> NEXT slide
#   Two fingers up (index+middle) -> PREVIOUS slide
#   Three fingers up              -> START slideshow (F5)
#   Fist held for 1.5 seconds     -> END slideshow (Esc)
#   Open hand                     -> rest / do nothing
#
# Show your palm to the camera with the fingers pointing up and
# hold the gesture for about half a second.
# ============================================================

PRESENTATION_WORDS = (
    "powerpoint", "slide show", "slideshow", "google slides",
    "presentation", "impress", "wps", "pptx", "ppt", "keynote",
)

# Gestures only press keys while a presentation window is in front,
# so arrow keys never go to some other app.  Set False to disable.
GESTURE_REQUIRE_PRESENTATION = True

GESTURE_ACTIONS = {
    "next": ("right", "NEXT SLIDE"),
    "previous": ("left", "PREVIOUS SLIDE"),
    "start": ("f5", "START SLIDESHOW"),
    "fist": ("esc", "END SLIDESHOW"),
}

GESTURE_HOLD_SECONDS = {
    "next": 0.5,
    "previous": 0.5,
    "start": 0.8,
    "fist": 1.5,
}

GESTURE_COOLDOWN = 0.8

HAND_MODEL_FILE = os.path.join(BASE_DIR, "hand_landmarker.task")
HAND_MODEL_URLS = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task",
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task",
)

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15),
    (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
)

# (name, knuckle index, middle-joint index, fingertip index)
FINGER_POINTS = (
    ("index", 5, 6, 8),
    ("middle", 9, 10, 12),
    ("ring", 13, 14, 16),
    ("pinky", 17, 18, 20),
)

_gesture_state = {"thread": None, "stop": None}


def classify_gesture(lm, aspect=1.0):
    """Turn 21 hand landmarks into a gesture name (or None).

    A finger counts as "up" when its tip is clearly farther from the
    wrist than its middle joint. This works even if the hand is tilted.
    The thumb is ignored on purpose.
    """
    def dist(a, b):
        return math.hypot((a.x - b.x) * aspect, a.y - b.y)

    wrist = lm[0]
    up = tuple(
        dist(lm[tip], wrist) > dist(lm[pip], wrist) * 1.2
        for _, _mcp, pip, tip in FINGER_POINTS
    )

    if up == (True, False, False, False):
        return "next"
    if up == (True, True, False, False):
        return "previous"
    if up == (True, True, True, False):
        return "start"
    if up == (False, False, False, False):
        return "fist"
    if up == (True, True, True, True):
        return "open"
    return None


class GestureTrigger:
    """Smooths gestures and fires each one once per hold."""

    def __init__(self):
        self.history = deque(maxlen=6)
        self.stable = None
        self.since = 0.0
        self.armed = True
        self.last_fire = 0.0

    def update(self, raw, now):
        """Returns (action or None, hold progress 0..1, stable gesture)."""
        self.history.append(raw)
        value, count = Counter(self.history).most_common(1)[0]

        # A gesture must be seen in 4 of the last 6 frames to count.
        if count >= 4 and value != self.stable:
            self.stable = value
            self.since = now
            self.armed = True       # a new gesture re-arms the trigger

        action = None
        progress = 0.0
        hold = GESTURE_HOLD_SECONDS.get(self.stable)

        if hold:
            if self.armed:
                progress = min(1.0, (now - self.since) / hold)
                if (
                    now - self.since >= hold
                    and now - self.last_fire >= GESTURE_COOLDOWN
                ):
                    action = self.stable
                    self.armed = False
                    self.last_fire = now
            else:
                progress = 1.0

        return action, progress, self.stable


def presentation_window_active():
    try:
        w = gw.getActiveWindow()
        title = ((w.title if w else "") or "").lower()
    except Exception:
        return False
    return any(word in title for word in PRESENTATION_WORDS)


def find_presentation_window():
    """Prefer a running slide show, then any presentation window."""
    try:
        windows = gw.getAllWindows()
    except Exception as e:
        print(f"[SLIDES] Window search error: {e}")
        return None

    for words in (
        ("slide show", "slideshow"),
        ("powerpoint", "pptx", ".ppt"),
        PRESENTATION_WORDS,
    ):
        for w in windows:
            title = (w.title or "").lower()
            if any(word in title for word in words):
                return w
    return None


def focus_presentation_window():
    window = find_presentation_window()
    if window is None:
        return False

    try:
        if window.isMinimized:
            window.restore()
        window.activate()
    except Exception as e:
        print(f"[SLIDES] activate warning: {e}")

    time.sleep(0.5)
    if not presentation_window_active():
        force_foreground(window)
        time.sleep(0.5)

    return presentation_window_active()


def press_key_safely(*keys):
    """Press keys without pyautogui's mouse-corner fail-safe interfering."""
    old = pyautogui.FAILSAFE
    pyautogui.FAILSAFE = False
    try:
        for key in keys:
            pyautogui.press(key)
    finally:
        pyautogui.FAILSAFE = old


def handle_presentation_command(query):
    query = query.lower().strip()
    words = query.split()

    # ---------- GESTURE CONTROL ON / OFF ----------
    if len(words) <= 5 and (
        "gesture" in query or "gestures" in query or "hand control" in query
    ):
        if any(w in words for w in ("stop", "disable", "off", "exit", "close", "end")):
            stop_gesture_control()
            return True
        if any(w in words for w in ("start", "enable", "begin", "activate", "on", "open", "launch")):
            start_gesture_control()
            return True

    # ---------- SLIDE COMMANDS ----------
    keys = None
    label = None

    m = re.match(r"^(?:go to |show |go )?(next|previous|back|first|last) slide$", query)
    if m:
        keys = {
            "next": ("right",), "previous": ("left",), "back": ("left",),
            "first": ("home",), "last": ("end",),
        }[m.group(1)]
        label = m.group(1) + " slide"

    elif re.match(
        r"^(?:start|begin|run) (?:the |my )?(?:slide ?show|presentation|slides)$",
        query,
    ):
        keys, label = ("f5",), "slideshow"

    elif re.match(
        r"^(?:end|stop|exit|close) (?:the |my )?(?:slide ?show|presentation)$",
        query,
    ):
        keys, label = ("esc",), "end of slideshow"

    else:
        m = re.match(r"^(?:go to |open |show )slide (?:number )?(\d{1,3})$", query)
        if not m:
            return False
        number = m.group(1)

        if not focus_presentation_window():
            speak("I could not find an open presentation.")
            return True

        pyautogui.write(number)
        press_key_safely("enter")
        speak(f"Slide {number}.")
        return True

    if not focus_presentation_window():
        speak("I could not find an open presentation. Open it first.")
        return True

    press_key_safely(*keys)
    print(f"[SLIDES] {label}")
    return True


def ensure_hand_model():
    """Return the path of the MediaPipe hand model, downloading it once."""
    if os.path.exists(HAND_MODEL_FILE) and os.path.getsize(HAND_MODEL_FILE) > 100000:
        return HAND_MODEL_FILE

    for url in HAND_MODEL_URLS:
        try:
            print(f"[GESTURE] Downloading hand model from {url}")
            urllib.request.urlretrieve(url, HAND_MODEL_FILE)
            if os.path.getsize(HAND_MODEL_FILE) > 100000:
                return HAND_MODEL_FILE
        except Exception as e:
            print(f"[GESTURE] Model download failed: {e}")

    return None


def keep_window_on_top(title):
    """Keep the camera preview above a full-screen slide show."""
    try:
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            # HWND_TOPMOST, no move, no resize, do not take focus
            ctypes.windll.user32.SetWindowPos(
                hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010
            )
    except Exception as e:
        print(f"[GESTURE] Could not keep window on top: {e}")


def gesture_worker(stop_event):
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
    except Exception as e:
        print(f"[GESTURE] Import error: {e}")
        speak(
            "Gesture control needs mediapipe and opencv. "
            "Please install them and try again."
        )
        return

    model_path = ensure_hand_model()
    if not model_path:
        speak(
            "I could not download the hand model. Please download "
            "hand_landmarker.task and put it in the project folder."
        )
        return

    try:
        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=model_path),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.6,
            min_hand_presence_confidence=0.6,
            min_tracking_confidence=0.6,
        )
        landmarker = vision.HandLandmarker.create_from_options(options)
    except Exception as e:
        print(f"[GESTURE] Could not start hand tracker: {e}")
        speak("I could not start the hand tracker.")
        return

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        landmarker.close()
        speak("I could not open the camera.")
        return

    window_name = "Jarvis Gesture Control (press Q here to stop)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 400, 300)
    cv2.moveWindow(window_name, 20, 20)
    try:
        cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
    except Exception:
        pass

    trigger = GestureTrigger()
    start_time = time.time()
    last_ts = -1
    status = "Show your hand"
    status_until = 0.0
    frame_count = 0
    last_seen = None
    last_warning = 0.0

    print("[GESTURE] Gesture control started.")

    try:
        while not stop_event.is_set():
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            frame = cv2.flip(frame, 1)        # mirror view
            height, width = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            ts = int((time.time() - start_time) * 1000)
            if ts <= last_ts:
                ts = last_ts + 1
            last_ts = ts

            result = landmarker.detect_for_video(mp_image, ts)

            raw = None
            points = None
            if result.hand_landmarks:
                points = result.hand_landmarks[0]
                raw = classify_gesture(points, width / height)

            now = time.time()
            action, progress, stable = trigger.update(raw, now)

            frame_count += 1
            if frame_count % 30 == 1:
                keep_window_on_top(window_name)

            if stable != last_seen:
                last_seen = stable
                print(f"[GESTURE] Seeing: {stable}")

            if action:
                allowed = (
                    (not GESTURE_REQUIRE_PRESENTATION)
                    or presentation_window_active()
                )

                # Camera window in front? Bring the slides forward first.
                if not allowed:
                    allowed = focus_presentation_window()

                if allowed:
                    key, label = GESTURE_ACTIONS[action]
                    press_key_safely(key)
                    status = label
                    print(f"[GESTURE] {label} (key: {key})")
                    try:
                        import winsound
                        winsound.Beep(1000, 60)
                    except Exception:
                        pass
                else:
                    status = "NO PRESENTATION FOUND"
                    print("[GESTURE] No presentation window found. "
                          "Open your PowerPoint file first.")
                    if now - last_warning > 10:
                        last_warning = now
                        speak("I cannot find your presentation. "
                              "Please open it first.")
                status_until = now + 2.5

            # ---------- preview window ----------
            if points:
                for a, b in HAND_CONNECTIONS:
                    cv2.line(
                        frame,
                        (int(points[a].x * width), int(points[a].y * height)),
                        (int(points[b].x * width), int(points[b].y * height)),
                        (0, 255, 0), 2,
                    )
                for p in points:
                    cv2.circle(
                        frame, (int(p.x * width), int(p.y * height)),
                        4, (0, 0, 255), -1,
                    )

            names = {
                "next": "ONE FINGER = NEXT",
                "previous": "TWO FINGERS = PREVIOUS",
                "start": "THREE FINGERS = START",
                "fist": "FIST (HOLD) = END",
                "open": "OPEN HAND",
            }
            seen = names.get(stable, "NO HAND" if not points else "...")
            cv2.putText(frame, seen, (10, 28), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (255, 255, 0), 2)

            if now < status_until:
                cv2.rectangle(frame, (0, height - 45), (width, height),
                              (0, 0, 0), -1)
                cv2.putText(frame, status, (10, height - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)

            if stable in GESTURE_HOLD_SECONDS:
                cv2.rectangle(frame, (10, 40), (10 + int(160 * progress), 52),
                              (0, 200, 0), -1)

            cv2.imshow(window_name, frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break

    except Exception as e:
        print(f"[GESTURE] Error: {e}")
    finally:
        cap.release()
        landmarker.close()
        cv2.destroyAllWindows()
        _gesture_state["thread"] = None
        print("[GESTURE] Gesture control stopped.")


def start_gesture_control():
    thread = _gesture_state["thread"]
    if thread is not None and thread.is_alive():
        speak("Gesture control is already on.")
        return

    stop_event = threading.Event()
    thread = threading.Thread(
        target=gesture_worker, args=(stop_event,), daemon=True
    )
    _gesture_state["stop"] = stop_event
    _gesture_state["thread"] = thread

    speak(
        "Starting gesture control. Open your presentation, then use one "
        "finger for next and two fingers for previous."
    )
    thread.start()


def stop_gesture_control():
    thread = _gesture_state["thread"]
    stop_event = _gesture_state["stop"]

    if thread is None or not thread.is_alive():
        speak("Gesture control is not running.")
        return

    stop_event.set()
    thread.join(timeout=3)
    speak("Gesture control stopped.")


# ============================================================
# MEDIA CONTROL (pause / play / volume / next / previous)
#
#   "pause" / "pause video"  ->  play/pause key
#   "play" / "resume"        ->  play/pause key
#   "volume up" / "volume down" / "mute"
#   "next song" / "previous song"
#
# Only exact phrases match, so "play alpha song" still goes to the
# YouTube handler. The play/pause key is a TOGGLE: it cannot tell
# whether the video is currently playing or paused.
# ============================================================

MEDIA_COMMANDS = {
    # play / pause (toggle key)
    "pause": ("playpause", "Paused."),
    "pause video": ("playpause", "Paused."),
    "pause the video": ("playpause", "Paused."),
    "pause music": ("playpause", "Paused."),
    "pause song": ("playpause", "Paused."),
    "play": ("playpause", "Playing."),
    "play video": ("playpause", "Playing."),
    "resume": ("playpause", "Resuming."),
    "resume video": ("playpause", "Resuming."),
    "resume music": ("playpause", "Resuming."),
    "continue": ("playpause", "Continuing."),
    "continue video": ("playpause", "Continuing."),
    "continue song": ("playpause", "Continuing."),
    "continue music": ("playpause", "Continuing."),
    "stop video": ("playpause", "Paused."),
    "stop music": ("playpause", "Paused."),
    # volume
    "volume up": ("volumeup", "Volume up."),
    "increase volume": ("volumeup", "Volume up."),
    "volume down": ("volumedown", "Volume down."),
    "decrease volume": ("volumedown", "Volume down."),
    "mute": ("volumemute", "Muted."),
    "unmute": ("volumemute", "Unmuted."),
    # tracks
    "next song": ("nexttrack", "Next song."),
    "next track": ("nexttrack", "Next song."),
    "previous song": ("prevtrack", "Previous song."),
    "previous track": ("prevtrack", "Previous song."),
}


# ---------- VOLUME + BRIGHTNESS ----------
#   "volume up" / "volume down"          (10% each time)
#   "increase volume by 20"
#   "set volume to 50"
#   "brightness up" / "brightness down"
#   "increase brightness by 20"
#   "set brightness to 70"
#   "max volume" / "minimum brightness"
#   "louder" / "quieter" / "brighter" / "dimmer"
#
# Brightness works on laptop screens out of the box. For an external
# monitor run:  pip install screen-brightness-control

LEVEL_STEP = 10          # percent changed by "up" / "down"
MIN_BRIGHTNESS = 5       # never go fully black


def tap_vk(vk, times):
    """Press a virtual key quickly (volume keys change volume by 2%)."""
    user32 = ctypes.windll.user32
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.01)


def set_volume_percent(level):
    level = max(0, min(100, level))
    tap_vk(0xAE, 50)                    # VK_VOLUME_DOWN x50 -> 0%
    tap_vk(0xAF, round(level / 2))      # VK_VOLUME_UP, 2% per press


def change_volume(delta):
    tap_vk(0xAF if delta > 0 else 0xAE, max(1, round(abs(delta) / 2)))


def run_powershell(command):
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, timeout=15,
        creationflags=0x08000000,       # no console window
    )


def get_brightness():
    try:
        import screen_brightness_control as sbc
        value = sbc.get_brightness()
        return int(value[0] if isinstance(value, list) else value)
    except Exception:
        pass

    try:
        out = run_powershell(
            "(Get-CimInstance -Namespace root/WMI "
            "-ClassName WmiMonitorBrightness).CurrentBrightness"
        )
        return int(out.stdout.strip().splitlines()[0])
    except Exception as e:
        print(f"[LEVEL] Could not read brightness: {e}")
        return None


def set_brightness(level):
    level = max(MIN_BRIGHTNESS, min(100, int(level)))

    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(level)
        return True
    except Exception:
        pass

    try:
        result = run_powershell(
            "(Get-CimInstance -Namespace root/WMI "
            "-ClassName WmiMonitorBrightnessMethods)"
            f".WmiSetBrightness(1,{level})"
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[LEVEL] Could not set brightness: {e}")
        return False


LEVEL_WORDS = {
    "louder": ("volume", "up", None),
    "quieter": ("volume", "down", None),
    "brighter": ("brightness", "up", None),
    "dimmer": ("brightness", "down", None),
}


def parse_level_command(query):
    """-> (kind, mode, value) or None. mode: up / down / set"""
    q = " ".join(
        w for w in query.lower().split()
        if w not in ("the", "please", "by", "percent", "%", "to", "at")
    )

    if q in LEVEL_WORDS:
        return LEVEL_WORDS[q]

    m = re.match(
        r"^(increase|raise|turn up|decrease|lower|reduce|turn down) "
        r"(volume|brightness)(?: (\d{1,3}))?$", q)
    if m:
        mode = "up" if m.group(1) in ("increase", "raise", "turn up") else "down"
        return m.group(2), mode, int(m.group(3)) if m.group(3) else None

    m = re.match(r"^(volume|brightness) (up|down)(?: (\d{1,3}))?$", q)
    if m:
        return m.group(1), m.group(2), int(m.group(3)) if m.group(3) else None

    m = re.match(r"^(?:set |change )?(volume|brightness) (\d{1,3})$", q)
    if m:
        return m.group(1), "set", int(m.group(2))

    m = re.match(r"^(max|maximum|full) (volume|brightness)$", q)
    if m:
        return m.group(2), "set", 100

    m = re.match(r"^(min|minimum|lowest) (volume|brightness)$", q)
    if m:
        return m.group(2), "set", 0

    return None


def handle_level_command(query):
    parsed = parse_level_command(query)
    if not parsed:
        return False

    kind, mode, value = parsed
    step = value if (value and mode != "set") else LEVEL_STEP

    if kind == "volume":
        if mode == "set":
            level = max(0, min(100, value))
            set_volume_percent(level)
            reply = f"Volume set to {level} percent."
        else:
            change_volume(step if mode == "up" else -step)
            reply = f"Volume {mode} by {step} percent."
        print(f"[LEVEL] {reply}")
        speak(reply)
        return True

    # brightness
    current = get_brightness()

    if mode == "set":
        target = value
    elif current is None:
        speak("I could not read the current brightness.")
        return True
    else:
        target = current + (step if mode == "up" else -step)

    target = max(MIN_BRIGHTNESS, min(100, target))

    if set_brightness(target):
        reply = f"Brightness set to {target} percent."
        print(f"[LEVEL] {reply}")
        speak(reply)
    else:
        speak(
            "I could not change the brightness. For an external monitor, "
            "install screen brightness control."
        )
    return True


def handle_media_command(query):
    query = query.lower().strip()

    # "pause the video" / "continue this video" -> "pause video" / "continue video"
    query = " ".join(
        w for w in query.split()
        if w not in ("the", "this", "that", "please", "it")
    )

    if query not in MEDIA_COMMANDS:
        return False

    key, reply = MEDIA_COMMANDS[query]

    # Volume is pressed several times for a noticeable change.
    presses = 5 if key in ("volumeup", "volumedown") else 1
    for _ in range(presses):
        press_key_safely(key)

    print(f"[MEDIA] {reply}")
    speak(reply)
    return True


# ============================================================
# GROQ FALLBACK (answers questions when Ollama is not running)
# ============================================================

GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
OLLAMA_FAIL_TEXT = "trouble connecting to my local ai brain"

_groq_state = {"model": None}


def groq_request(path, payload=None):
    """Call the Groq API (GET if no payload, POST otherwise)."""
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/" + path,
        data=json.dumps(payload).encode("utf-8") if payload else None,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ["GROQ_API_KEY"],
            "User-Agent": "Mozilla/5.0 JarvisAssistant",
        },
        method="POST" if payload else "GET",
    )
    with urllib.request.urlopen(request, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pick_groq_model():
    """Ask Groq which models are active and choose a chat model."""
    try:
        ids = [m["id"] for m in groq_request("models").get("data", [])]
    except Exception as e:
        print(f"Groq model list error: {e}")
        return None

    for preferred in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
        if preferred in ids:
            return preferred

    skip = ("whisper", "orpheus", "guard", "safeguard", "compound", "tts")
    for model_id in ids:
        if not any(s in model_id for s in skip):
            return model_id

    return None


def ask_groq(question):
    """Ask Groq's online model. Returns the answer text or None."""
    model = _groq_state["model"] or GROQ_MODEL

    for attempt in range(2):
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are Jarvis, a helpful voice assistant. Answer "
                        "in 2 to 3 short sentences of plain text. No "
                        "markdown, no lists, no emojis."
                    ),
                },
                {"role": "user", "content": question},
            ],
            "temperature": 0.5,
            "max_tokens": 1000,
        }

        if model.startswith("openai/gpt-oss"):
            payload["reasoning_effort"] = "low"

        try:
            data = groq_request("chat/completions", payload)
            answer = (data["choices"][0]["message"].get("content") or "")
            answer = answer.strip()
            if answer:
                _groq_state["model"] = model
                return answer
            print("Groq returned an empty answer.")
            return None

        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")[:300]
            except Exception:
                pass
            print(f"Groq error (model {model}): HTTP {e.code} {body}")

            # Model retired or not allowed -> pick a working one and retry.
            if e.code in (400, 403, 404) and attempt == 0:
                new_model = pick_groq_model()
                if new_model and new_model != model:
                    print(f"Switching Groq model to {new_model}")
                    model = new_model
                    continue
            return None

        except Exception as e:
            print(f"Groq error: {e}")
            return None

    return None


# ============================================================
# WAIT FOR WAKE WORD
# ============================================================

def wait_for_wake_word():
    wake_words = (
        "jarvis",
        "hey jarvis",
        "hello jarvis",
        "okay jarvis",
        "ok jarvis",
        "jarvis ji",
        "jarvis j",
    )

    while True:
        print("Waiting for wake word: Jarvis...")
        query = listen()

        if not query or query == "none":
            continue

        query = query.lower().strip()
        print(f"Wake-word listener heard: {query}")

        for wake_word in wake_words:
            if wake_word in query:
                print("Wake word detected!")
                return True


# ============================================================
# MAIN JARVIS LOOP
# ============================================================

def jarvis_loop(pause_event, registry, args):
    jarvis = JarvisEngine(registry)

    if args.text:
        print("JARVIS: Jarvis Online. Waiting for wake word...")
    else:
        speak("Jarvis Online. Waiting for my name.")

    awake = False  # becomes True after the wake word and stays True

    while True:
        if pause_event.is_set():
            time.sleep(0.5)
            continue

        # ---------- WAKE WORD (only when asleep) ----------
        if not awake:
            if args.text:
                try:
                    wake_query = input("WAITING FOR JARVIS: ").strip().lower()
                except EOFError:
                    break

                if "jarvis" not in wake_query:
                    print("Wake word not detected.")
                    continue
            else:
                if not wait_for_wake_word():
                    continue

            if pause_event.is_set():
                continue

            awake = True
            print("JARVIS: Wake word detected.")
            speak("Yes, how can I help?")

        # ---------- LISTEN FOR COMMAND ----------
        if args.text:
            try:
                user_query = input("COMMAND: ").strip().lower()
            except EOFError:
                break
        else:
            user_query = listen()

        # Stay awake silently if nothing was understood.
        if not user_query or user_query == "none":
            continue

        user_query = user_query.lower().strip()
        print(f"You said: {user_query}")

        # Remove the wake word only at the start/end, so names like
        # "open jarvis folder" keep the word "jarvis".
        clean_query = re.sub(
            r"^(?:(?:hey|hello|ok|okay)\s+)?jarvis(?:\s+ji)?[\s,]*|[\s,]*jarvis$",
            "",
            user_query,
        ).strip()
        normalized_command = " ".join(clean_query.split())

        if not normalized_command:
            continue

        # ---------- SLEEP ----------
        sleep_commands = (
            "go to sleep",
            "sleep",
            "stop listening",
            "sleep mode",
        )

        if normalized_command in sleep_commands:
            awake = False
            speak("Going to sleep. Say Jarvis to wake me.")
            continue

        # ---------- QUIT ----------
        quit_commands = (
            "quit",
            "exit",
            "shutdown",
            "close jarvis",
            "stop jarvis",
        )

        if normalized_command in quit_commands:
            print("Shutting down JARVIS...")
            speak("Shutting down. Goodbye.")
            break

        # ---------- DIRECT COMMANDS ----------
        if handle_level_command(normalized_command):
            continue

        if handle_media_command(normalized_command):
            continue

        if handle_video_pick_command(normalized_command):
            continue

        if handle_scroll_click_command(normalized_command):
            continue

        if handle_youtube_command(normalized_command):
            continue

        if handle_file_command(normalized_command):
            continue

        if handle_file_action_command(normalized_command):
            continue

        if handle_folder_command(normalized_command):
            continue

        if handle_whatsapp_command(normalized_command):
            continue

        if handle_presentation_command(normalized_command):
            continue

        if handle_app_command(normalized_command):
            continue

        if handle_open_anything_command(normalized_command):
            continue

        # ---------- AI ENGINE ----------
        try:
            print(f"Thinking: {normalized_command}")

            response = jarvis.run_conversation(normalized_command)

            # If Ollama is down, answer with Groq instead.
            if response and OLLAMA_FAIL_TEXT in response.lower():
                print("Ollama unavailable -> using Groq.")
                groq_answer = ask_groq(normalized_command)
                if groq_answer:
                    response = groq_answer

            if pause_event.is_set():
                continue

            if response:
                if args.text:
                    print(f"JARVIS: {response}")

                speak(response)

        except Exception as e:
            print(f"Main Loop Error: {e}")
            speak("I encountered a system error.")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="JARVIS AI Assistant")

    parser.add_argument(
        "--text",
        action="store_true",
        help="Run in text mode instead of voice mode",
    )

    args = parser.parse_args()

    # Pause event and skill registry.
    pause_event = threading.Event()
    registry = SkillRegistry()

    context = {
        "pause_event": pause_event,
        "registry": registry,
    }

    # Load skills.
    skills_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "skills",
    )

    registry.load_skills(skills_dir, context=context)

    # Start JARVIS voice thread.
    voice_thread = threading.Thread(
        target=jarvis_loop,
        args=(pause_event, registry, args),
        daemon=True,
    )

    voice_thread.start()

    print("[JARVIS] Voice command system started.")

    try:
        run_gui_app(pause_event)

    except KeyboardInterrupt:
        print("\n[JARVIS] Shutting down...")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()