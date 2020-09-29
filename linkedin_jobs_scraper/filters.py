from enum import Enum


class ERelevanceFilterOptions(Enum):
    RELEVANT = 'R'
    RECENT = 'DD'


class ETimeFilterOptions(Enum):
    ANY = ''
    DAY = '1'
    WEEK = '1,2'
    MONTH = '1,2,3,4'


class EJobTypeFilterOptions(Enum):
    FULL_TIME = 'F'
    PART_TIME = 'P'
    TEMPORARY = 'T'
    CONTRACT = 'C'
    INTERNSHIP = 'I'


class EExperienceLevelOptions(Enum):
    INTERNSHIP = '1'
    ENTRY_LEVEL = '2'
    ASSOCIATE = '3'
    MID_SENIOR = '4'
    DIRECTOR = '5'
