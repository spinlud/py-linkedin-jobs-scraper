class CallbackException(Exception):
    """Raised when an exception occurs in a scraper callback"""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class InvalidCookieException(Exception):
    """Raised when the session cookie is invalid"""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class ChromedriverResolutionException(Exception):
    """Raised when Selenium Manager cannot provide a chromedriver matching the installed Chrome"""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class UnresolvedLocationError(ValueError):
    """Raised when a location is a name that cannot be turned into a LinkedIn geoId"""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class LocationResolutionError(Exception):
    """Raised when a location name could not be looked up: the location picker could not be
    operated or the page holding it never rendered"""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
