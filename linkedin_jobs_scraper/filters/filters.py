from enum import Enum
from ..config import Config


class RelevanceFilters(Enum):
    RELEVANT = 'R'
    RECENT = 'DD'


class TimeFilters(Enum):
    ANY = ''
    DAY = 'r86400'
    WEEK = 'r604800'
    MONTH = 'r2592000'


class TypeFilters(Enum):
    FULL_TIME = 'F'
    PART_TIME = 'P'
    TEMPORARY = 'T'
    CONTRACT = 'C'
    INTERNSHIP = 'I'
    VOLUNTEER = 'V'
    OTHER = 'O'


class ExperienceLevelFilters(Enum):
    INTERNSHIP = '1'
    ENTRY_LEVEL = '2'
    ASSOCIATE = '3'
    MID_SENIOR = '4'
    DIRECTOR = '5'
    EXECUTIVE = '6'


class OnSiteOrRemoteFilters(Enum):
    ON_SITE = '1'
    REMOTE = '2'
    HYBRID = '3'
