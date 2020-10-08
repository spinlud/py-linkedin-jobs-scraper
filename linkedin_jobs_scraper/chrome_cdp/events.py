from enum import Enum


class Events(Enum):
    REQUEST = 'Fetch.requestPaused'
    RESPONSE = 'Network.responseReceived'
