import requests

from .client import Client


def get_cookie(username, password):
    """Returns the li_at cookie after authenticating with the given credentials

    Args:
        username (_str_): Linkedin username
        password (_str_): Linkedin password

    Returns:
        _type_: _description_
    """
    # Initialize the client
    client = Client(
        refresh_cookies=False,
        debug=False,
        proxies={},
        cookies_dir=None,
    )

    # Authenticate
    client.authenticate(username, password)

    # Get the cookies
    cookies_dict = requests.utils.dict_from_cookiejar(client.cookies)

    # Return the relevant cookie
    return cookies_dict["li_at"]
