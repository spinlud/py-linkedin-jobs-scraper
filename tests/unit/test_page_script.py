"""What the browser answers enters Python through readers, which name the field that is wrong."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from linkedin_jobs_scraper.strategies.authenticated_strategy import read_single_job_state
from linkedin_jobs_scraper.utils.page_script import (
    PageAnswerError,
    as_int,
    as_mapping,
    as_str,
    read_cookie_value,
    read_job_details,
    read_job_record,
    read_list,
    read_str,
    read_suggestions,
    read_target_infos,
    read_texts,
    read_throttle_reading,
    read_value,
    run_async_script,
    run_cdp,
    run_script,
)


def test_scripts_and_cdp_commands_reach_selenium_unchanged() -> None:
    driver = MagicMock()
    driver.execute_script.return_value = 'sync'
    driver.execute_async_script.return_value = 'async'
    driver.execute_cdp_cmd.return_value = {'targetInfos': []}

    assert run_script(driver, 'return arguments[0]', 1, 'a') == 'sync'
    assert run_async_script(driver, 'arguments[0]()', ['a']) == 'async'
    assert run_cdp(driver, 'Target.getTargets', {}) == {'targetInfos': []}

    driver.execute_script.assert_called_once_with('return arguments[0]', 1, 'a')
    driver.execute_async_script.assert_called_once_with('arguments[0]()', ['a'])
    driver.execute_cdp_cmd.assert_called_once_with('Target.getTargets', {})


def test_readers_return_what_the_page_holds() -> None:
    raw = {'title': 'Engineer', 'texts': ['a', ''], 'mixed': [1, None], 'nothing': None}

    assert as_mapping(raw, 'card') == raw
    assert as_str('Engineer', 'title') == 'Engineer'
    assert read_value(raw, 'nothing') is None
    assert read_str(raw, 'title') == 'Engineer'
    assert read_list(raw, 'mixed') == [1, None]
    assert read_texts(raw, 'texts') == ['a', '']


@pytest.mark.parametrize(
    'read, message',
    [
        (lambda: as_mapping(['a'], 'card'), 'card: expected an object, found list'),
        (lambda: as_str(None, 'title'), 'title: expected a string, found NoneType'),
        (lambda: read_value({}, 'title'), 'title: missing'),
        (lambda: read_str({'title': 1}, 'title'), 'title: expected a string, found int'),
        (lambda: read_list({'texts': 'ab'}, 'texts'), 'texts: expected a list, found str'),
        (lambda: read_texts({'texts': ['a', None]}, 'texts'), 'texts: expected a string'),
    ],
)
def test_a_reader_names_the_field_and_the_type_it_held(
    read: Callable[[], object], message: str
) -> None:
    with pytest.raises(PageAnswerError, match=message):
        read()


def test_a_wrong_answer_is_a_value_error() -> None:
    assert issubclass(PageAnswerError, ValueError)


CARD = {
    'job_id': '4438239210',
    'card_texts': ['Junior Software Engineer', 'Lexroom', 'Milan (Hybrid)'],
    'card_labels': ['Dismiss Junior Software Engineer job'],
    'card_img': 'https://media.licdn.com/logo',
}
ANCHOR = {
    'text': 'Lexroom',
    'href': 'https://www.linkedin.com/company/lexroom/life',
    'label': '',
}
DETAILS = {
    'job_id': '4438239210',
    'top_texts': ['Lexroom', 'Junior Software Engineer'],
    'anchors': [ANCHOR],
    'button_labels': ['Easy Apply to this job'],
    'company_img': '',
    'description_text': 'About the job',
    'description_html': '<h2>About the job</h2>',
    'company_texts': [],
}


def test_a_job_card_is_read_as_the_page_gave_it() -> None:
    assert read_job_record(CARD) == CARD


@pytest.mark.parametrize('field', CARD)
def test_a_job_card_names_its_wrong_field(field: str) -> None:
    with pytest.raises(PageAnswerError, match=f'^{field}: '):
        read_job_record({**CARD, field: None})


def test_job_details_are_read_as_the_page_gave_them() -> None:
    assert read_job_details(DETAILS) == DETAILS


@pytest.mark.parametrize('field', DETAILS)
def test_job_details_name_their_wrong_field(field: str) -> None:
    with pytest.raises(PageAnswerError, match=f'^{field}: '):
        read_job_details({**DETAILS, field: None})


@pytest.mark.parametrize('field', ANCHOR)
def test_job_details_name_the_wrong_field_of_an_anchor(field: str) -> None:
    with pytest.raises(PageAnswerError, match=f'^{field}: '):
        read_job_details({**DETAILS, 'anchors': [ANCHOR, {**ANCHOR, field: None}]})


def test_an_svg_anchor_names_its_link() -> None:
    # What Chrome returns for `a.href` on an anchor drawn in an SVG
    svg_anchor = {**ANCHOR, 'href': {'animVal': '/y', 'baseVal': '/y'}}

    with pytest.raises(PageAnswerError, match=r'^href: expected a string, found dict'):
        read_job_details({**DETAILS, 'anchors': [svg_anchor]})


SUGGESTION = {'href': '/jobs/search-results/?geoId=90009885', 'text': 'Rome, Latium, Italy'}


def test_suggestions_are_read_as_the_page_gave_them() -> None:
    assert read_suggestions([SUGGESTION]) == [SUGGESTION]


@pytest.mark.parametrize('answer', [None, []])
def test_a_list_not_on_the_page_holds_no_suggestion(answer: object) -> None:
    assert read_suggestions(answer) == []


@pytest.mark.parametrize('suggestion', [{}, {'href': None, 'text': None}])
def test_a_suggestion_without_a_link_or_text_is_empty(suggestion: object) -> None:
    assert read_suggestions([suggestion]) == [{'href': '', 'text': ''}]


@pytest.mark.parametrize('field', SUGGESTION)
def test_a_suggestion_names_its_wrong_field(field: str) -> None:
    with pytest.raises(PageAnswerError, match=f'^{field}: expected a string, found int'):
        read_suggestions([{**SUGGESTION, field: 1}])


@pytest.mark.parametrize('answer', [None, {}, {'name': 'li_at'}, {'name': 'li_at', 'value': None}])
def test_a_cookie_not_in_the_jar_has_no_value(answer: object) -> None:
    assert read_cookie_value(answer) is None


def test_a_cookie_is_read_by_its_value() -> None:
    assert read_cookie_value({'name': 'li_at', 'value': 'x', 'expiry': 1795614876}) == 'x'


def test_a_cookie_names_its_wrong_field() -> None:
    with pytest.raises(PageAnswerError, match='value: expected a string, found int'):
        read_cookie_value({'name': 'li_at', 'value': 1})


@pytest.mark.parametrize('answer', [None, {}, {'targetInfos': []}])
def test_an_answer_without_tabs_lists_none(answer: object) -> None:
    assert read_target_infos(answer) == []


def test_tabs_are_listed_unread() -> None:
    assert read_target_infos({'targetInfos': [{'type': 'page'}, None]}) == [{'type': 'page'}, None]


def test_a_list_of_tabs_names_its_wrong_field() -> None:
    with pytest.raises(PageAnswerError, match='targetInfos: expected a list, found NoneType'):
        read_target_infos({'targetInfos': None})


@pytest.mark.parametrize('answer', [[1795614876986.7, 0], [1795614876986, 2]])
def test_the_refused_requests_of_a_document_are_read(answer: list[float]) -> None:
    assert read_throttle_reading(answer) == tuple(answer)


@pytest.mark.parametrize(
    'answer, field',
    [
        ([None, 0], 'timeOrigin'),
        ([1795614876986.7, '0'], 'refused requests'),
        ([1795614876986.7, True], 'refused requests'),
        ([1795614876986.7], 'resource timings'),
        ('0', 'resource timings'),
    ],
)
def test_the_refused_requests_of_a_document_name_their_wrong_field(
    answer: object, field: str
) -> None:
    with pytest.raises(PageAnswerError, match=f'^{field}: '):
        read_throttle_reading(answer)


def test_a_response_status_names_itself_when_it_is_no_number() -> None:
    assert as_int(429, 'responseStatus') == 429
    with pytest.raises(PageAnswerError, match='responseStatus: expected an integer, found str'):
        as_int('429', 'responseStatus')


@pytest.mark.parametrize(
    'answer, state', [('details', 'details'), ('not-found', 'not-found'), (None, None)]
)
def test_the_state_of_a_single_job_page_is_read(answer: object, state: str | None) -> None:
    assert read_single_job_state(answer) == state


def test_the_state_of_a_single_job_page_names_itself_when_unknown() -> None:
    with pytest.raises(PageAnswerError, match=r'single job state: .* found True'):
        read_single_job_state(True)
