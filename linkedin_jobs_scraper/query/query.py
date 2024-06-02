from typing import List, Union
from ..filters import TimeFilters, ExperienceLevelFilters, TypeFilters, RelevanceFilters, OnSiteOrRemoteFilters, IndustryFilters, SalaryBaseFilters
from ..utils.url import get_query_params


class __Base:
    def __str__(self):
        params = [f'{k}={str(v)}' for k, v in self.__dict__.items() if v is not None and not self.__is_empty_list(v)]
        return f'{self.__class__.__name__}({" ".join(params)})'

    @staticmethod
    def __is_empty_list(v):
        return isinstance(v, List) and len(v) == 0


class QueryFilters(__Base):
    @staticmethod
    def process_filter(filter):
        if filter is not None:
            if not isinstance(filter, List):
                return [filter]
            return filter
        return []

    def __init__(self,
                 company_jobs_url: str = None,
                 relevance: RelevanceFilters = None,
                 time: TimeFilters = None,
                 type: Union[TypeFilters, List[TypeFilters]] = None,
                 experience: Union[ExperienceLevelFilters, List[ExperienceLevelFilters]] = None,
                 on_site_or_remote: Union[OnSiteOrRemoteFilters, List[OnSiteOrRemoteFilters]] = None,
                 base_salary: SalaryBaseFilters = None,
                 industry: Union[IndustryFilters, List[IndustryFilters]] = None):

        super().__init__()

        self.company_jobs_url = company_jobs_url
        self.relevance = relevance
        self.time = time
        self.base_salary = base_salary
        self.type = self.process_filter(type)
        self.experience = self.process_filter(experience)
        self.on_site_or_remote = self.process_filter(on_site_or_remote)
        self.industry = self.process_filter(industry)

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

        if self.relevance is not None and not isinstance(self.relevance, RelevanceFilters):
            raise ValueError('Parameter relevance must be of type RelevanceFilters')

        if self.time is not None and not isinstance(self.time, TimeFilters):
            raise ValueError('Parameter time must be of type TimeFilters')

        if self.base_salary is not None and not isinstance(self.base_salary, SalaryBaseFilters):
            raise ValueError('Parameter base_salary must be of type SalaryBaseFilters')

        if any((not isinstance(e, TypeFilters) for e in self.type)):
            raise ValueError('Parameter type must be of type Union[TypeFilters, List[TypeFilters]]')

        if any((not isinstance(e, ExperienceLevelFilters) for e in self.experience)):
            raise ValueError('Parameter experience must be of type '
                             'Union[ExperienceLevelFilters, List[ExperienceLevelFilters]]')

        if any((not isinstance(e, OnSiteOrRemoteFilters) for e in self.on_site_or_remote)):
            raise ValueError('Parameter on_site_or_remote must be of type '
                             'Union[OnSiteOrRemoteFilters, List[OnSiteOrRemoteFilters]]')


class QueryOptions(__Base):
    def __init__(self,
                 limit: int = None,
                 locations: List[str] = None,
                 filters: QueryFilters = None,
                 apply_link: bool = None,
                 skip_promoted_jobs: bool = None,
                 page_offset: int = 0):

        super().__init__()

        if isinstance(locations, str):
            locations = [locations]

        self.limit = limit
        self.locations = locations
        self.filters = filters
        self.apply_link = apply_link
        self.skip_promoted_jobs = skip_promoted_jobs
        self.page_offset = page_offset

    def validate(self):
        if self.limit is not None:
            if not isinstance(self.limit, int) or self.limit < 0:
                raise ValueError('Parameter limit must be a positive integer')

        if self.locations is not None:
            if not isinstance(self.locations, List) or any([not isinstance(e, str) for e in self.locations]):
                raise ValueError('Parameter locations must be a list of strings')

        if self.apply_link is not None and not isinstance(self.apply_link, bool):
            raise ValueError('Parameter apply_link must be a boolean')

        if self.skip_promoted_jobs is not None and not isinstance(self.skip_promoted_jobs, bool):
            raise ValueError('Parameter skip_promoted_jobs must be a boolean')

        if self.page_offset is not None:
            if not isinstance(self.page_offset, int) or self.page_offset < 0:
                raise ValueError('Parameter page_offset must be a positive integer')

        if self.filters is not None:
            self.filters.validate()


class Query(__Base):
    def __init__(self, query: str = '', options: QueryOptions = QueryOptions()):
        super().__init__()

        self.query = query
        self.options = options

    def merge_options(self, options: QueryOptions):
        if self.options.limit is None:
            self.options.limit = options.limit if options.limit is not None else 25

        if self.options.apply_link is None:
            self.options.apply_link = options.apply_link if options.apply_link is not None else False

        if self.options.skip_promoted_jobs is None:
            self.options.skip_promoted_jobs = options.skip_promoted_jobs if options.skip_promoted_jobs is not None else False

        if self.options.locations is None and options.locations is not None:
            self.options.locations = options.locations

        if self.options.filters is None and options.filters is not None:
            self.options.filters = options.filters

    def validate(self):
        if not isinstance(self.query, str):
            raise ValueError(f'Parameter query must be a string')

        self.options.validate()
