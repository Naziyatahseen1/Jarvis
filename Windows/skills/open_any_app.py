"""
open_any_app.py

Generic Windows app launcher. Finds and opens ANY app that appears in the
Start Menu -- this includes normal desktop apps (Notepad, Chrome, VS Code),
Store/UWP apps (WhatsApp, Spotify, Calculator UWP), and anything with a
shortcut in the Start Menu folders.

Test it directly from PowerShell:
    python open_any_app.py whatsapp
    python open_any_app.py excel
    python open_any_app.py calculator
    python open_any_app.py "vs code"

Once you confirm it works, this same logic goes into skills/system_ops.py
(already provided) so JARVIS can call it as a tool.
"""

import subprocess
import json
import difflib
import sys
from typing import List, Dict, Optional


def get_installed_apps() -> List[Dict[str, str]]:
    """
    Ask Windows for every app registered in the Start Menu.
    Covers classic desktop apps AND Store/UWP apps in one call.
    """
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-StartApps | ConvertTo-Json -Compress"
        ],
        capture_output=True,
        text=True,
        timeout=15
    )

    raw = result.stdout.strip()
    if not raw:
        print("WARNING: Get-StartApps returned nothing. Is PowerShell available?")
        return []

    data = json.loads(raw)

    # PowerShell returns a plain dict (not a list) if there's only one match
    if isinstance(data, dict):
        data = [data]

    apps = []
    for item in data:
        name = item.get("Name")
        app_id = item.get("AppID")
        if name and app_id:
            apps.append({"name": name, "app_id": app_id})

    return apps


def find_best_match(query: str, apps: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    query_lower = query.strip().lower()

    # 1. Exact match
    for app in apps:
        if app["name"].strip().lower() == query_lower:
            return app

    # 2. Substring match (either direction), prefer shortest name
    substring_matches = [
        app for app in apps
        if query_lower in app["name"].lower() or app["name"].lower() in query_lower
    ]
    if substring_matches:
        substring_matches.sort(key=lambda a: len(a["name"]))
        return substring_matches[0]

    # 3. Fuzzy match as last resort (handles slightly-off STT transcriptions)
    names = [app["name"] for app in apps]
    close = difflib.get_close_matches(query, names, n=1, cutoff=0.6)
    if close:
        for app in apps:
            if app["name"] == close[0]:
                return app

    return None


def open_app(app_name: str) -> dict:
    apps = get_installed_apps()
    match = find_best_match(app_name, apps)

    if not match:
        return {
            "status": "error",
            "app": app_name,
            "error": f"No installed app found matching '{app_name}'."
        }

    try:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{match['app_id']}"])
        return {"status": "success", "app": match["name"]}
    except Exception as e:
        return {"status": "error", "app": match["name"], "error": str(e)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python open_any_app.py <app name>")
        print("Example: python open_any_app.py whatsapp")
        sys.exit(1)

    app_name = " ".join(sys.argv[1:])
    print(f"Searching for: {app_name}")

    result = open_app(app_name)
    print(json.dumps(result, indent=2))