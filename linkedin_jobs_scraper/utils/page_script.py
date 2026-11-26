"""Where the browser's answers enter Python.

Selenium types what a script, a CDP command or a cookie answers as Any, which would silence the
type checker wherever it flows. The functions here hand it over as an unchecked object, and the
readers narrow it, naming the field that does not hold what is expected of it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from selenium.webdriver.remote.webdriver import WebDriver

from .job_record import RawAnchor, RawJobDetails, RawJobRecord


class PageAnswerError(ValueError):
    """The browser answered with a shape its reader does not know."""


def run_script(driver: WebDriver, script: str, *args: object) -> object:
    # The typed local is what turns Selenium's Any into an object, here and below
    answer: object = driver.execute_script(script, *args)
    return answer


def run_async_script(driver: WebDriver, script: str, *args: object) -> object:
    answer: object = driver.execute_async_script(script, *args)
    return answer


def run_cdp(driver: WebDriver, command: str, params: dict[str, object]) -> object:
    answer: object = driver.execute_cdp_cmd(command, params)
    return answer


def _unexpected(key: str, expected: str, value: object) -> PageAnswerError:
    return PageAnswerError(f'{key}: expected {expected}, found {type(value).__name__}')


def as_mapping(value: object, key: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _unexpected(key, 'an object', value)
    return value


def as_list(value: object, key: str) -> list[object]:
    if not isinstance(value, list):
        raise _unexpected(key, 'a list', value)
    return value


def as_str(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise _unexpected(key, 'a string', value)
    return value


def as_texts(value: object, key: str) -> list[str]:
    return [as_str(text, key) for text in as_list(value, key)]


def read_value(raw: Mapping[str, object], key: str) -> object:
    if key not in raw:
        raise PageAnswerError(f'{key}: missing')
    return raw[key]


def read_str(raw: Mapping[str, object], key: str) -> str:
    return as_str(read_value(raw, key), key)


def read_list(raw: Mapping[str, object], key: str) -> list[object]:
    return as_list(read_value(raw, key), key)


def read_texts(raw: Mapping[str, object], key: str) -> list[str]:
    return as_texts(read_value(raw, key), key)


def as_int(value: object, key: str) -> int:
    # Python counts true and false among the integers
    if not isinstance(value, int) or isinstance(value, bool):
        raise _unexpected(key, 'an integer', value)
    return value


def read_job_record(answer: object) -> RawJobRecord:
    raw = as_mapping(answer, 'job card')
    return {
        'job_id': read_str(raw, 'job_id'),
        'card_texts': read_texts(raw, 'card_texts'),
        'card_labels': read_texts(raw, 'card_labels'),
        'card_img': read_str(raw, 'card_img'),
    }


def _read_anchor(answer: object) -> RawAnchor:
    raw = as_mapping(answer, 'anchors')
    return {
        'text': read_str(raw, 'text'),
        'href': read_str(raw, 'href'),
        'label': read_str(raw, 'label'),
    }


def read_job_details(answer: object) -> RawJobDetails:
    raw = as_mapping(answer, 'job details')
    return {
        'job_id': read_str(raw, 'job_id'),
        'top_texts': read_texts(raw, 'top_texts'),
        'anchors': [_read_anchor(anchor) for anchor in read_list(raw, 'anchors')],
        'button_labels': read_texts(raw, 'button_labels'),
        'company_img': read_str(raw, 'company_img'),
        'description_text': read_str(raw, 'description_text'),
        'description_html': read_str(raw, 'description_html'),
        'company_texts': read_texts(raw, 'company_texts'),
    }


def _read_suggestion(answer: object) -> dict[str, str]:
    raw = as_mapping(answer, 'suggestions')
    return {
        'href': as_str(raw.get('href') or '', 'href'),
        'text': as_str(raw.get('text') or '', 'text'),
    }


def read_suggestions(answer: object) -> Iterator[dict[str, str]]:
    # Nothing is answered while the list is not on the page
    if not answer:
        return
    # Read one at a time, so a pick stops before the suggestions after it
    for suggestion in as_list(answer, 'suggestions'):
        yield _read_suggestion(suggestion)


def read_cookie_value(answer: object) -> str | None:
    if not answer:
        return None
    value = as_mapping(answer, 'cookie').get('value')
    return None if value is None else as_str(value, 'value')


def read_target_infos(answer: object) -> list[object]:
    """
    The targets listed by Target.getTargets, each left to its user to read
    :param answer: object
    :return: list[object]
    """
    if not answer:
        return []
    raw = as_mapping(answer, 'targets')
    return read_list(raw, 'targetInfos') if 'targetInfos' in raw else []


def read_throttle_reading(answer: object) -> tuple[float, int]:
    reading = as_list(answer, 'resource timings')
    if len(reading) != 2:
        raise PageAnswerError(f'resource timings: expected 2 values, found {len(reading)}')
    time_origin, refused = reading
    if not isinstance(time_origin, int | float):
        raise _unexpected('timeOrigin', 'a number', time_origin)
    return time_origin, as_int(refused, 'refused requests')
