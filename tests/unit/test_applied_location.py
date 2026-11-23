import pytest

from linkedin_jobs_scraper.utils.location_picker import applied_location_name, is_worldwide, location_matches


@pytest.mark.parametrize('label, name', [
    ('Location San Francisco Bay Area', 'San Francisco Bay Area'),
    ('Location Italy', 'Italy'),
    ('  Location Germany ', 'Germany'),
    ('Location ', ''),
    ('', ''),
    (None, ''),
    ('Something else', ''),
])
def test_applied_location_name_strips_the_control_prefix(label: str | None, name: str) -> None:
    assert applied_location_name(label) == name


@pytest.mark.parametrize('expected, applied', [
    ('San Francisco Bay Area', 'San Francisco Bay Area'),
    ('Rome, Latium, Italy', 'Rome'),
    ('Rome', 'Rome, Latium, Italy'),
    ('italy', 'Italy'),
])
def test_first_segment_matches_case_insensitively(expected: str, applied: str) -> None:
    assert location_matches(expected, applied)


@pytest.mark.parametrize('expected, applied', [
    ('San Francisco Bay Area', 'Bengaluru, Karnataka, India'),
    ('Rome, Latium, Italy', 'Italy'),
    ('Rome', ''),
])
def test_different_first_segment_is_a_mismatch(expected: str, applied: str) -> None:
    assert not location_matches(expected, applied)


@pytest.mark.parametrize('name', ['Worldwide', 'worldwide', '  WORLDWIDE '])
def test_worldwide_is_recognised(name: str) -> None:
    assert is_worldwide(name)


@pytest.mark.parametrize('name', ['', 'Italy', 'Worldwide Italy'])
def test_other_names_are_not_worldwide(name: str) -> None:
    assert not is_worldwide(name)
