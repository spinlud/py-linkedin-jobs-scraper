class CallbackException(Exception):
    """Raised when an exception occurs in a scraper callback"""

    def __init__(self, *args):
        super().__init__(*args)
