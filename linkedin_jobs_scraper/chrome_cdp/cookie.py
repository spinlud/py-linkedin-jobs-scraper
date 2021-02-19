class CDPCookie():
    def __init__(self,
                 name: str,
                 value: str,
                 url: str = None,
                 domain: str = None,
                 path: str = None,
                 secure: bool = None,
                 http_only: bool = None,
                 expires: int = None,
                 same_site: str = None,
                 ):
        self.name = name
        self.value = value
        self.url = url
        self.domain = domain
        self.path = path
        self.secure = secure
        self.http_only = http_only
        self.expires = expires
        self.same_site = same_site

    def __str__(self):
        params = [f'{k}={str(v)}' for k, v in self.__dict__.items() if v is not None and not self.__is_empty_list(v)]
        return f'{self.__class__.__name__}({" ".join(params)})'

    @staticmethod
    def __is_empty_list(v):
        return isinstance(v, list) and len(v) == 0

    def to_dict(self) -> dict:
        d = {
            'name': self.name,
            'value': self.value,
        }

        if self.domain is not None:
            d['domain'] = self.domain

        if self.path is not None:
            d['path'] = self.path

        if self.url is not None:
            d['url'] = self.url

        if self.secure is not None:
            d['secure'] = self.secure

        if self.http_only is not None:
            d['httpOnly'] = self.http_only

        if self.expires is not None:
            d['expires'] = self.expires

        if self.same_site is not None:
            d['sameSite'] = self.same_site

        return d
