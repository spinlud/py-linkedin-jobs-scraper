# linkedin-jobs-scraper
> Scrape public available jobs on Linkedin using headless browser. 
> For each job, the following fields are extracted: 
> `job_id`, 
> `link`, 
> `apply_link`, 
> `title`, 
> `company`, 
> `company_link`, 
> `company_img_link`, 
> `place`, 
> `description`, 
> `description_html`, 
> `date`,
> `insights`.
>
> It's also available an equivalent [npm package](https://www.npmjs.com/package/linkedin-jobs-scraper).

## Table of Contents

<!-- toc -->

* [Requirements](#requirements)
* [Installation](#installation)
* [Usage](#usage)
* [Anonymous vs authenticated session](#anonymous-vs-authenticated-session)
* [Rate limiting](#rate-limiting)
* [Proxy mode](#proxy-mode-experimental)
* [Filters](#filters)
* [Company filter](#company-filter)
* [Logging](#logging)
* [License](#license)

<!-- toc stop -->


## Requirements
- [Chrome](https://www.google.com/intl/en_us/chrome/) or [Chromium](https://www.chromium.org/getting-involved/download-chromium)
- [Chromedriver](https://chromedriver.chromium.org/): latest version tested is `104.0.5112.79`
- Python >= 3.6


## Installation
Install package:
```shell
pip install linkedin-jobs-scraper
```


## Usage 
```python
import logging
from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import Events, EventData, EventMetrics
from linkedin_jobs_scraper.query import Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import RelevanceFilters, TimeFilters, TypeFilters, ExperienceLevelFilters, RemoteFilters

# Change root logger level (default is WARN)
logging.basicConfig(level = logging.INFO)

# Fired once for each successfully processed job
def on_data(data: EventData):
    print('[ON_DATA]', data.title, data.company, data.company_link, data.date, data.link, data.insights, len(data.description))

# Fired once for each page (25 jobs)
def on_metrics(metrics: EventMetrics):
  print('[ON_METRICS]', str(metrics))

def on_error(error):
    print('[ON_ERROR]', error)

def on_end():
    print('[ON_END]')


scraper = LinkedinScraper(
    chrome_executable_path=None, # Custom Chrome executable path (e.g. /foo/bar/bin/chromedriver) 
    chrome_options=None,  # Custom Chrome options here
    headless=True,  # Overrides headless mode only if chrome_options is None
    max_workers=1,  # How many threads will be spawned to run queries concurrently (one Chrome driver for each thread)
    slow_mo=0.5,  # Slow down the scraper to avoid 'Too many requests 429' errors (in seconds)
    page_load_timeout=20  # Page load timeout (in seconds)    
)

# Add event listeners
scraper.on(Events.DATA, on_data)
scraper.on(Events.ERROR, on_error)
scraper.on(Events.END, on_end)

queries = [
    Query(
        options=QueryOptions(            
            limit=27  # Limit the number of jobs to scrape.            
        )
    ),
    Query(
        query='Engineer',
        options=QueryOptions(
            locations=['United States', 'Europe'],            
            apply_link = True,  # Try to extract apply link (easy applies are skipped). Default to False.
            limit=5,
            filters=QueryFilters(              
                company_jobs_url='https://www.linkedin.com/jobs/search/?f_C=1441%2C17876832%2C791962%2C2374003%2C18950635%2C16140%2C10440912&geoId=92000000',  # Filter by companies.
                relevance=RelevanceFilters.RECENT,
                time=TimeFilters.MONTH,
                type=[TypeFilters.FULL_TIME, TypeFilters.INTERNSHIP],
                experience=None,                
            )
        )
    ),
]

scraper.run(queries)
```
If the query input is like this:

```
queries = [
    Query(
        query='backend',
        options=QueryOptions(
            locations=['Indonesia'],            
            apply_link = True,  # Try to extract apply link (easy applies are skipped). Default to False.
            limit=5
        )
    ),
]
```
Then the output will be shown like this in terminal:
```
INFO:li:scraper:('Using strategy AnonymousStrategy',)
WARNING:li:scraper:("AnonymousStrategy is no longer maintained and it won't probably work. It is recommended to use an authenticated session, see documentation at https://github.com/spinlud/py-linkedin-jobs-scraper#anonymous-vs-authenticated-session.",)
INFO:li:scraper:('Starting new query', "Query(query=backend options=QueryOptions(limit=5 locations=['Indonesia'] 
optimize=False apply_link=True))")

DevTools listening on ws://127.0.0.1:62877/devtools/browser/ccedf756-b0b3-434a-a7eb-02d0e5545cc3
INFO:li:scraper:('Chrome debugger url', 'http://localhost:62877')
[18464:18844:1130/061920.212:ERROR:device_event_log_impl.cc(215)] [06:19:20.212] USB: usb_device_handle_win.cc:1048 Failed to read descriptor from node connection: A device attached to the system is not functioning. (0x1F)    
[18464:18844:1130/061920.221:ERROR:device_event_log_impl.cc(215)] [06:19:20.221] USB: usb_device_handle_win.cc:1048 Failed to read descriptor from node connection: A device attached to the system is not functioning. (0x1F)    
INFO:li:scraper:('[backend][Indonesia]', 'Opening https://www.linkedin.com/jobs/search?keywords=backend&location=Indonesia')
INFO:li:scraper:('[backend][Indonesia]', 'Trying first selectors set')
INFO:li:scraper:('[backend][Indonesia]', 'Trying second selectors set')
INFO:li:scraper:('[backend][Indonesia]', 'OK')
INFO:li:scraper:('[backend][Indonesia]', 'Starting pagination loop')
INFO:li:scraper:('[backend][Indonesia]', 'Found 25 jobs')
INFO:li:scraper:('[backend][Indonesia][1]', 'Processed')
[ON_DATA] Backend SDE Halodoc  2022-11-17 https://id.linkedin.com/jobs/view/backend-sde-at-halodoc-3364253958?refId=f6K2bj9n6800UzVWvOKwVA%3D%3D&trackingId=CQMhfRzkzlJy0sU8fBdGQw%3D%3D&position=1&pageNum=0&trk=public_jobs_jserp-result_search-card [] 1069
INFO:li:scraper:('[backend][Indonesia][2]', 'Processed')
[ON_DATA] Backend Engineer tiket.com  2022-11-16 https://id.linkedin.com/jobs/view/backend-engineer-at-tiket-com-pt-global-tiket-network-3355837178?refId=f6K2bj9n6800UzVWvOKwVA%3D%3D&trackingId=e%2BwixFRh35ftVMT2qf1CAw%3D%3D&position=2&pageNum=0&trk=public_jobs_jserp-result_search-card [] 1679
INFO:li:scraper:('[backend][Indonesia][3]', 'Processed')
[ON_DATA] Back End Developer Female Daily Network  2022-10-19 https://id.linkedin.com/jobs/view/back-end-developer-at-female-daily-network-3334881227?refId=f6K2bj9n6800UzVWvOKwVA%3D%3D&trackingId=RtGJI%2BIZmo14YkwI8HFqcg%3D%3D&position=3&pageNum=0&trk=public_jobs_jserp-result_search-card [] 998
WARNING:li:scraper:('[backend][Indonesia]', '[429] Too many requests', 'You should probably increase scraper "slow_mo" value or reduce concurrency')
ERROR:li:scraper:('[backend][Indonesia][4]', 'Timeout on loading job details')
NoneType: None
INFO:li:scraper:('[backend][Indonesia][4]', 'Processed')
[ON_DATA] Backend Engineer Kitabisa  2022-11-16 https://id.linkedin.com/jobs/view/backend-engineer-at-kitabisa-3362977057?refId=f6K2bj9n6800UzVWvOKwVA%3D%3D&trackingId=7GDE0GYp9GNB9uvVtHBkBg%3D%3D&position=5&pageNum=0&trk=public_jobs_jserp-result_search-card [] 1273
INFO:li:scraper:('[backend][Indonesia][5]', 'Processed')
[ON_DATA] Backend Node.Js PT Global Game Internusa  2022-11-10 https://id.linkedin.com/jobs/view/backend-node-js-at-pt-global-game-internusa-3345818891?refId=f6K2bj9n6800UzVWvOKwVA%3D%3D&trackingId=Cza%2Ft3yW4wZ1css1vE0tMQ%3D%3D&position=6&pageNum=0&trk=public_jobs_jserp-result_search-card [] 328
[ON_END]
```
## Anonymous vs authenticated session

**⚠ WARNING: due to lack of time, anonymous session strategy is no longer maintained. If someone wants to keep
support for this feature and become a project maintainer, please be free to pm me.**  

By default the scraper will run in anonymous mode (no authentication required). In some environments (e.g. AWS or Heroku) 
this may be not possible though. You may face the following error message:

```
Scraper failed to run in anonymous mode, authentication may be necessary for this environment.
```

In that case the only option available is to run using an authenticated session. These are the steps required:
1. Login to LinkedIn using an account of your choice.
2. Open Chrome developer tools:

![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/images/img3.png)

3. Go to tab `Application`, then from left panel select `Storage` -> `Cookies` -> `https://www.linkedin.com`. In the
main view locate row with name `li_at` and copy content from the column `Value`.

![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/images/img4.png)

4. Set the environment variable `LI_AT_COOKIE` with the value obtained in step 3, then run your application as normal.
Example:

```shell script
LI_AT_COOKIE=<your li_at cookie value here> python your_app.py
```

## Rate limiting
You may experience the following rate limiting warning during execution: 
```
[429] Too many requests. You should probably increase scraper "slow_mo" value or reduce concurrency.
```

This means you are exceeding the number of requests per second allowed by the server (this is especially true when 
using authenticated sessions where the rate limits are much more strict). You can overcome this by:

- Trying a higher value for `slow_mo` parameter (this will slow down scraper execution). 
- Reducing the value of `max_workers` to limit concurrency. I recommend to use no more than one worker in authenticated
  mode.
- If you are using anonymous mode, you can try [proxy mode](#proxy-mode-experimental).

The right value for `slow_mo` parameter largely depends on rate-limiting settings on Linkedin servers (and this can 
vary over time). For the time being, I suggest a value of at least `1.3` in anonymous mode and `0.4` in authenticated
mode.
  
## Proxy mode [experimental]
It is also possible to pass a list of proxies to the scraper:

```python
scraper = LinkedinScraper(
    chrome_executable_path=None,
    chrome_options=None,
    headless=True,
    max_workers=1,
    slow_mo=1,
    proxies=[
        'http://localhost:6666',
        'http://localhost:7777',        
    ]
)
```

**How it works?** Basically every request from the browser is intercepted and executed from a python library instead, using
one of the provided proxies in a round-robin fashion. The response is then returned back to the browser. In case of a proxy
error, the request will be executed from the browser (a warning will be logged to stdout).

**WARNING**: proxy mode is currently not supported when using an authenticated session.

## Filters
It is possible to customize queries with the following filters:
- RELEVANCE:
    * `RELEVANT`
    * `RECENT`
- TIME:
    * `DAY`
    * `WEEK`
    * `MONTH`
    * `ANY`
- TYPE:
    * `FULL_TIME`
    * `PART_TIME`
    * `TEMPORARY`
    * `CONTRACT`
- EXPERIENCE LEVEL:
    * `INTERNSHIP`
    * `ENTRY_LEVEL`
    * `ASSOCIATE`
    * `MID_SENIOR`
    * `DIRECTOR`
- REMOTE:
    * `REMOTE` (supported only with authenticated session)
    
See the following example for more details:

```python
from linkedin_jobs_scraper.query import Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import RelevanceFilters, TimeFilters, TypeFilters, ExperienceLevelFilters, RemoteFilters


query = Query(
    query='Engineer',
    options=QueryOptions(
        locations=['United States'],
        optimize=False,
        limit=5,
        filters=QueryFilters(            
            relevance=RelevanceFilters.RECENT,
            time=TimeFilters.MONTH,
            type=[TypeFilters.FULL_TIME, TypeFilters.INTERNSHIP],
            experience=[ExperienceLevelFilters.INTERNSHIP, ExperienceLevelFilters.MID_SENIOR],
            remote=RemoteFilters.REMOTE, # supported only with authenticated session
        )
    )
)
```

### Company Filter

It is also possible to filter by company using the public company jobs url on LinkedIn. To find this url you have to:
 1. Login to LinkedIn using an account of your choice.
 2. Go to the LinkedIn page of the company you are interested in (e.g. [https://www.linkedin.com/company/google](https://www.linkedin.com/company/google)).
 3. Click on `jobs` from the left menu.
 
 ![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/images/img1.png)

 
 4. Scroll down and locate `See all jobs` or `See jobs` button.
 
 ![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/images/img2.png)
 
 5. Right click and copy link address (or navigate the link and copy it from the address bar).
 6. Paste the link address in code as follows:
 
```python
query = Query(    
    options=QueryOptions(        
        filters=QueryFilters(
            # Paste link below
            company_jobs_url='https://www.linkedin.com/jobs/search/?f_C=1441%2C17876832%2C791962%2C2374003%2C18950635%2C16140%2C10440912&geoId=92000000',        
        )
    )
)
```
  
## Logging
Package logger can be retrieved using namespace `li:scraper`. Default level is `INFO`. 
It is possible to change logger level using environment variable `LOG_LEVEL` or in code:

```python
import logging

# Change root logger level (default is WARN)
logging.basicConfig(level = logging.DEBUG)

# Change package logger level
logging.getLogger('li:scraper').setLevel(logging.DEBUG)

# Optional: change level to other loggers
logging.getLogger('urllib3').setLevel(logging.WARN)
logging.getLogger('selenium').setLevel(logging.WARN)
```

## License
[MIT License](http://en.wikipedia.org/wiki/MIT_License)

If you like the project and want to contribute you can [donate something here](https://paypal.me/spinlud)!
