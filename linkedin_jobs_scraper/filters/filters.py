from enum import Enum
from ..config import Config


class RelevanceFilters(Enum):
    RELEVANT = 'R'
    RECENT = 'DD'


class TimeFilters(Enum):
    ANY = ''
    DAY = '1' if not Config.LI_AT_COOKIE else 'r86400'
    WEEK = '1,2' if not Config.LI_AT_COOKIE else 'r604800'
    MONTH = '1,2,3,4' if not Config.LI_AT_COOKIE else 'r2592000'


class TypeFilters(Enum):
    FULL_TIME = 'F'
    PART_TIME = 'P'
    TEMPORARY = 'T'
    CONTRACT = 'C'
    INTERNSHIP = 'I'


class ExperienceLevelFilters(Enum):
    INTERNSHIP = '1'
    ENTRY_LEVEL = '2'
    ASSOCIATE = '3'
    MID_SENIOR = '4'
    DIRECTOR = '5'
