
import sys
import pyttsx3
import speech_recognition as sr


# ============================================================
# TEXT TO SPEECH
# ============================================================

def create_engine():
    """Create and configure the Windows speech engine."""

    if sys.platform == "win32":
        engine = pyttsx3.init("sapi5")
    else:
        engine = pyttsx3.init()

    voices = engine.getProperty("voices")

    # Prefer Microsoft David on Windows
    if sys.platform == "win32":
        for voice in voices:
            if "David" in voice.name:
                engine.setProperty("voice", voice.id)
                break

    engine.setProperty("rate", 175)
    engine.setProperty("volume", 1.0)

    return engine


# Prevent listening while JARVIS is speaking
is_speaking = False


def speak(text):
    """Convert JARVIS's response into speech."""

    global is_speaking

    if not text:
        return

    text = str(text)

    # Avoid reading raw JSON tool responses
    if "{" in text and "}" in text and "status" in text:
        text = "Task completed."

    print(f"JARVIS: {text}")

    is_speaking = True

    try:
        engine = create_engine()

        print("TTS: Speaking...")

        engine.say(text)
        engine.runAndWait()

        print("TTS: Speech finished.")

        engine.stop()

    except Exception as e:
        print(f"TTS Error: {e}")

    finally:
        is_speaking = False


# ============================================================
# SPEECH TO TEXT
# ============================================================

def listen():
    """Listen to the microphone and convert speech to text."""

    global is_speaking

    if is_speaking:
        return "none"

    recognizer = sr.Recognizer()

    # Keep recognition responsive
    recognizer.pause_threshold = 0.8

    # Google recognition timeout
    recognizer.operation_timeout = 3

    try:
        with sr.Microphone() as source:

            print("Listening...")

            # Very short calibration
            recognizer.adjust_for_ambient_noise(
                source,
                duration=0.1
            )

            try:
                audio = recognizer.listen(
                    source,
                    timeout=5,
                    phrase_time_limit=10
                )

                print("Recognizing...")

                try:
                    # Google Speech Recognition
                    query = recognizer.recognize_google(
                        audio
                    )

                    print(f"You said: {query}")

                    return query.lower().strip()

                except sr.UnknownValueError:
                    print("Could not understand.")
                    return "none"

                except sr.RequestError as e:
                    print(f"Speech recognition service error: {e}")
                    return "none"

                except Exception as e:
                    print(f"Speech recognition error: {e}")
                    return "none"

            except sr.WaitTimeoutError:
                print("No speech detected.")
                return "none"

            except Exception as e:
                print(f"Listening error: {e}")
                return "none"

    except Exception as e:
        print(f"Microphone Error: {e}")
        return "none"
