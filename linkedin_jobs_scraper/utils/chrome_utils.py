from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions


def build_default_chrome_driver(width=1472, height=828, timeout=20):
    chrome_options = ChromeOptions()
    chrome_options.headless = True
    chrome_options.page_load_strategy = 'normal'

    chrome_options.add_argument('--enable-automation'),
    chrome_options.add_argument('--start-maximized'),
    chrome_options.add_argument(f'--window-size={width},{height}'),
    chrome_options.add_argument('--lang=en-GB'),
    chrome_options.add_argument('--no-sandbox'),
    chrome_options.add_argument('--disable-setuid-sandbox'),
    chrome_options.add_argument('--disable-gpu'),
    chrome_options.add_argument('--disable-dev-shm-usage'),
    chrome_options.add_argument('--no-sandbox'),
    chrome_options.add_argument('--disable-setuid-sandbox'),
    chrome_options.add_argument('--disable-dev-shm-usage'),
    chrome_options.add_argument("-proxy-server='direct://"),
    chrome_options.add_argument('--proxy-bypass-list=*'),
    chrome_options.add_argument('--disable-accelerated-2d-canvas'),
    chrome_options.add_argument('--disable-gpu'),
    chrome_options.add_argument('--allow-running-insecure-content'),
    chrome_options.add_argument('--disable-web-security'),
    chrome_options.add_argument('--disable-client-side-phishing-detection'),
    chrome_options.add_argument('--disable-notifications'),
    chrome_options.add_argument('--mute-audio'),

    # Disable downloads
    chrome_options.add_experimental_option(
        'prefs', {
            'safebrowsing.enabled': 'false',
            'download.prompt_for_download': False,
            'download.default_directory': '/dev/null',
            'download_restrictions': 3,
            'profile.default_content_setting_values.notifications': 2,
        }
    )

    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(timeout)
    return driver
