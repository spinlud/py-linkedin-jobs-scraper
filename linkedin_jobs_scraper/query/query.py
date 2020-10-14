from typing import List, Union
from ..filters import TimeFilters, ExperienceLevelFilters, TypeFilters, RelevanceFilters
from ..utils.url import get_query_params


class __Base:
    def __str__(self):
        params = [f'{k}={str(v)}' for k, v in self.__dict__.items() if v is not None and not self.__is_empty_list(v)]
        return f'{self.__class__.__name__}({" ".join(params)})'

    @staticmethod
    def __is_empty_list(v):
        return isinstance(v, List) and len(v) == 0


class QueryFilters(__Base):
    def __init__(self,
                 company_jobs_url: str = None,
                 relevance: RelevanceFilters = None,
                 time: TimeFilters = None,
                 type: Union[TypeFilters, List[TypeFilters]] = None,
                 experience: Union[ExperienceLevelFilters, List[ExperienceLevelFilters]] = None):

        super().__init__()

        if type is not None:
            if not isinstance(type, List):
                type = [type]
        else:
            type = []

        if experience is not None:
            if not isinstance(experience, List):
                experience = [experience]
        else:
            experience = []

        self.company_jobs_url = company_jobs_url
        self.relevance = relevance
        self.time = time
        self.type = type
        self.experience = experience

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

        if any((not isinstance(e, TypeFilters) for e in self.type)):
            raise ValueError('Parameter type must be of type Union[TypeFilters, List[TypeFilters]]')

        if any((not isinstance(e, ExperienceLevelFilters) for e in self.experience)):
            raise ValueError('Parameter experience must be of type '
                             'Union[ExperienceLevelFilters, List[ExperienceLevelFilters]]')


class QueryOptions(__Base):
    def __init__(self,
                 limit: int = None,
                 locations: List[str] = None,
                 filters: QueryFilters = None,
                 optimize: bool = None):

        super().__init__()

        if isinstance(locations, str):
            locations = [locations]

        self.limit = limit
        self.locations = locations
        self.filters = filters
        self.optimize = optimize

    def validate(self):
        if self.limit is not None:
            if not isinstance(self.limit, int) or self.limit < 0:
                raise ValueError('Parameter limit must be a positive integer')

        if self.locations is not None:
            if not isinstance(self.locations, List) or any([not isinstance(e, str) for e in self.locations]):
                raise ValueError('Parameter locations must be a list of strings')

        if self.optimize is not None and not isinstance(self.optimize, bool):
            raise ValueError('Parameter optimize must be a boolean')

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

        if self.options.optimize is None:
            self.options.optimize = options.optimize if options.optimize is not None else False

        if self.options.locations is None and options.locations is not None:
            self.options.locations = options.locations

        if self.options.filters is None and options.filters is not None:
            self.options.filters = options.filters

    def validate(self):
        if not isinstance(self.query, str):
            raise ValueError(f'Parameter query must be a string')

        self.options.validate()
