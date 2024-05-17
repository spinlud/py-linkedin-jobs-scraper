import logging
import os
import time
from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import Events, EventData, EventMetrics
from linkedin_jobs_scraper.query import Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import RelevanceFilters, TimeFilters, TypeFilters, ExperienceLevelFilters, \
    OnSiteOrRemoteFilters

# Change root logger level (default is WARN)
from linkedin_jobs_scraper.query.query import QuerySkipOptions

logging.basicConfig(level=logging.INFO)


# Fired once for each successfully processed job
def on_data(data: EventData):
    print('[ON ', data.tag, ']', '\n',
          data.title, "[", data.place, "]", '\n',
          "[", data.company, "]", "[", data.job_salary, "]",
          "\n", data.link)


def on_data_file(data: EventData):
    fn = f"{data.query} {data.location} {time.strftime('%Y%m%d', time.localtime(time.time()))}"
    if not os.path.isfile(f"{fn.replace(' ', '')}.txt"):
        with open(f"{fn.replace(' ', '')}.txt", "w") as f:
            f.write(fn)
            f.write('\n\n\n')
    with open(f"{fn.replace(' ', '')}.txt", "a") as f:
        f.write(" ".join(
                ['[ON ', data.tag, ']', '\n',
                 data.title, "[", data.place, "]", '\n',
                 "[", data.company, "]", "[", data.job_salary, "]", "\n",
                 " ".join(data.skills), "\n",
                 data.link.strip() + "\n\n"]))


# Fired once for each page (25 jobs)
def on_metrics(metrics: EventMetrics):
    print('[ON_METRICS]', str(metrics))


def on_error(error):
    print('[ON_ERROR]', error)


def on_end():
    print('[ON_END]')


scraper = LinkedinScraper(
        chrome_executable_path=None,  # Custom Chrome executable path (e.g. /foo/bar/bin/chromedriver)
        chrome_binary_location=None,
        # Custom path to Chrome/Chromium binary (e.g. /foo/bar/chrome-mac/Chromium.app/Contents/MacOS/Chromium)
        chrome_options=None,  # Custom Chrome options here
        headless=True,  # Overrides headless mode only if chrome_options is None
        max_workers=1,
        # How many threads will be spawned to run queries concurrently (one Chrome driver for each thread)
        slow_mo=1.5,  # Slow down the scraper to avoid 'Too many requests 429' errors (in seconds)
        page_load_timeout=40  # Page load timeout (in seconds)
        )

# Add event listeners
scraper.on(Events.DATA, on_data)
scraper.on(Events.ERROR, on_error)
scraper.on(Events.END, on_end)
scraper.on(Events.DATAFILE, on_data_file)

job_titles = ['Computer Vision', 'Natural Language Processing']

queries = [
        Query(
                query=query,
                options=QueryOptions(
                        locations=['EMEA'],  # 'United States', 'EMEA'
                        apply_link=True,
                        # Try to extract apply link (easy applies are skipped). If set to True, scraping is slower
                        # because an additional page must be navigated. Default to False.
                        # page_offset=2,  # How many pages to skip
                        limit=200,
                        filters=QueryFilters(
                                # company_jobs_url='https://www.linkedin.com/jobs/search/?f_C=1441%2C17876832
                                # %2C791962%2C2374003%2C18950635%2C16140%2C10440912&geoId=92000000',  # Filter by
                                # companies.
                                relevance=RelevanceFilters.RECENT,  # sortBy
                                time=TimeFilters.MONTH,
                                type=[TypeFilters.FULL_TIME],
                                on_site_or_remote=[OnSiteOrRemoteFilters.REMOTE],
                                experience=[ExperienceLevelFilters.MID_SENIOR]
                                )
                        ),
                options_skip=QuerySkipOptions(
                        stop_title_list=['Applied Scientist', 'Backend', 'Trading', 'Sales', 'Gen', 'Executive',
                                         'Account', 'Product', 'Customer', 'Manager', 'Infrastructure',
                                         'Principal', 'Staff', 'Associate', 'Founding', 'President',
                                         'Quant', 'Data Engineer', 'Software', 'Compositor', 'Business', 'Statistical'],
                        stop_skills_list=['sql', 'spark', 'mlops', 'рекомендательные системы', 'базы данных',
                                          'A/B тестирование', 'Структуры данных', 'СУБД', 'Databases',
                                          'Diffusion', 'Reinforcement', 'Time Series', 'Анализ временных рядов',
                                          'Compression',
                                          'automation', 'Автоматизация', 'Алгоритмы', 'Датчики',
                                          'Deployment Strategies', 'Azure', 'BigQuery', 'AWS',
                                          'Clojurescript', 'LLVM', 'Amazon', 'C++', 'C#', 'Risk',
                                          'Робототехника', 'XGBoost', 'Kotlin', 'Android', 'Blockchain',
                                          'HTML', 'TypeScript', 'React', 'Django', 'Веб-аналитика', 'Java', 'Scala',
                                          'Node.js', 'Angular', 'Apache',
                                          'Презентации', 'Протеомика'],
                        stop_words_description=['citizenship', 'Anywhere in the US', 'Hybrid',
                                                'to work in US', 'to work in the US', 'United States Affirmative',
                                                'US based applicants', 'working rights in the US',
                                                'to work in the UK', 'located in the UK', 'work permit'],
                        stop_company_list=['Launch Potato', 'Braintrust'],
                        skip_promoted_jobs=False,  # Skip promoted jobs. Default to False.
                        stop_location_remote_available=True
                        # True - do not return vacancies without full remote option against location, False - return all
                        ),
                )
        for query in job_titles
        ]

scraper.run(queries)
