import os


class Config:
    LI_AT_COOKIE = os.environ['LI_AT_COOKIE'] if 'LI_AT_COOKIE' in os.environ else None
