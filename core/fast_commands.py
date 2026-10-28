
import os
import subprocess
import re


# ============================================================
# FAST COMMANDS
# These commands bypass Ollama completely.
# ============================================================

def handle_fast_command(user_prompt, registry):

    if not user_prompt:
        return None

    command = user_prompt.lower().strip()

    # Remove wake word
    command = re.sub(
        r"^\s*jarvis[\s,:-]*",
        "",
        command
    ).strip()

    # ========================================================
    # OPEN APPLICATIONS
    # ========================================================

    app_commands = {

        # Windows
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "command prompt": "cmd.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "file explorer": "explorer.exe",
        "explorer": "explorer.exe",

        # Microsoft Office
        "powerpoint": "powerpnt.exe",
        "microsoft powerpoint": "powerpnt.exe",
        "word": "winword.exe",
        "microsoft word": "winword.exe",
        "excel": "excel.exe",
        "microsoft excel": "excel.exe",
        "edge": "msedge.exe",
        "microsoft edge": "msedge.exe",

        # VS Code
        "vs code": "code.exe",
        "visual studio code": "code.exe",
    }

    # ========================================================
    # SPECIAL APPLICATIONS
    # ========================================================

    special_apps = {

        # Chrome
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        ],

        "google chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        ],

        # WhatsApp Desktop
        "whatsapp": [
            "explorer.exe",
            "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"
        ],

        # Microsoft Copilot
        "microsoft copilot": [
            "explorer.exe",
            "shell:AppsFolder\\Microsoft.Copilot_8wekyb3d8bbwe!App"
        ],

        "copilot": [
            "explorer.exe",
            "shell:AppsFolder\\Microsoft.Copilot_8wekyb3d8bbwe!App"
        ],
    }

    # ========================================================
    # NORMALIZE OPEN COMMAND
    # ========================================================

    open_patterns = [
        r"^open\s+(.+)$",
        r"^launch\s+(.+)$",
        r"^start\s+(.+)$",
        r"^run\s+(.+)$",
    ]

    app_name = None

    for pattern in open_patterns:

        match = re.match(pattern, command)

        if match:
            app_name = match.group(1).strip()
            break

    # User simply says application name
    if app_name is None:

        if command in app_commands:
            app_name = command

        elif command in special_apps:
            app_name = command

    # ========================================================
    # OPEN APPLICATION
    # ========================================================

    if app_name:

        app_name = re.sub(
            r"\bplease\b",
            "",
            app_name
        ).strip()

        # ----------------------------------------------------
        # SPECIAL APPLICATIONS
        # ----------------------------------------------------

        if app_name in special_apps:

            try:

                command_list = special_apps[app_name]

                subprocess.Popen(
                    command_list,
                    shell=False
                )

                print(
                    f"DEBUG: Fast command executed: "
                    f"open {app_name}"
                )

                return f"Opened {app_name}."

            except Exception as e:

                print(
                    f"DEBUG: Failed to open "
                    f"{app_name}: {e}"
                )

                return f"Could not open {app_name}."

        # ----------------------------------------------------
        # NORMAL WINDOWS APPLICATIONS
        # ----------------------------------------------------

        if app_name in app_commands:

            executable = app_commands[app_name]

            try:

                subprocess.Popen(
                    executable,
                    shell=True
                )

                print(
                    f"DEBUG: Fast command executed: "
                    f"open {app_name}"
                )

                return f"Opened {app_name}."

            except Exception as e:

                print(
                    f"DEBUG: Failed to open "
                    f"{app_name}: {e}"
                )

                return f"Could not open {app_name}."

    # ========================================================
    # CLOSE APPLICATIONS
    # ========================================================

    close_match = re.match(
        r"^(close|exit|quit)\s+(.+)$",
        command
    )

    if close_match:

        app_name = close_match.group(2).strip()

        process_names = {

            "notepad": "notepad.exe",
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",

            "powerpoint": "POWERPNT.EXE",
            "microsoft powerpoint": "POWERPNT.EXE",

            "word": "WINWORD.EXE",
            "microsoft word": "WINWORD.EXE",

            "excel": "EXCEL.EXE",
            "microsoft excel": "EXCEL.EXE",

            "whatsapp": "WhatsApp.exe",

            "calculator": "CalculatorApp.exe",
        }

        if app_name in process_names:

            process = process_names[app_name]

            try:

                result = subprocess.run(
                    [
                        "taskkill",
                        "/F",
                        "/IM",
                        process
                    ],
                    capture_output=True,
                    text=True
                )

                print(
                    f"DEBUG: Fast close command executed: "
                    f"{app_name}"
                )

                return f"Closed {app_name}."

            except Exception as e:

                print(
                    f"DEBUG: Failed to close "
                    f"{app_name}: {e}"
                )

                return f"Could not close {app_name}."

    # ========================================================
    # FILE EXPLORER
    # ========================================================

    if command in [
        "open my files",
        "open files",
        "open file explorer",
        "open explorer",
        "open windows explorer"
    ]:

        try:

            subprocess.Popen(
                ["explorer.exe"],
                shell=False
            )

            print(
                "DEBUG: Fast File Explorer command executed."
            )

            return "Opened File Explorer."

        except Exception as e:

            print(
                f"DEBUG: File Explorer error: {e}"
            )

            return "Could not open File Explorer."

    # ========================================================
    # SHOW DESKTOP
    # ========================================================

    if command in [
        "show desktop",
        "open desktop",
        "go to desktop"
    ]:

        try:

            subprocess.run(
                [
                    "powershell",
                    "-Command",
                    "(New-Object -ComObject Shell.Application).MinimizeAll()"
                ],
                capture_output=True
            )

            print(
                "DEBUG: Show desktop executed."
            )

            return "Showing desktop."

        except Exception as e:

            print(
                f"DEBUG: Show desktop error: {e}"
            )

            return "Could not show desktop."

    # ========================================================
    # LOCK COMPUTER
    # ========================================================

    if command in [
        "lock computer",
        "lock my computer",
        "lock pc"
    ]:

        try:

            subprocess.run(
                [
                    "rundll32.exe",
                    "user32.dll,LockWorkStation"
                ]
            )

            print(
                "DEBUG: Computer locked."
            )

            return "Computer locked."

        except Exception as e:

            print(
                f"DEBUG: Lock error: {e}"
            )

            return "Could not lock the computer."

    # ========================================================
    # NO FAST COMMAND
    # Send request to Ollama.
    # ========================================================

    return None