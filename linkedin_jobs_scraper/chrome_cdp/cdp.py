import threading
import json
import websocket
from websocket import WebSocketTimeoutException, WebSocketConnectionClosedException
from types import FunctionType
from typing import Callable, Union
from .request import CDPRequest
from .response import CDPResponse
from .events import Events
from ..utils.logger import debug, info, warn, error


class CDP:
    def __init__(self, ws_url, timeout=1):
        self.ws_url = ws_url
        self.timeout = timeout
        self._tag = f'[T_{threading.get_ident()} ChromeDevTools]'
        self._stop = threading.Event()
        self._ws = None
        self._ws_loop_th = None
        self._is_running = False
        self._id = 0

        def __default_request_handler(request: CDPRequest) -> None:
            request.resume()

        self._event_handlers = {
            'request': __default_request_handler,
            'response': None
        }

    def __ws_loop(self):
        """
        Loop to receive messages from websocket server
        :return:
        """

        while not self._stop.is_set():
            try:
                msg = self._ws.recv()
                parsed = json.loads(msg)

                # Intercept request/response
                if 'method' in parsed:
                    event = parsed['method']

                    # Request handler
                    if event == Events.REQUEST.value:
                        if self._event_handlers['request'] is not None:
                            request = CDPRequest(self, parsed)
                            self._event_handlers['request'](request)

                    # Response handler
                    if event == Events.RESPONSE.value:
                        if self._event_handlers['response'] is not None:
                            response = CDPResponse(self, parsed)
                            self._event_handlers['response'](response)
            except (WebSocketTimeoutException, WebSocketConnectionClosedException) as e:
                continue

    def call_method(self, method: str, **params) -> None:
        """
        Call dev tools method with the given parameters
        :param method: str
        :param params:
        :return: None
        """

        if not self._ws or not self._ws.connected:
            raise RuntimeError(self._tag + '\tWebsocket not connected')

        self._id += 1

        msg = {'id': self._id, 'method': method, 'params': params}
        debug(self._tag, 'Calling method', msg)
        self._ws.send(json.dumps(msg))

    def start(self) -> None:
        """
        Start ChromeDevTools client
        :return: None
        """

        if self._is_running:
            raise RuntimeError(self._tag, 'It is already running')

        debug(self._tag, 'Connecting to websocket', self.ws_url)
        self._ws = websocket.create_connection(self.ws_url, enable_multithread=True, skip_utf8_validation=True)
        self._ws.settimeout(self.timeout)

        # Enable Fetch domain
        self.call_method('Fetch.enable')

        # Enable Network domain
        self.call_method('Network.enable')

        self._stop.clear()
        self._ws_loop_th = threading.Thread(target=self.__ws_loop, daemon=True)
        debug(self._tag, 'Starting websocket loop thread', self._ws_loop_th.ident)
        self._ws_loop_th.start()
        self._is_running = True

    def stop(self) -> None:
        """
        Stop ChromeDevTools client
        :return: None
        """

        self._stop.set()

        if self._ws_loop_th:
            self._ws_loop_th.join()

        self._is_running = False

        debug(self._tag, 'Closing websocket')
        self._ws.close()

    def on(self, event: str, cb: Union[Callable, None]) -> None:
        """
        Override event handler
        :param event: str
        :param cb: Callable | None
        :return: None
        """

        if cb is not None and not isinstance(cb, FunctionType):
            raise ValueError(self._tag + '\tCallback must be a function')

        if event not in self._event_handlers.keys():
            raise ValueError(self._tag + f'\tEvent must be one of ({", ".join(self._event_handlers.keys())})')

        self._event_handlers[event] = cb

    def set_user_agent(self, ua: str) -> None:
        """
        Set user agent
        :param ua: str
        :return: None
        """

        debug(self._tag, 'Setting user agent', ua)
        self.call_method('Network.setUserAgentOverride', userAgent=ua)
