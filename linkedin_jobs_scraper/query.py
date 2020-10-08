from typing import Callable, List, NamedTuple
from .filters import ETimeFilterOptions, EExperienceLevelOptions, EJobTypeFilterOptions, ERelevanceFilterOptions
from .utils.url import get_query_params


class QueryFilters(NamedTuple):
    company_jobs_url: str = None
    relevance: ERelevanceFilterOptions = None
    time: ETimeFilterOptions = None
    type: EJobTypeFilterOptions = None
    experience: EExperienceLevelOptions = None

    def validate(self):
        if self.company_jobs_url is not None:
            if not isinstance(self.company_jobs_url, str):
                raise ValueError('Parameter company_jobs_url must be a string')

            try:
                query_params = get_query_params(self.company_jobs_url)
                if 'f_C' not in query_params:
                    raise ValueError('Parameter company_jobs_url is invalid. '
                                     'Please check the documentation on how find a company jobs link from LinkedIn')
            except:
                raise ValueError('Parameter company_jobs_url must be a valid url')

        if self.relevance is not None and not isinstance(self.relevance, ERelevanceFilterOptions):
            raise ValueError('Parameter relevance must be a ERelevanceFilterOptions')

        if self.time is not None and not isinstance(self.time, ETimeFilterOptions):
            raise ValueError('Parameter time must be a ETimeFilterOptions')

        if self.type is not None and not isinstance(self.type, EJobTypeFilterOptions):
            raise ValueError('Parameter type must be a EJobTypeFilterOptions')

        if self.experience is not None and not isinstance(self.experience, EExperienceLevelOptions):
            raise ValueError('Parameter experience must be a EExperienceLevelOptions')


class QueryOptions(NamedTuple):
    limit: int = 25
    locations: List[str] = ['Worldwide']
    filters: QueryFilters = None
    optimize: bool = False

    def validate(self):
        if not isinstance(self.limit, int) or self.limit < 0:
            raise ValueError('Parameter limit must be a positive integer')

        if not isinstance(self.locations, List) or any([not isinstance(e, str) for e in self.locations]):
            raise ValueError('Parameter locations must be a list of strings')

        if not isinstance(self.optimize, bool):
            raise ValueError('Parameter optmize must be a boolean')

        if self.filters is not None:
            self.filters.validate()


class Query(NamedTuple):
    query: str = ''
    options: QueryOptions = QueryOptions()

    def merge_options(self, options: QueryOptions):
        if self.options.locations is None and options.locations is not None:
            self.options._replace(locations=options.locations)

        if self.options.filters is None and options.filters is not None:
            self.options._replace(filters=options.filters)

    def validate(self):
        if not isinstance(self.query, str):
            raise ValueError(f'Parameter query must be a string')

        self.options.validate()
