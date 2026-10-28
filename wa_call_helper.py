import sys
import time


def find_whatsapp(desktop):
    partial = None
    for w in desktop.windows():
        try:
            t = (w.window_text() or "").strip().lower()
        except Exception:
            continue
        if t == "whatsapp":
            return w
        if t.startswith("whatsapp") and partial is None:
            partial = w
    return partial


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else "voice"

    from pywinauto import Desktop
    desk = Desktop(backend="uia")
    names = []

    for _ in range(4):
        win = find_whatsapp(desk)
        if win is None:
            print("NO_WINDOW")
            time.sleep(1.5)
            continue

        names = []
        target = None

        for b in win.descendants(control_type="Button"):
            try:
                name = (b.window_text() or "").strip()
            except Exception:
                continue
            if not name:
                continue
            names.append(name)
            low = name.lower()

            if target is not None:
                continue
            if kind == "video":
                if "video" in low:
                    target = b
            else:
                if ("voice" in low or low in ("call", "audio call", "start call")) \
                        and "video" not in low:
                    target = b

        if target is not None:
            try:
                target.click_input()
            except Exception:
                target.invoke()
            print("CLICKED:", target.window_text())
            return 0

        time.sleep(1.5)   # WhatsApp builds its button list lazily; retry

    print("NOT_FOUND. Buttons seen:", names)
    return 1


if __name__ == "__main__":
    sys.exit(main())