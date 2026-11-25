from selenium.common.exceptions import WebDriverException
from urllib3.exceptions import HTTPError

# What a call to the browser raises when the browser is what failed. Selenium reports Chrome's own
# failures as WebDriverException; a chromedriver that has exited surfaces as urllib3's HTTPError,
# which Selenium does not wrap.
BROWSER_ERRORS = (WebDriverException, HTTPError)
