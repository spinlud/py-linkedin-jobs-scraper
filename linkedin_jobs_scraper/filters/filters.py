from enum import Enum


class TimeFilters(Enum):
    ANY = ''
    DAY = 'r86400'
    WEEK = 'r604800'
    MONTH = 'r2592000'


class OnSiteOrRemoteFilters(Enum):
    """Workplace type: values of the f_SAL facet 225001"""
    ON_SITE = '296001'
    REMOTE = '272001'
    HYBRID = '1621001'


class ExperienceLevelFilters(Enum):
    """Experience level: values of the f_SAL facet 227001"""
    ENTRY_LEVEL = '276001'
    SENIOR = '277001'
    MANAGER = '278001'
    DIRECTOR = '272003'
    EXECUTIVE = '279001'


class TypeFilters(Enum):
    """Employment type: values of the f_SAL facet 226001"""
    FULL_TIME = '272015'
    PART_TIME = '273001'
    CONTRACT = '274001'
    INTERNSHIP = '275001'
    VOLUNTEER = '272002'


# f_SAL facet ids, in the order their sections are serialized
WORKPLACE_FACET = '225001'
EXPERIENCE_FACET = '227001'
EMPLOYMENT_TYPE_FACET = '226001'
