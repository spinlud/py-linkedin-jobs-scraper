import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlparse


def get_job_id(url_or_id: str) -> str:
    """
    Extract a LinkedIn job id from a bare id or a job url
    :param url_or_id: a numeric id, a '/jobs/view/<id>' url or a '?currentJobId=<id>' url
    :return: str
    """

    value = url_or_id.strip()

    if value.isdigit():
        return value

    match = re.search(r'/jobs/view/(\d+)', value)
    if match:
        return match.group(1)

    current_job_id = get_query_params(value).get('currentJobId')
    if current_job_id and current_job_id.isdigit():
        return current_job_id

    raise ValueError(f'Could not extract a job id from {url_or_id!r}')


def get_query_params(url: str) -> dict[str, str]:
    """
    Extract url query parameters as a dictionary
    :param url:
    :return: dict
    """

    parsed = urlparse(url)
    return dict(parse_qsl(parsed.query))


def override_query_params(url: str, override_params: Mapping[str, object]) -> str:
    """
    Override url query parameters
    :param url:
    :param override_params:
    :return:
    """

    params: dict[str, object] = dict(get_query_params(url))

    for k, v in override_params.items():
        params[k] = v

    return urlparse(url)._replace(query=urlencode(params)).geturl()
