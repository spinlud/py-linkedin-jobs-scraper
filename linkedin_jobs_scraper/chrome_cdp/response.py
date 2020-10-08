class CDPResponse:
    def __init__(self, parent: 'ChromeDevTools', message):
        self._parent = parent
        self._tag = '[CDPResponse]'
        params = message['params']
        response = params['response']

        self.event: str = message.pop('method', None)
        self.request_id: str = params.pop('requestId', None)
        self.loader_id: str = params.pop('loaderId', None)
        self.timestamp: float = params.pop('timestamp', None)
        self.type: str = params.pop('type', None)
        self.frame_id: str = params.pop('frameId', None)
        self.url: str = response.pop('url', None)
        self.status: int = response.pop('status', None)
        self.status_text: str = response.pop('statusText', None)
        self.headers: dict = response.pop('headers', None)
        self.mime_type = response.pop('mimeType', None)
        self.connection_reused: bool = response.pop('connectionReused', None)
        self.connection_id: int = response.pop('connectionId', None)
        self.remote_ip_address: str = response.pop('remoteIPAddress', None)
        self.remote_port: int = response.pop('remotePort', None)
        self.from_disk_cache: bool = response.pop('fromDiskCache', None)
        self.from_service_worker: bool = response.pop('fromServiceWorker', None)
        self.from_prefetch_cache: bool = response.pop('fromPrefetchCache', None)
        self.encoded_data_length: int = response.pop('encodedDataLength', None)
        self.timing: dict = response.pop('timing', None)
        self.response_time: float = response.pop('responseTime', None)
        self.protocol: str = response.pop('protocol', None)
        self.security_state: str = response.pop('securityState', None)
        self.security_details: dict = response.pop('securityDetails', None)

    def __str__(self):
        return f'request_id={self.request_id} status={self.status} type={self.type} mime_type={self.mime_type} url={self.url}'
