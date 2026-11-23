from typing import List, Union
from ..filters import TimeFilters, ExperienceLevelFilters, TypeFilters, OnSiteOrRemoteFilters
from ..utils.url import get_query_params


class __Base:
    def __str__(self):
        params = [f'{k}={str(v)}' for k, v in self.__dict__.items() if v is not None and not self.__is_empty_list(v)]
        return f'{self.__class__.__name__}({" ".join(params)})'

    @staticmethod
    def __is_empty_list(v):
        return isinstance(v, List) and len(v) == 0


class Location(__Base):
    def __init__(self, geo_id: str, name: str = None):
        super().__init__()
        self.geo_id = geo_id
        self.name = name

    @property
    def label(self) -> str:
        return self.name if self.name else self.geo_id

    def validate(self):
        if not isinstance(self.geo_id, str) or len(self.geo_id) == 0:
            raise ValueError('Parameter geo_id must be a non-empty string')
        if self.name is not None and not isinstance(self.name, str):
            raise ValueError('Parameter name must be a string')


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
                 company_id: str = None,
                 time: TimeFilters = None,
                 type: Union[TypeFilters, List[TypeFilters]] = None,
                 experience: Union[ExperienceLevelFilters, List[ExperienceLevelFilters]] = None,
                 on_site_or_remote: Union[OnSiteOrRemoteFilters, List[OnSiteOrRemoteFilters]] = None,
                 easy_apply: bool = False,
                 under_10_applicants: bool = False,
                 verified: bool = False):

        super().__init__()

        self.company_jobs_url = company_jobs_url
        self.company_id = company_id
        self.time = time
        self.type = self.process_filter(type)
        self.experience = self.process_filter(experience)
        self.on_site_or_remote = self.process_filter(on_site_or_remote)
        self.easy_apply = easy_apply
        self.under_10_applicants = under_10_applicants
        self.verified = verified

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

        if self.company_id is not None:
            if not isinstance(self.company_id, str) or not self.company_id.isdigit():
                raise ValueError('Parameter company_id must be a numeric string')
            if self.company_jobs_url is not None:
                raise ValueError('Parameters company_id and company_jobs_url are mutually exclusive')

        if self.time is not None and not isinstance(self.time, TimeFilters):
            raise ValueError('Parameter time must be of type TimeFilters')

        if any((not isinstance(e, TypeFilters) for e in self.type)):
            raise ValueError('Parameter type must be of type Union[TypeFilters, List[TypeFilters]]')

        if any((not isinstance(e, ExperienceLevelFilters) for e in self.experience)):
            raise ValueError('Parameter experience must be of type '
                             'Union[ExperienceLevelFilters, List[ExperienceLevelFilters]]')

        if any((not isinstance(e, OnSiteOrRemoteFilters) for e in self.on_site_or_remote)):
            raise ValueError('Parameter on_site_or_remote must be of type '
                             'Union[OnSiteOrRemoteFilters, List[OnSiteOrRemoteFilters]]')

        if not isinstance(self.easy_apply, bool):
            raise ValueError('Parameter easy_apply must be a boolean')

        if not isinstance(self.under_10_applicants, bool):
            raise ValueError('Parameter under_10_applicants must be a boolean')

        if not isinstance(self.verified, bool):
            raise ValueError('Parameter verified must be a boolean')


class QueryOptions(__Base):
    def __init__(self,
                 limit: int = None,
                 locations: List[Union[str, Location]] = None,
                 filters: QueryFilters = None,
                 apply_link: bool = None,
                 skip_promoted_jobs: bool = None,
                 page_offset: int = None):

        super().__init__()

        if isinstance(locations, (str, Location)):
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
            if not isinstance(self.locations, List) or any(
                    [not isinstance(e, (str, Location)) for e in self.locations]):
                raise ValueError('Parameter locations must be a list of strings or Location objects')
            for e in self.locations:
                if isinstance(e, Location):
                    e.validate()

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
    def __init__(self, query: str = '', options: QueryOptions = None):
        super().__init__()

        self.query = query
        self.options = options if options is not None else QueryOptions()

    def merge_options(self, options: QueryOptions):
        if self.options.limit is None:
            self.options.limit = options.limit if options.limit is not None else 25

        if self.options.apply_link is None:
            self.options.apply_link = options.apply_link if options.apply_link is not None else False

        if self.options.skip_promoted_jobs is None:
            self.options.skip_promoted_jobs = options.skip_promoted_jobs if options.skip_promoted_jobs is not None else False

        if self.options.page_offset is None:
            self.options.page_offset = options.page_offset if options.page_offset is not None else 0

        if self.options.locations is None and options.locations is not None:
            self.options.locations = options.locations

        if self.options.filters is None and options.filters is not None:
            self.options.filters = options.filters

    def validate(self):
        if not isinstance(self.query, str):
            raise ValueError(f'Parameter query must be a string')

        self.options.validate()
