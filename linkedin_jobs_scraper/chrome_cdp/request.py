import base64
from ..utils.logger import debug
from typing import Dict, Any, Union, List
from .utils import base64_from_bytes


class CDPRequest:
    def __init__(self, cdp, message):
        self._cdp = cdp
        self._tag = '[CDPRequest]'
        params = message['params']
        request = params['request']

        self.event: str = message.pop('method', None)

        self.request_id: str = params.pop('requestId', None)
        self.resource_type: str = params.pop('resourceType', None)
        self.frame_id: str = params.pop('frameId', None)
        self.response_error_reason: str = params.pop('responseErrorReason', None)
        self.response_status_code: int = params.pop('responseStatusCode', None)
        self.response_headers: List[{'name': str, 'value': str}] = params.pop('responseHeaders', None)
        self.network_id: str = params.pop('networkId', None)

        self.url: str = request.pop('url', None)
        self.method: str = request.pop('method', None)
        self.headers: dict = request.pop('headers', None)
        self.has_post_data: bool = request.pop('hasPostData', None)
        self.post_data: str = request.pop('postData', None)
        self.post_data_entries: List[bytes] = request.pop('postDataEntries', None)
        self.mixed_content_type: str = request.pop('mixedContentType', None)
        self.initial_priority: str = request.pop('initialPriority', None)
        self.referrer_policy: str = request.pop('referrerPolicy', None)
        self.is_link_preload: bool = request.pop('isLinkPreload', None)

    def __str__(self):
        return f'request_id={self.request_id} method={self.method} resource_type={self.resource_type} url={self.url}'

    def resume(self):
        debug(self._tag, '[RESUME]', str(self))
        self._cdp.call_method('Fetch.continueRequest', requestId=self.request_id)

    def abort(self, reason='Aborted'):
        debug(self._tag, '[ABORT]', str(self))
        self._cdp.call_method('Fetch.failRequest', requestId=self.request_id, errorReason=reason)

    def fulfill(
            self,
            code: int = 200,
            headers: Dict[str, Any] = None,
            phrase: str = None,
            body: bytes = None
    ):
        debug(self._tag, '[FULFILL]', str(self))

        _headers = []

        if headers is not None:
            for k, v in headers.items():
                _headers.append({
                    'name': k.lower(),
                    'value': v
                })

        if body is not None:
            if 'content-length' not in _headers:
                _headers.append({
                    'name': 'content-length',
                    'value': str(len(body))
                })

        # print('[FULFILL HEADERS]', _headers)

        self._cdp.call_method('Fetch.fulfillRequest',
                              requestId=self.request_id,
                              responseCode=code,
                              responsePhrase=phrase if phrase else 'OK',
                              responseHeaders=_headers,
                              body=base64_from_bytes(body) if body is not None else None,
                              )
