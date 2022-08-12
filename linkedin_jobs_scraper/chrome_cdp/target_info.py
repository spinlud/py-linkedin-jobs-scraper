class CDPTargetsInfoResponse:
    def __init__(self, cdp, message):
        self._cdp = cdp
        self._tag = '[CDPTargetsInfoResponse]'

        self.id = message.pop('id', None)
        self.targets = [CDPTargetInfo(cdp, e) for e in message['result']['targetInfos']]

    def __str__(self):
        return f'{self._tag} id={self.id} targets={[str(e) for e in self.targets]}'


class CDPTargetInfo:
    def __init__(self, cdp, message):
        self._tag = '[CDPTargetInfo]'
        self.targetId = message.pop('targetId', None)
        self.type = message.pop('type', None)
        self.title = message.pop('title', None)
        self.url = message.pop('url', None)
        self.attached = message.pop('attached', None)
        self.openerId = message.pop('openerId', None)
        self.canAccessOpener = message.pop('canAccessOpener', None)
        self.openerFrameId = message.pop('openerFrameId', None)
        self.browserContextId = message.pop('browserContextId', None)

    def __str__(self):
        return f'{self._tag} targetId={self.targetId} type={self.type} title={self.title} url={self.url} attached={self.attached}'
