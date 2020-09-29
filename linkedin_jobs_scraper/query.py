from typing import Callable, List, NamedTuple
from .filters import ETimeFilterOptions, EExperienceLevelOptions, EJobTypeFilterOptions, ERelevanceFilterOptions


class QueryFilters(NamedTuple):
    company_jobs_url: str = None
    relevance: ERelevanceFilterOptions = None
    time: ETimeFilterOptions = None
    type: EJobTypeFilterOptions = None
    experience: EExperienceLevelOptions = None


class QueryOptions(NamedTuple):
    limit: int = 25
    locations: List[str] = ['Worldwide']
    filters: QueryFilters = None
    description_fn: Callable = None
    optimize: bool = False


class Query(NamedTuple):
    query: str = ''
    options: QueryOptions = QueryOptions()

    def merge_options(self, options: QueryOptions):
        if self.options.locations is None and options.locations is not None:
            self.options._replace(locations=options.locations)

        if self.options.filters is None and options.filters is not None:
            self.options._replace(filters=options.filters)

        if self.options.description_fn is None and options.description_fn is not None:
            self.options._replace(description_fn=options.description_fn)

    # TODO add static query validation (validateQuery)

