from urllib.parse import urlparse, urlencode, parse_qsl


def get_query_params(url: str) -> dict:
    parsed = urlparse(url)
    return dict(parse_qsl(parsed.query))
