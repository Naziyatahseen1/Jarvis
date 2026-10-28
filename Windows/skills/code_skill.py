import os
import json
import subprocess
from typing import List, Dict, Any, Callable
from core.skill import Skill


class CodeSkill(Skill):
    """
    Lets JARVIS write code to a file and open it in VS Code.
    Example voice commands:
        "write a python hello world program"
        "create a javascript file that prints hello world"
        "write code to add two numbers in python"
    """

    # Where generated code files get saved.
    # Change this to any folder you like.
    CODE_DIR = os.path.expanduser(r"~\Documents\JarvisCode")

    LANGUAGE_EXTENSIONS = {
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "java": ".java",
        "c": ".c",
        "cpp": ".cpp",
        "c++": ".cpp",
        "csharp": ".cs",
        "c#": ".cs",
        "html": ".html",
        "css": ".css",
        "bash": ".sh",
        "shell": ".sh",
        "go": ".go",
        "rust": ".rs",
        "php": ".php",
        "ruby": ".rb",
        "sql": ".sql",
    }

    @property
    def name(self) -> str:
        return "code_skill"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "write_code_file",
                    "description": (
                        "Write source code to a file and open it in VS Code. "
                        "Use this whenever the user asks to write, create, or "
                        "generate a piece of code, a script, or a program "
                        "(e.g. 'write a python hello world program')."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filename": {
                                "type": "string",
                                "description": (
                                    "Name for the file, without extension "
                                    "(e.g. 'hello_world'). If not specified, "
                                    "use a short descriptive name."
                                )
                            },
                            "language": {
                                "type": "string",
                                "description": (
                                    "Programming language, e.g. 'python', "
                                    "'javascript', 'java', 'cpp'."
                                )
                            },
                            "code": {
                                "type": "string",
                                "description": "The full source code to write to the file."
                            }
                        },
                        "required": ["filename", "language", "code"]
                    }
                }
            }
        ]

    def get_functions(self) -> Dict[str, Callable]:
        return {
            "write_code_file": self.write_code_file
        }

    def _find_vscode_path(self):
        candidates = [
            os.path.expandvars(r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft VS Code\Code.exe"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def write_code_file(self, filename: str, language: str, code: str):
        try:
            os.makedirs(self.CODE_DIR, exist_ok=True)

            language_key = language.strip().lower()
            extension = self.LANGUAGE_EXTENSIONS.get(language_key, ".txt")

            # Sanitize filename a bit
            safe_filename = "".join(
                c for c in filename.strip() if c.isalnum() or c in ("_", "-", " ")
            ).strip().replace(" ", "_")

            if not safe_filename:
                safe_filename = "jarvis_code"

            full_filename = f"{safe_filename}{extension}"
            filepath = os.path.join(self.CODE_DIR, full_filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code)

            # Try to open it in VS Code
            vscode_path = self._find_vscode_path()

            if vscode_path:
                subprocess.Popen([vscode_path, filepath])
                opened_with = "vscode"
            else:
                # Fall back to opening with the default text editor
                os.startfile(filepath)
                opened_with = "default_editor"

            return json.dumps({
                "status": "success",
                "file": filepath,
                "language": language_key,
                "opened_with": opened_with
            })

        except Exception as e:
            return json.dumps({
                "status": "error",
                "error": str(e)
            })