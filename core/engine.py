
import json
import ollama

from core.fast_commands import handle_fast_command
from core.registry import SkillRegistry


class JarvisEngine:

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

        # ====================================================
        # LOCAL OLLAMA CONFIGURATION
        # ====================================================

        self.model_name = "llama3.2:3b"

        self.system_instruction = (
            "You are Jarvis, a helpful and precise AI desktop assistant. "
            "Maintain natural conversation with the user and use previous "
            "conversation context when interpreting follow-up requests. "
            "Use the provided tools whenever an action is required. "
            "Do not describe a tool action without actually using the tool. "
            "After a tool successfully completes, give a short natural "
            "confirmation to the user."
        )

        # Persistent conversation history
        self.conversation_history = []

        # Keep history reasonably small
        self.max_history_messages = 20

    # ============================================================
    # BUILD MESSAGES
    # ============================================================

    def _build_messages(self, user_prompt: str):

        messages = [
            {
                "role": "system",
                "content": self.system_instruction
            }
        ]

        messages.extend(self.conversation_history)

        messages.append(
            {
                "role": "user",
                "content": user_prompt
            }
        )

        return messages

    # ============================================================
    # SAVE MESSAGE
    # ============================================================

    def _save_message(self, message):

        self.conversation_history.append(message)

        if len(self.conversation_history) > self.max_history_messages:
            self.conversation_history = (
                self.conversation_history[
                    -self.max_history_messages:
                ]
            )

    # ============================================================
    # CLEAR CONVERSATION
    # ============================================================

    def clear_conversation(self):

        self.conversation_history = []

    # ============================================================
    # GET TOOLS
    # ============================================================

    def _get_tools(self):

        try:

            tools_schema = self.registry.get_tools_schema()

            if not tools_schema:
                return []

            normalized_tools = []

            for tool in tools_schema:

                if (
                    isinstance(tool, dict)
                    and tool.get("type") == "function"
                    and "function" in tool
                ):
                    normalized_tools.append(tool)

                else:
                    print(
                        "DEBUG: Unsupported tool schema:",
                        tool
                    )

            return normalized_tools

        except Exception as e:

            print(
                f"DEBUG: Could not load tools: {e}"
            )

            return []

    # ============================================================
    # GET TOOL CALLS
    # ============================================================

    def _get_tool_calls(self, response_message):

        try:

            tool_calls = response_message.get(
                "tool_calls",
                []
            )

            if tool_calls:
                return tool_calls

        except Exception:
            pass

        return []

    # ============================================================
    # MAIN CONVERSATION
    # ============================================================

    def run_conversation(self, user_prompt: str):

        # ========================================================
        # FAST COMMAND PATH
        #
        # Simple commands are executed WITHOUT Ollama.
        # This makes commands such as:
        #
        # open WhatsApp
        # open Chrome
        # open Notepad
        #
        # much faster.
        # ========================================================

        try:

            fast_command_result = handle_fast_command(
                user_prompt,
                self.registry
            )

            if fast_command_result is not None:

                print(
                    "DEBUG: Fast command executed."
                )

                return str(
                    fast_command_result
                )

        except Exception as e:

            print(
                f"DEBUG: Fast command error: {e}"
            )

        # ========================================================
        # NORMAL OLLAMA PATH
        # ========================================================

        messages = self._build_messages(
            user_prompt
        )

        tools = self._get_tools()

        # ========================================================
        # FIRST OLLAMA REQUEST
        # ========================================================

        try:

            completion_kwargs = {
                "model": self.model_name,
                "messages": messages,

                # Smaller response = faster response
                "options": {
                    "num_predict": 150
                }
            }

            if tools:

                completion_kwargs["tools"] = tools

            print(
                f"DEBUG: Sending request to Ollama "
                f"model {self.model_name}"
            )

            response = ollama.chat(
                **completion_kwargs
            )

        except Exception as e:

            print(
                f"Ollama Error: {e}"
            )

            return (
                "I am having trouble connecting "
                "to my local AI brain, sir."
            )

        # ========================================================
        # GET RESPONSE MESSAGE
        # ========================================================

        response_message = response.get(
            "message",
            {}
        )

        tool_calls = self._get_tool_calls(
            response_message
        )

        # ========================================================
        # CASE 1:
        # AI WANTS TO USE TOOL
        # ========================================================

        if tool_calls:

            print(
                "DEBUG: Executing Tool..."
            )

            # ----------------------------------------------------
            # Save user request
            # ----------------------------------------------------

            self._save_message(
                {
                    "role": "user",
                    "content": user_prompt
                }
            )

            # ----------------------------------------------------
            # Save assistant tool-call message
            # ----------------------------------------------------

            assistant_tool_message = {
                "role": "assistant",
                "content": response_message.get(
                    "content",
                    ""
                ),
                "tool_calls": []
            }

            for tool_call in tool_calls:

                try:

                    function_data = tool_call.get(
                        "function",
                        {}
                    )

                    function_name = function_data.get(
                        "name"
                    )

                    function_arguments = function_data.get(
                        "arguments",
                        {}
                    )

                except Exception as e:

                    print(
                        f"DEBUG: Invalid tool call: {e}"
                    )

                    continue

                if function_arguments is None:
                    function_arguments = {}

                # Ollama can return arguments as JSON string
                if isinstance(
                    function_arguments,
                    str
                ):

                    try:

                        function_arguments = json.loads(
                            function_arguments
                        )

                    except json.JSONDecodeError:

                        print(
                            "DEBUG: Could not parse "
                            f"tool arguments: "
                            f"{function_arguments}"
                        )

                        function_arguments = {}

                assistant_tool_message[
                    "tool_calls"
                ].append(
                    {
                        "function": {
                            "name": function_name,
                            "arguments": function_arguments
                        }
                    }
                )

            self._save_message(
                assistant_tool_message
            )

            # ====================================================
            # EXECUTE EVERY TOOL
            # ====================================================

            for tool_call in tool_calls:

                try:

                    function_data = tool_call.get(
                        "function",
                        {}
                    )

                    function_name = function_data.get(
                        "name"
                    )

                    function_args = function_data.get(
                        "arguments",
                        {}
                    )

                except Exception as e:

                    print(
                        f"DEBUG: Invalid tool call: {e}"
                    )

                    continue

                if function_args is None:
                    function_args = {}

                # Parse JSON arguments
                if isinstance(
                    function_args,
                    str
                ):

                    try:

                        function_args = json.loads(
                            function_args
                        )

                    except json.JSONDecodeError:

                        print(
                            "DEBUG: Could not parse "
                            f"tool arguments: "
                            f"{function_args}"
                        )

                        function_args = {}

                print(
                    f"DEBUG: AI attempting to call: "
                    f"{function_name}"
                )

                print(
                    f"DEBUG: Tool arguments: "
                    f"{function_args}"
                )

                # ------------------------------------------------
                # Find function
                # ------------------------------------------------

                function_to_call = (
                    self.registry.get_function(
                        function_name
                    )
                )

                # ------------------------------------------------
                # Tool not found
                # ------------------------------------------------

                if not function_to_call:

                    res = (
                        "Error: Tool not found."
                    )

                    print(
                        f"DEBUG: Tool {function_name} "
                        "not found in registry."
                    )

                # ------------------------------------------------
                # Execute tool
                # ------------------------------------------------

                else:

                    try:

                        res = function_to_call(
                            **function_args
                        )

                        print(
                            f"DEBUG: Tool Output: "
                            f"{str(res)[:200]}..."
                        )

                    except Exception as e:

                        res = (
                            f"Error executing tool: {e}"
                        )

                        print(
                            "DEBUG: Tool Execution Error:",
                            e
                        )

                # ------------------------------------------------
                # Save tool result
                # ------------------------------------------------

                self._save_message(
                    {
                        "role": "tool",
                        "content": str(res)
                    }
                )

            # ====================================================
            # FINAL OLLAMA RESPONSE
            # ====================================================

            try:

                final_messages = [
                    {
                        "role": "system",
                        "content": self.system_instruction
                    },
                    *self.conversation_history
                ]

                second_response = ollama.chat(
                    model=self.model_name,
                    messages=final_messages,
                    options={
                        "num_predict": 80
                    }
                )

                final_message = (
                    second_response
                    .get("message", {})
                    .get("content", "")
                )

                if not final_message:

                    final_message = (
                        "The task has been completed."
                    )

                self._save_message(
                    {
                        "role": "assistant",
                        "content": final_message
                    }
                )

                return final_message

            except Exception as e:

                print(
                    f"Ollama final response error: {e}"
                )

                return (
                    "The action was completed, sir."
                )

        # ========================================================
        # CASE 2:
        # NORMAL CONVERSATION
        # ========================================================

        assistant_response = (
            response_message.get(
                "content",
                ""
            )
        )

        if not assistant_response:

            assistant_response = (
                "I'm ready."
            )

        # Save user message
        self._save_message(
            {
                "role": "user",
                "content": user_prompt
            }
        )

        # Save assistant response
        self._save_message(
            {
                "role": "assistant",
                "content": assistant_response
            }
        )

        return assistant_response
