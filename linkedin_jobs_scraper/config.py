import os
import logging


class Config:
    LI_AT_COOKIE = os.environ['LI_AT_COOKIE'] if 'LI_AT_COOKIE' in os.environ else None
    LI_AT_LOGIN = True if os.path.isfile(
        os.path.join(os.path.dirname(os.path.realpath(__file__)), "linkedin_scpap_tokens.py")) else None
    if LI_AT_LOGIN:
        from .linkedin_scpap_tokens import LINKEDIN_EMAIL, LINKEDIN_PASS
    else:
        LINKEDIN_EMAIL, LINKEDIN_PASS = None, None
    LOGGER_NAMESPACE = 'li:scraper'
    
    _level = logging.INFO
    
    if 'LOG_LEVEL' in os.environ:
        _level_env = os.environ['LOG_LEVEL'].upper().strip()
        
        if _level_env == 'DEBUG':
            _level = logging.DEBUG
        elif _level_env == 'INFO':
            _level = logging.INFO
        elif _level_env == 'WARN' or _level_env == 'WARNING':
            _level = logging.WARN
        elif _level_env == 'ERROR':
            _level = logging.ERROR
        elif _level_env == 'FATAL':
            _level = logging.FATAL
    
    LOGGER_LEVEL = _level
