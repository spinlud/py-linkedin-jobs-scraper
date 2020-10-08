from ..utils.logger import debug


class CDPRequest:
    def __init__(self, parent: 'ChromeDevTools', message):
        self._parent = parent
        self._tag = '[CDPRequest]'
        params = message['params']
        request = params['request']

        self.event: str = message.pop('method', None)
        self.request_id: str = params.pop('requestId', None)
        self.url: str = request.pop('url', None)
        self.method: str = request.pop('method', None)
        self.headers: dict = request.pop('headers', None)
        self.post_data: dict = request.pop('postData', None)
        self.initial_priority: str = request.pop('initialPriority', None)
        self.referrer_policy: str = request.pop('referrerPolicy', None)
        self.resource_type: str = params.pop('resourceType', None)
        self.frame_id: str = params.pop('frameId', None)

    def __str__(self):
        return f'request_id={self.request_id} method={self.method} resource_type={self.resource_type} url={self.url}'

    def resume(self):
        debug(self._tag, '[RESUME]', str(self))
        self._parent.call_method('Fetch.continueRequest', requestId=self.request_id)

    def abort(self, reason='Aborted'):
        debug(self._tag, '[ABORT]', str(self))
        self._parent.call_method('Fetch.failRequest', requestId=self.request_id, errorReason=reason)
