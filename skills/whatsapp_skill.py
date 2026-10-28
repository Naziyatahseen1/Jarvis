from core.skill import Skill
from skills.whatsapp.whatsapp_client import WhatsAppClient
from skills.whatsapp.whatsapp_call import call_contact


class WhatsappSkill(Skill):
    """Messages via WhatsApp Web (Selenium), calls via the WhatsApp desktop app."""

    def __init__(self):
        self.client = None

    @property
    def name(self):
        return "whatsapp_skill"

    def _get_client(self):
        if not self.client:
            self.client = WhatsAppClient()
        return self.client

    def get_tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "send_whatsapp_message",
                    "description": "Send a WhatsApp message to a person by searching their name in WhatsApp.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "The person's name."},
                            "message": {"type": "string", "description": "The message to send."},
                        },
                        "required": ["name", "message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "make_whatsapp_call",
                    "description": "Start a WhatsApp voice or video call with a person by searching their name.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "The person to call."},
                            "video": {"type": "boolean", "description": "True for video call, false for voice call."},
                        },
                        "required": ["name"],
                    },
                },
            },
        ]

    def get_functions(self):
        return {
            "send_whatsapp_message": self.send_whatsapp_message,
            "make_whatsapp_call": self.make_whatsapp_call,
        }

    def send_whatsapp_message(self, name, message):
        clean_name = (name or "").strip()
        if not clean_name:
            return "Error: No WhatsApp contact name was provided."
        if not message or not message.strip():
            return "Error: No message was provided."
        try:
            return self._get_client().send_message(clean_name, message.strip())
        except Exception as e:
            return f"Error sending WhatsApp message: {e}"

    def make_whatsapp_call(self, name, video=False):
        clean_name = (name or "").strip()
        if not clean_name:
            return "Error: No WhatsApp contact name was provided."
        try:
            return call_contact(clean_name, video=bool(video))
        except Exception as e:
            return f"Error starting WhatsApp call: {e}"