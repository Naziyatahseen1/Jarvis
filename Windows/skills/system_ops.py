import os
import json
import subprocess
import difflib
import time
from typing import List, Dict, Any, Callable, Optional
from core.skill import Skill


class SystemSkill(Skill):

    def __init__(self):
        self._app_cache: List[Dict[str, str]] = []
        self._app_cache_time: float = 0
        self._cache_ttl_seconds: int = 300  # refresh every 5 min

    @property
    def name(self) -> str:
        return "system_skill"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "set_volume",
                    "description": "Set system volume (0-100)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "level": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 100
                            }
                        },
                        "required": ["level"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "open_app",
                    "description": "Open any installed application (desktop or Store app) or a common website on this Windows computer",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "app_name": {
                                "type": "string"
                            }
                        },
                        "required": ["app_name"]
                    }
                }
            }
        ]

    def get_functions(self) -> Dict[str, Callable]:
        return {
            "set_volume": self.set_volume,
            "open_app": self.open_app
        }

    def set_volume(self, level):
        try:
            level = max(0, min(100, int(level)))
            return json.dumps({"status": "success", "level": level})
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

    # ==============================================================
    # APP DISCOVERY (covers desktop shortcuts, Start Menu, UWP/Store)
    # ==============================================================

    def _get_installed_apps(self, force_refresh: bool = False) -> List[Dict[str, str]]:
        """
        Returns a list of {"name": ..., "app_id": ...} for every app
        registered in the Start Menu (classic desktop apps + UWP/Store apps).
        This is cached because calling PowerShell is slow (~1-2s).
        """
        now = time.time()
        if (not force_refresh
                and self._app_cache
                and (now - self._app_cache_time) < self._cache_ttl_seconds):
            return self._app_cache

        try:
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
                return self._app_cache  # keep stale cache rather than empty

            data = json.loads(raw)

            # Get-StartApps returns a single dict if there's only one result
            if isinstance(data, dict):
                data = [data]

            apps = []
            for item in data:
                app_name = item.get("Name")
                app_id = item.get("AppID")
                if app_name and app_id:
                    apps.append({"name": app_name, "app_id": app_id})

            self._app_cache = apps
            self._app_cache_time = now
            return apps

        except Exception:
            # If PowerShell fails for any reason, fall back to whatever we had
            return self._app_cache

    def _find_best_match(self, app_name: str, apps: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        query = app_name.strip().lower()

        # 1. Exact match
        for app in apps:
            if app["name"].strip().lower() == query:
                return app

        # 2. Substring match (query is contained in app name, or vice versa)
        substring_matches = [
            app for app in apps
            if query in app["name"].lower() or app["name"].lower() in query
        ]
        if substring_matches:
            # Prefer the shortest name match (usually the most "canonical" app)
            substring_matches.sort(key=lambda a: len(a["name"]))
            return substring_matches[0]

        # 3. Fuzzy match as a last resort
        names = [app["name"] for app in apps]
        close = difflib.get_close_matches(app_name, names, n=1, cutoff=0.6)
        if close:
            for app in apps:
                if app["name"] == close[0]:
                    return app

        return None

    def _launch_by_app_id(self, app_id: str) -> None:
        subprocess.Popen(
            ["explorer.exe", f"shell:AppsFolder\\{app_id}"]
        )

    # ==============================================================
    # OPEN APP
    # ==============================================================

    def open_app(self, app_name):
        try:
            original_name = app_name
            app_name = app_name.strip().lower()

            # ==============================
            # WEBSITES (fast path)
            # ==============================
            websites = {
                "youtube": "https://www.youtube.com",
                "youtube.com": "https://www.youtube.com",
                "google": "https://www.google.com",
                "google.com": "https://www.google.com",
                "instagram": "https://www.instagram.com",
                "facebook": "https://www.facebook.com",
                "github": "https://github.com",
                "gmail": "https://mail.google.com"
            }

            if app_name in websites:
                os.startfile(websites[app_name])
                return json.dumps({"status": "success", "app": app_name, "type": "website"})

            # ==============================
            # QUICK NATIVE COMMANDS (fast path, no PowerShell needed)
            # ==============================
            quick_map = {
                "notepad": ["notepad.exe"],
                "calculator": ["calc.exe"],
                "calc": ["calc.exe"],
                "paint": ["mspaint.exe"],
                "cmd": ["cmd.exe"],
                "command prompt": ["cmd.exe"],
                "powershell": ["powershell.exe"],
                "file explorer": ["explorer.exe"],
                "explorer": ["explorer.exe"],
            }

            if app_name in quick_map:
                subprocess.Popen(quick_map[app_name])
                return json.dumps({"status": "success", "app": app_name})

            # ==============================
            # GENERIC: search everything registered in the Start Menu
            # (covers all desktop apps + Store/UWP apps, e.g. WhatsApp)
            # ==============================
            apps = self._get_installed_apps()
            match = self._find_best_match(original_name, apps)

            if match:
                self._launch_by_app_id(match["app_id"])
                return json.dumps({
                    "status": "success",
                    "app": match["name"]
                })

            # Try once more with a forced cache refresh in case it's a
            # newly installed app that isn't in the cached list yet
            apps = self._get_installed_apps(force_refresh=True)
            match = self._find_best_match(original_name, apps)

            if match:
                self._launch_by_app_id(match["app_id"])
                return json.dumps({
                    "status": "success",
                    "app": match["name"]
                })

            return json.dumps({
                "status": "error",
                "app": original_name,
                "error": f"Could not find an installed app matching '{original_name}'."
            })

        except Exception as e:
            return json.dumps({
                "status": "error",
                "app": app_name,
                "error": str(e)
            })