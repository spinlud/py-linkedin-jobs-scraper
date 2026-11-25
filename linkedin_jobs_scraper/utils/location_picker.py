"""Turn a location name into a LinkedIn geoId through the search page's own location picker.

LinkedIn drops a free-text `location=` parameter, and its typeahead endpoint is a React
Server Components action with an opaque body that a plain replay answers with HTTP 500. So
a name is resolved the way a person does it: open the "Location <current>" control, type
the name, and read the `geoId` of the first suggestion from its href. No suggestion is
clicked, so the resolution itself does not search anything.
"""

from __future__ import annotations

from threading import Lock
from time import monotonic, sleep
from typing import NamedTuple

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from .url import get_query_params


class LocationSelectors(NamedTuple):
    # The control's aria-label is "Location " followed by the location on screen
    control = '[aria-label^="Location "]'
    text_editor = '[componentkey="LocationTypeahead_TextEditor"]'
    suggestions = '[componentkey="semanticSearchBoxLocationList"]'


# Typed suggestions carry this `origin` in their href. The list also holds the account's
# recent locations and LinkedIn's own picks before anything is typed (`..._HISTORY`,
# `..._SUGGESTION`), which must never be taken for a match.
AUTOCOMPLETE_ORIGIN = 'JOB_SEARCH_PAGE_LOCATION_AUTOCOMPLETE'

# How long to wait for the picker to open, and for suggestions to follow the typed name.
# A name with no match leaves the list empty, which only the timeout can tell apart from a
# list still on its way.
CONTROL_TIMEOUT = 15
SUGGESTIONS_TIMEOUT = 6
POLL_INTERVAL = 0.2

READ_SUGGESTIONS_SCRIPT = r"""
    const list = document.querySelector(arguments[0]);
    if (!list) {
        return null;
    }
    return Array.from(list.querySelectorAll('a[href]'))
        .map(a => ({ href: a.getAttribute('href'), text: (a.innerText || '').trim() }));
"""

# Selects the whole content of the contenteditable textbox, so the next keystroke replaces it
# whatever platform modifier "select all" would need
SELECT_EDITOR_CONTENT_SCRIPT = r"""
    const editor = document.querySelector(arguments[0]);
    if (!editor) {
        return false;
    }
    editor.focus();
    const range = document.createRange();
    range.selectNodeContents(editor);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    return true;
"""


class PickedLocation(NamedTuple):
    geo_id: str
    label: str


CONTROL_LABEL_PREFIX = 'Location '

# LinkedIn's new search page offers no worldwide search: every way of asking for one leaves
# the account's remembered location applied, and the picker suggests nothing for the name.
WORLDWIDE = 'Worldwide'

READ_CONTROL_LABEL_SCRIPT = r"""
    const control = document.querySelector(arguments[0]);
    return control ? control.getAttribute('aria-label') : null;
"""


def is_worldwide(name: str) -> bool:
    return name.strip().lower() == WORLDWIDE.lower()


def applied_location_name(label: str | None) -> str:
    """
    The location named by the control's aria-label ("Location <name>"), '' when it names none
    :param label: str | None
    :return: str
    """
    text = (label or '').strip() + ' '
    if not text.startswith(CONTROL_LABEL_PREFIX):
        return ''
    return text[len(CONTROL_LABEL_PREFIX) :].strip()


def _first_segment(name: str) -> str:
    return name.split(',')[0].strip().lower()


def location_matches(expected: str, applied: str) -> bool:
    """
    Whether the applied location is the expected one, compared on the first comma-separated
    segment: the picker says "Rome, Latium, Italy" where the control may say "Rome"
    :param expected: str
    :param applied: str
    :return: bool
    """
    return _first_segment(expected) != '' and _first_segment(expected) == _first_segment(applied)


def read_applied_location(driver: webdriver) -> str:
    """
    The location the search page on screen applied, read from the location control
    :param driver: webdriver
    :return: str, '' when the control is absent or unreadable
    """
    try:
        return applied_location_name(
            driver.execute_script(READ_CONTROL_LABEL_SCRIPT, LocationSelectors.control)
        )
    except WebDriverException:
        return ''


class LocationPickerError(Exception):
    """Raised when the location picker could not be operated, as opposed to finding no match"""


def first_suggestion(suggestions: list[dict]) -> PickedLocation | None:
    """
    The first typed suggestion that carries a geoId
    :param suggestions: list of {'href': str, 'text': str} in display order
    :return: PickedLocation | None
    """
    for suggestion in suggestions:
        params = get_query_params(suggestion.get('href') or '')
        geo_id = params.get('geoId', '')
        if params.get('origin') == AUTOCOMPLETE_ORIGIN and geo_id.isdigit():
            return PickedLocation(geo_id=geo_id, label=suggestion.get('text') or '')
    return None


def _wait_for(driver: webdriver, css: str, timeout: float) -> bool:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        try:
            if driver.execute_script('return !!document.querySelector(arguments[0]);', css):
                return True
        except WebDriverException:
            # The document is being replaced
            pass
        sleep(POLL_INTERVAL)
    return False


def pick_location(driver: webdriver, name: str) -> PickedLocation | None:
    """
    Type a name into the location picker of the search page on screen and read its first match

    The browser must be on a jobs search-results page. The picker is left open with the name
    typed into it; nothing is submitted.

    :param driver: webdriver
    :param name: str
    :return: PickedLocation, or None when LinkedIn suggests nothing for the name
    :raises LocationPickerError: when the picker could not be opened or typed into
    """

    if not _wait_for(driver, LocationSelectors.control, CONTROL_TIMEOUT):
        raise LocationPickerError('The location control never appeared')

    # A scripted click does not open the picker; a pointer click does
    control = driver.find_element(By.CSS_SELECTOR, LocationSelectors.control)
    ActionChains(driver).move_to_element(control).click().perform()

    if not _wait_for(driver, LocationSelectors.text_editor, CONTROL_TIMEOUT):
        raise LocationPickerError('The location textbox never appeared')

    editor = driver.find_element(By.CSS_SELECTOR, LocationSelectors.text_editor)
    ActionChains(driver).click(editor).perform()

    if not driver.execute_script(SELECT_EDITOR_CONTENT_SCRIPT, LocationSelectors.text_editor):
        raise LocationPickerError('The location textbox could not be selected')

    ActionChains(driver).send_keys(Keys.BACKSPACE).send_keys(name).perform()

    deadline = monotonic() + SUGGESTIONS_TIMEOUT
    while monotonic() < deadline:
        sleep(POLL_INTERVAL)
        try:
            suggestions = driver.execute_script(
                READ_SUGGESTIONS_SCRIPT, LocationSelectors.suggestions
            )
        except WebDriverException:
            continue
        picked = first_suggestion(suggestions or [])
        if picked is not None:
            return picked

    return None


class LocationCache:
    """
    Names already resolved in this process, matches and misses alike

    A picker that could not be operated is not cached: that says nothing about the name.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._entries: dict[str, PickedLocation | None] = {}

    @staticmethod
    def _key(name: str) -> str:
        return ' '.join(name.split()).lower()

    def get(self, name: str) -> tuple[bool, PickedLocation | None]:
        with self._lock:
            key = self._key(name)
            return key in self._entries, self._entries.get(key)

    def put(self, name: str, picked: PickedLocation | None) -> None:
        with self._lock:
            self._entries[self._key(name)] = picked


LOCATION_CACHE = LocationCache()
