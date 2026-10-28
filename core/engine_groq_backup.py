
import os
import json
import re

from groq import Groq
from core.registry import SkillRegistry


class JarvisEngine:

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

        self.client = Groq(
            api_key=os.environ.get("GROQ_API_KEY")
        )

        self.model_name = "llama-3.3-70b-versatile"

        self.system_instruction = (
            "You are Jarvis, a helpful and precise AI desktop assistant. "
            "Maintain natural conversation with the user and use previous "
            "conversation context when interpreting follow-up requests. "
            "Use the provided tools whenever an action is required. "
            "When using tools, use the standard tool calling format provided "
            "by the API."
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
    # RUN CONVERSATION
    # ============================================================

    def run_conversation(self, user_prompt: str):

        # --------------------------------------------------------
        # Build messages
        # --------------------------------------------------------

        messages = self._build_messages(user_prompt)

        try:

            tools_schema = self.registry.get_tools_schema()

            completion_kwargs = {
                "model": self.model_name,
                "messages": messages,
                "max_tokens": 300
            }

            if tools_schema:
                completion_kwargs["tools"] = tools_schema
                completion_kwargs["tool_choice"] = "auto"

            response = self.client.chat.completions.create(
                **completion_kwargs
            )

        except Exception as e:

            error_str = str(e)

            # ====================================================
            # RECOVER FAILED TOOL CALL
            # ====================================================

            if (
                "tool_use_failed" in error_str
                and "failed_generation" in error_str
            ):

                try:

                    match = re.search(
                        r"<function=(\w+)(?:.*?)"
                        r"(?=\{)(\{.*?\})"
                        r"</function>",
                        error_str,
                        re.DOTALL
                    )

                    if match:

                        func_name = match.group(1)
                        func_args_str = match.group(2)

                        print(
                            f"DEBUG: Recovered failed tool call: "
                            f"{func_name} with {func_args_str}"
                        )

                        function_to_call = (
                            self.registry.get_function(
                                func_name
                            )
                        )

                        if function_to_call:

                            try:

                                args = json.loads(
                                    func_args_str
                                )

                                if args is None:
                                    args = {}

                                # Execute recovered function
                                res = function_to_call(
                                    **args
                                )

                                # IMPORTANT:
                                # Do NOT save a role=tool message here.
                                #
                                # There is no valid Groq tool_call_id
                                # available in this recovery path.
                                #
                                # Saving it as an ordinary assistant
                                # result prevents the next Groq request
                                # from becoming invalid.

                                self._save_message(
                                    {
                                        "role": "user",
                                        "content": user_prompt
                                    }
                                )

                                self._save_message(
                                    {
                                        "role": "assistant",
                                        "content": str(res)
                                    }
                                )

                                return str(res)

                            except Exception as exec_e:

                                return (
                                    "Error executing recovered "
                                    f"tool: {exec_e}"
                                )

                except Exception as parse_e:

                    print(
                        f"Failed to recover tool call: "
                        f"{parse_e}"
                    )

            print(
                f"Groq API Error: {e}"
            )

            return (
                "I am having trouble connecting "
                "to the brain, sir."
            )

        # ========================================================
        # GET AI RESPONSE
        # ========================================================

        response_message = response.choices[0].message

        tool_calls = response_message.tool_calls

        # ========================================================
        # CASE 1: AI WANTS TO USE TOOL
        # ========================================================

        if tool_calls:

            print(
                "DEBUG: Executing Tool..."
            )

            # Save user request
            self._save_message(
                {
                    "role": "user",
                    "content": user_prompt
                }
            )

            # IMPORTANT:
            # Convert the assistant message to a normal dictionary.
            #
            # This preserves the tool_calls information required by
            # Groq for the following role=tool messages.

            assistant_tool_message = {
                "role": "assistant",
                "content": response_message.content or "",
                "tool_calls": []
            }

            for tool_call in tool_calls:

                assistant_tool_message["tool_calls"].append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    }
                )

            self._save_message(
                assistant_tool_message
            )

            # ----------------------------------------------------
            # Execute every requested tool
            # ----------------------------------------------------

            for tool_call in tool_calls:

                function_name = (
                    tool_call.function.name
                )

                print(
                    f"DEBUG: AI attempting to call: "
                    f"{function_name}"
                )

                function_to_call = (
                    self.registry.get_function(
                        function_name
                    )
                )

                if not function_to_call:

                    res = (
                        "Error: Tool not found."
                    )

                    print(
                        f"DEBUG: Tool {function_name} "
                        "not found in registry."
                    )

                else:

                    try:

                        function_args = json.loads(
                            tool_call.function.arguments
                        )

                        if function_args is None:
                            function_args = {}

                        print(
                            f"DEBUG: Tool arguments: "
                            f"{function_args}"
                        )

                        res = function_to_call(
                            **function_args
                        )

                        print(
                            f"DEBUG: Tool Output: "
                            f"{str(res)[:100]}..."
                        )

                    except Exception as e:

                        res = (
                            f"Error executing tool: {e}"
                        )

                        print(
                            f"DEBUG: Tool Execution Error: "
                            f"{e}"
                        )

                # ------------------------------------------------
                # IMPORTANT GROQ TOOL MESSAGE
                # ------------------------------------------------

                tool_message = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": str(res)
                }

                self._save_message(
                    tool_message
                )

            # ====================================================
            # GET FINAL NATURAL LANGUAGE RESPONSE
            # ====================================================

            try:

                second_response = (
                    self.client.chat.completions.create(
                        model=self.model_name,
                        messages=[
                            {
                                "role": "system",
                                "content": self.system_instruction
                            },
                            *self.conversation_history
                        ],
                        max_tokens=300
                    )
                )

                final_message = (
                    second_response
                    .choices[0]
                    .message
                    .content
                )

                if not final_message:
                    final_message = (
                        "The task has been completed."
                    )

                # Save final response
                self._save_message(
                    {
                        "role": "assistant",
                        "content": final_message
                    }
                )

                return final_message

            except Exception as e:

                print(
                    f"Groq final response error: "
                    f"{e}"
                )

                return (
                    "The action was completed, "
                    "but I couldn't generate "
                    "a response."
                )

        # ========================================================
        # CASE 2: NORMAL CONVERSATION
        # ========================================================

        else:

            # Save user message
            self._save_message(
                {
                    "role": "user",
                    "content": user_prompt
                }
            )

            assistant_response = (
                response_message.content
            )

            if not assistant_response:
                assistant_response = (
                    "I'm ready."
                )

            self._save_message(
                {
                    "role": "assistant",
                    "content": assistant_response
                }
            )

            return assistant_response
