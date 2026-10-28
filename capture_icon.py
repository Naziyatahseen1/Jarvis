import os
import sys
import time
import pyautogui

kind = sys.argv[1] if len(sys.argv) > 1 else "voice_call"   # or video_call
out_dir = os.path.join("skills", "whatsapp", "icons")
os.makedirs(out_dir, exist_ok=True)

print("Open any WhatsApp chat. Put your mouse ON the call icon (top right of the chat).")
for i in range(6, 0, -1):
    print(f"Capturing in {i}...")
    time.sleep(1)

x, y = pyautogui.position()
size = 36
img = pyautogui.screenshot(region=(x - size // 2, y - size // 2, size, size))
path = os.path.join(out_dir, f"{kind}.png")
img.save(path)
print("Saved", path)