from urllib.parse import urlparse, urlencode, parse_qsl


def get_query_params(url: str) -> dict:
    """
    Extract url query parameters as a dictionary
    :param url:
    :return: dict
    """

    parsed = urlparse(url)
    return dict(parse_qsl(parsed.query))


def get_url_no_query_params(url: str) -> str:
    """
    Returns url without query parameters
    :param url:
    :return:
    """

    parsed = urlparse(url)
    parsed = parsed._replace(query='')
    return parsed.geturl()


def override_query_params(url: str, override_params: dict) -> str:
    """
    Override url query parameters
    :param url:
    :param override_params:
    :return:
    """

    params = get_query_params(url)

    for k, v in override_params.items():
        params[k] = v

    return urlparse(url)._replace(query=urlencode(params)).geturl()


def get_domain(url: str) -> str:
    """
    Return SLD (Second Level Domain) from url
    :param url: str
    :return: str
    """

    return '.'.join(urlparse(url).netloc.split('.')[-2:])
