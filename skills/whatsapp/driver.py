
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


class WhatsAppDriver:

    _driver = None

    @classmethod
    def get_driver(cls):

        # Reuse existing Chrome session
        if cls._driver is not None:

            try:
                _ = cls._driver.current_url
                return cls._driver

            except Exception:

                print("DEBUG: Existing Chrome driver is dead.")

                try:
                    cls._driver.quit()
                except Exception:
                    pass

                cls._driver = None

        # Create new driver
        cls._driver = cls._init_driver()

        return cls._driver

    @staticmethod
    def _init_driver():

        print("DEBUG: Initializing Chrome Driver...")

        try:

            options = Options()

            # ------------------------------------------------
            # Chrome stability options
            # ------------------------------------------------

            options.add_argument("--start-maximized")

            options.add_argument("--disable-gpu")

            options.add_argument("--disable-software-rasterizer")

            options.add_argument("--disable-dev-shm-usage")

            options.add_argument("--no-sandbox")

            options.add_argument("--remote-allow-origins=*")

            options.add_argument("--disable-extensions")

            options.add_argument("--disable-background-networking")

            options.add_argument("--disable-background-timer-throttling")

            options.add_argument("--disable-renderer-backgrounding")

            options.add_argument("--disable-backgrounding-occluded-windows")

            # ------------------------------------------------
            # Keep WhatsApp login session
            # ------------------------------------------------

            user_data = (
                r"C:\Users\Naziya Tahseen"
                r"\AppData\Local\JARVIS_WhatsApp_Chrome"
            )

            options.add_argument(
                f"--user-data-dir={user_data}"
            )

            # ------------------------------------------------
            # Explicit Chrome location
            # ------------------------------------------------

            chrome_path = (
                r"C:\Program Files\Google\Chrome"
                r"\Application\chrome.exe"
            )

            options.binary_location = chrome_path

            # ------------------------------------------------
            # Create Chrome driver
            # ------------------------------------------------

            service = Service(
                ChromeDriverManager().install()
            )

            driver = webdriver.Chrome(
                service=service,
                options=options
            )

            driver.maximize_window()

            print("DEBUG: Chrome Driver started successfully.")

            return driver

        except Exception as e:

            print(
                f"DEBUG: Failed to initialize Chrome: {e}"
            )

            raise