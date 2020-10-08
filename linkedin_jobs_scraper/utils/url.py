from urllib.parse import urlparse, urlencode, parse_qsl


def get_query_params(url: str) -> dict:
    """
    Extract url query parameters as a dictionary
    :param url:
    :return: dict
    """

    parsed = urlparse(url)
    return dict(parse_qsl(parsed.query))


def get_domain(url: str) -> str:
    """
    Return SLD (Second Level Domain) from url
    :param url: str
    :return: str
    """

    return '.'.join(urlparse(url).netloc.split('.')[-2:])
