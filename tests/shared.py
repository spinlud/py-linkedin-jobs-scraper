import sys
from urllib.parse import urlparse
from linkedin_jobs_scraper.events import EventData


def __is_valid_url(url: str):
    try:
        urlparse(url)
    except:
        return False
    else:
        return True


def on_data(data: EventData):
    assert isinstance(data.query, str)
    assert isinstance(data.location, str)
    assert isinstance(data.job_id, str)
    assert isinstance(data.link, str)
    assert isinstance(data.apply_link, str)
    assert isinstance(data.title, str)
    assert isinstance(data.company, str)
    assert isinstance(data.place, str)
    assert isinstance(data.description, str)
    assert isinstance(data.description_html, str)
    assert isinstance(data.date, str)
    assert isinstance(data.seniority_level, str)
    assert isinstance(data.job_function, str)
    assert isinstance(data.employment_type, str)
    assert isinstance(data.industries, str)

    assert len(data.location) > 0
    assert len(data.job_id) > 0
    assert len(data.title) > 0
    assert len(data.place) > 0
    assert len(data.description) > 0
    assert len(data.description_html) > 0

    if len(data.link) > 0:
        assert __is_valid_url(data.link)

    if len(data.apply_link) > 0:
        assert __is_valid_url(data.apply_link)

    print('[ON_DATA]', 'OK', data.job_id)


def on_error(error):
    print('[ON_ERROR]', error)


def on_invalid_session():
    print('[ON_INVALID_SESSION]')
    sys.exit(1)


def on_end():
    print('[ON_END]')
