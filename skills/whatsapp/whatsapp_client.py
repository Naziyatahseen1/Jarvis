
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from .driver import WhatsAppDriver


class WhatsAppClient:
    """
    WhatsApp Web client.

    Searches for contacts directly using the WhatsApp Web search box.
    No phone number or contacts.json is required.
    """

    def __init__(self):
        pass

    def send_message(self, contact_name, message):
        """
        Search WhatsApp Web for contact_name and send message.
        """

        try:
            driver = WhatsAppDriver.get_driver()
            wait = WebDriverWait(driver, 30)

            print(f"DEBUG: Searching WhatsApp for contact: {contact_name}")

            # --------------------------------------------------
            # 1. Make sure WhatsApp Web is open
            # --------------------------------------------------

            if "web.whatsapp.com" not in driver.current_url:
                print("DEBUG: Opening WhatsApp Web...")
                driver.get("https://web.whatsapp.com/")

            # --------------------------------------------------
            # 2. Wait for WhatsApp Web to load
            # --------------------------------------------------

            print("DEBUG: Waiting for WhatsApp Web...")

            search_box = wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        '//div[@contenteditable="true"][@data-tab="3"]'
                    )
                )
            )

            # --------------------------------------------------
            # 3. Search contact name
            # --------------------------------------------------

            print(
                f"DEBUG: Searching contact: {contact_name}"
            )

            search_box.click()

            # Clear existing search
            search_box.send_keys(Keys.CONTROL, "a")
            search_box.send_keys(Keys.BACKSPACE)

            # Enter contact name
            search_box.send_keys(contact_name)

            time.sleep(2)

            # --------------------------------------------------
            # 4. Find search result
            # --------------------------------------------------

            print("DEBUG: Looking for WhatsApp contact...")

            contact_result = None

            possible_xpaths = [
                f'//span[@title="{contact_name}"]',
                f'//span[contains(@title, "{contact_name}")]',
                f'//span[contains(translate(@title, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{contact_name.lower()}")]',
            ]

            for xpath in possible_xpaths:

                try:

                    contact_result = WebDriverWait(
                        driver,
                        5
                    ).until(
                        EC.element_to_be_clickable(
                            (
                                By.XPATH,
                                xpath
                            )
                        )
                    )

                    if contact_result:
                        break

                except TimeoutException:
                    continue

            # --------------------------------------------------
            # 5. If exact contact result wasn't found
            # --------------------------------------------------

            if not contact_result:

                print(
                    f"DEBUG: Could not find exact contact: "
                    f"{contact_name}"
                )

                # Try pressing DOWN and ENTER.
                # This selects the first search result.
                search_box.send_keys(Keys.ARROW_DOWN)

                time.sleep(0.5)

                search_box.send_keys(Keys.ENTER)

            else:

                print(
                    f"DEBUG: Contact found: {contact_name}"
                )

                contact_result.click()

            # --------------------------------------------------
            # 6. Wait for chat/message box
            # --------------------------------------------------

            print("DEBUG: Waiting for chat to open...")

            message_box = wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        '//div[@contenteditable="true"][@data-tab="10"]'
                    )
                )
            )

            time.sleep(1)

            # --------------------------------------------------
            # 7. Type message
            # --------------------------------------------------

            print(
                f"DEBUG: Typing message: {message}"
            )

            message_box.click()
            message_box.send_keys(message)

            time.sleep(0.5)

            # --------------------------------------------------
            # 8. Send message
            # --------------------------------------------------

            print("DEBUG: Sending WhatsApp message...")

            try:

                send_button = WebDriverWait(
                    driver,
                    5
                ).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            '//span[@data-icon="send"]'
                        )
                    )
                )

                send_button.click()

            except Exception:

                print(
                    "DEBUG: Send button not found. "
                    "Using ENTER."
                )

                message_box.send_keys(Keys.ENTER)

            # --------------------------------------------------
            # 9. Finish
            # --------------------------------------------------

            time.sleep(1)

            print(
                f"DEBUG: Message successfully sent to "
                f"{contact_name}"
            )

            return (
                f"Message sent successfully to "
                f"{contact_name}."
            )

        except Exception as e:

            print(
                f"DEBUG: WhatsApp error: {e}"
            )

            return (
                f"Failed to send WhatsApp message "
                f"to {contact_name}: {e}"
            )