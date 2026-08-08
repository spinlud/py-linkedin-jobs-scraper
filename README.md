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
> `date_text`,
> `insights`.


> [!WARNING]
> For personal or educational use only. All extracted data is publicly available on LinkedIn and remains
> owned by LinkedIn. I am not responsible for any inappropriate use of data extracted through this library.

## Sponsored by

### [NinjaPear](https://nubela.co/?utm_source=github&utm_medium=sponsorship&utm_campaign=oss_sponsorships&utm_content=github_readme&utm_id=py-linkedin-jobs-scraper)
<a href="https://nubela.co/?utm_source=github&utm_medium=sponsorship&utm_campaign=oss_sponsorships&utm_content=github_readme&utm_id=py-linkedin-jobs-scraper" target="_blank"><img src="https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/media/ninja-pear-logo.png" width="300px"/></a>

Scrape+Enrich rich B2B profile data in real-time.

## Table of Contents

<!-- toc -->

* [Requirements](#requirements)
* [Installation](#installation)
* [Usage](#usage)
* [Authentication](#authentication)
* [Rate limiting](#rate-limiting)
* [Filters](#filters)
* [Company filter](#company-filter)
* [Logging](#logging)
* [License](#license)

<!-- toc stop -->


## Requirements
- [Chrome](https://www.google.com/intl/en_us/chrome/) or [Chromium](https://www.chromium.org/getting-involved/download-chromium)
- Python >= 3.10

Selenium automatically downloads a Chromedriver matching your Chrome version. 
You can also specify custom paths like so:

```python
scraper = LinkedinScraper(
    chrome_executable_path='/path/to/chromedriver',
    chrome_binary_location='/path/to/chrome',
)
```


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
from linkedin_jobs_scraper.filters import RelevanceFilters, TimeFilters, TypeFilters, ExperienceLevelFilters, \
    OnSiteOrRemoteFilters, SalaryBaseFilters

# Change root logger level (default is WARN)
logging.basicConfig(level=logging.INFO)


# Fired once for each successfully processed job
def on_data(data: EventData):
    print('[ON_DATA]', data.title, data.company, data.company_link, data.date, data.date_text, data.link, data.insights,
          len(data.description))


# Fired once for each page (25 jobs)
def on_metrics(metrics: EventMetrics):
    print('[ON_METRICS]', str(metrics))


def on_error(error):
    print('[ON_ERROR]', error)


def on_end():
    print('[ON_END]')


scraper = LinkedinScraper(
    chrome_executable_path=None,  # Custom Chrome executable path (e.g. /foo/bar/bin/chromedriver)
    chrome_binary_location=None,  # Custom path to Chrome/Chromium binary (e.g. /foo/bar/chrome-mac/Chromium.app/Contents/MacOS/Chromium)
    chrome_options=None,  # Custom Chrome options here
    headless=True,  # Overrides headless mode only if chrome_options is None
    max_workers=1,  # How many threads will be spawned to run queries concurrently (one Chrome driver for each thread)
    slow_mo=0.8,  # Minimum seconds slept between jobs, to avoid 'Too many requests 429' errors. Minimum 0.2, default 0.8
    adaptive_slow_mo=True,  # Slow down automatically when Linkedin throttles the run, then ease back. See 'Rate limiting'
    page_load_timeout=40,  # Page load timeout (in seconds)
    user_data_dir=None,  # Chrome profile reused across runs, so the scraper keeps its own session. See 'Authentication'
    interactive_login=False  # Sign in by hand on the first run, when user_data_dir holds no session. Requires a display
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
            apply_link=True,  # Try to extract apply link (easy applies are skipped). If set to True, scraping is slower because an additional page must be navigated. Default to False.
            skip_promoted_jobs=True,  # Skip promoted jobs. Default to False.
            page_offset=2,  # How many pages to skip
            limit=5,
            filters=QueryFilters(
                company_jobs_url='https://www.linkedin.com/jobs/search/?f_C=1441%2C17876832%2C791962%2C2374003%2C18950635%2C16140%2C10440912&geoId=92000000',  # Filter by companies.                
                relevance=RelevanceFilters.RECENT,
                time=TimeFilters.MONTH,
                type=[TypeFilters.FULL_TIME, TypeFilters.INTERNSHIP],
                on_site_or_remote=[OnSiteOrRemoteFilters.REMOTE],
                experience=[ExperienceLevelFilters.MID_SENIOR],
                base_salary=SalaryBaseFilters.SALARY_100K
            )
        )
    ),
]

scraper.run(queries)
```

## Authentication

The scraper needs a LinkedIn session. There are two ways to give it one: pick the one that
matches where the scraper runs. Both keep the session alive on their own, so a long run is not
interrupted when LinkedIn expires it.

|  | Chrome profile | Cookie pair |
| --- | --- | --- |
| Runs on | A machine with a display | Anywhere, no display needed |
| Setup | Sign in once, in a browser window | Two environment variables |
| Lasts | As long as the profile is kept | About a year |
| Concurrency | `max_workers` forced to `1` | Unrestricted |

### 1. Chrome profile

Sign in once into a Chrome profile that the scraper then reuses:

```shell script
python -m linkedin_jobs_scraper.login --user-data-dir ~/.linkedin-jobs-scraper
```

A browser window opens on the sign in page. Sign in there, ticking **"Keep me logged in"** — that
is what makes the profile reusable. The password is typed into the browser: nothing in this
package reads, stores or transmits it.

Then point the scraper at the same profile:

```python
scraper = LinkedinScraper(user_data_dir='~/.linkedin-jobs-scraper')
```

To skip the separate command and have the first run do the sign in instead:

```python
scraper = LinkedinScraper(
    user_data_dir='~/.linkedin-jobs-scraper',
    interactive_login=True,
)
```

`interactive_login` requires `user_data_dir` and waits up to 10 minutes for a human, so leave it
off (the default) anywhere nobody is watching, such as CI or a server. Chrome locks a profile
directory, so `max_workers` is forced to `1` whenever `user_data_dir` is set.

### 2. Cookie pair

You can use LinkedIn's remember me cookies (`li_rm` and `bcookie`) as environment variables to obtain a session. Useful on a remote machine where a browser window is not available (you still need a machine with a browser window to obtain them the first time). Both variables are required.

```shell script
export LI_RM_COOKIE='<li_rm value>'
export LI_BCOOKIE='<bcookie value>' # keep the double quote " characters the value contains
python your_app.py
```

Get the two values by running the sign in command above on a machine that has a display: it
prints them at the end, quoted and ready to export.

> [!WARNING]
> Do not copy these two cookies out of your browser's developer tools:
> use the sign in command described above instead.

Setting `user_data_dir` as well is worth it if the host has storage that survives across runs:
the session is then reused instead of being requested again at the start of each run.

### Fallback: a bare session cookie

`LI_AT_COOKIE` takes the `li_at` session cookie on its own. This one can be copied straight out of your own Chrome browser. Sign in, then open Chrome developer
tools:

![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/media/img3.png)

Go to tab `Application`, then from the left panel select `Storage` -> `Cookies` ->
`https://www.linkedin.com`, locate the row named `li_at` and copy the `Value` column.

![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/media/img4.png)

```shell script
LI_AT_COOKIE=<your li_at cookie value here> python your_app.py
```

This cookie cannot be renewed: LinkedIn expires it after a while, and a run that
loses it stops. Expect to replace it by hand. Prefer one of the two modes described above if possible.

### Session events

`SESSION_REFRESHED` fires whenever the scraper ends up holding a session cookie different from
the one it was given. Listen to it if you have nowhere else to store a session and want to reuse
it on the next run:

```python
from linkedin_jobs_scraper.events import Events, EventSession

def on_session_refreshed(session: EventSession):
    print('store this for the next run:', session.li_at)

scraper.on(Events.SESSION_REFRESHED, on_session_refreshed)
```

`INVALID_SESSION` fires when every credential supplied was refused, immediately before the run
aborts with `InvalidCookieException`. It takes no arguments:

```python
def on_invalid_session():
    print('LinkedIn refused every credential')

scraper.on(Events.INVALID_SESSION, on_invalid_session)
```

> [!NOTE]
> **Changed in 6.0.0:** `INVALID_SESSION` used to fire whenever a session cookie went missing,
> which normally happened right before a new one was issued and the run carried on. It now fires
> only when authentication has actually failed. If you were using it to know when to harvest a
> fresh cookie, use `SESSION_REFRESHED` instead.

## Rate limiting

Requests failing with the status code 429 mean you are sending too many requests and Linkedin is
throttling them. Two parameters control this:

- `slow_mo`: seconds slept between jobs. Higher is safer, at least `0.2`, default `0.8`.
- `max_workers`: how many queries run concurrently. One worker is recommended.

`slow_mo` is a floor rather than a fixed delay: with `adaptive_slow_mo` on (the default) the run
starts there and paces itself from what Linkedin answers, doubling the delay on every 429 up to
`min(10, slow_mo * 10)` seconds and easing it back down after 20 jobs that went through cleanly.
A page that comes back throttled is asked for again after a wait growing 5s, 15s and 45s, so a
burst of throttling does not end the query. Pass `adaptive_slow_mo=False` to make `slow_mo` a
fixed delay instead.

The `METRICS` event reports both numbers: `throttled` is how many 429s the run has met, `pace` is
the delay currently slept between jobs.

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
- ON SITE OR REMOTE:
    * `ON_SITE`
    * `REMOTE`
    * `HYBRID`
- INDUSTRY:
    * `AIRLINES_AVIATION`
    * `BANKING`
    * `CIVIL_ENGINEERING`
    * `COMPUTER_GAMES`
    * `ENVIRONMENTAL_SERVICES`
    * `ELECTRONIC_MANUFACTURING`
    * `FINANCIAL_SERVICES`
    * `INFORMATION_SERVICES`
    * `INVESTMENT_BANKING`
    * `INVESTMENT_MANAGEMENT`
    * `IT_SERVICES`
    * `LEGAL_SERVICES`
    * `MOTOR_VEHICLES`
    * `OIL_GAS`
    * `SOFTWARE_DEVELOPMENT`
    * `STAFFING_RECRUITING`
    * `TECHNOLOGY_INTERNET`
- BASE SALARY:
    * `SALARY_40K`
    * `SALARY_60K`
    * `SALARY_80K`
    * `SALARY_100K`
    * `SALARY_120K`
    * `SALARY_140K`
    * `SALARY_160K`
    * `SALARY_180K`
    * `SALARY_200K`
- COMPANY:
    * See below
    
See the following example for more details:

```python
from linkedin_jobs_scraper.query import Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import RelevanceFilters, TimeFilters, TypeFilters, ExperienceLevelFilters, \
    OnSiteOrRemoteFilters, IndustryFilters, SalaryBaseFilters
query = Query(
    query='Engineer',
    options=QueryOptions(
        locations=['United States'],        
        apply_link=True,
        skip_promoted_jobs=True,
        limit=5,
        filters=QueryFilters(
            relevance=RelevanceFilters.RECENT,
            time=TimeFilters.MONTH,
            type=[TypeFilters.FULL_TIME, TypeFilters.INTERNSHIP],
            experience=[ExperienceLevelFilters.INTERNSHIP, ExperienceLevelFilters.MID_SENIOR],
            on_site_or_remote=[OnSiteOrRemoteFilters.REMOTE],
            industry=[IndustryFilters.IT_SERVICES],
            base_salary=SalaryBaseFilters.SALARY_100K
        )
    )
)
```

### Industry Filter
You will probably need to add the industry filter to the IndustryFilters class in filters.py

To find the numeric code for the industry:
 1. Perform the search on LinkedIn in a browser, with the industry filter applied.
 2. The numeric code is in the URL, immediately after `f_I` . For example URL
https://www.linkedin.com/jobs/search/?currentJobId=3661007408&distance=25&f_E=3%2C4&f_I=43%2C46%2C41%2C45&f_JT=F%2CC&geoId=102257491&keywords=Product%20Owner&refresh=true contains text `f_I=43%2C46%2C41%2C45` indicating a filter is applied on industry codes 43, 46, 41 and 45.

### Company Filter

It is also possible to filter by company using the public company jobs url on LinkedIn. To find this url you have to:
 1. Login to LinkedIn using an account of your choice.
 2. Go to the LinkedIn page of the company you are interested in (e.g. [https://www.linkedin.com/company/google](https://www.linkedin.com/company/google)).
 3. Click on `jobs` from the left menu.
 
 ![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/media/img1.png)

 
 4. Scroll down and locate `See all jobs` or `See jobs` button.
 
 ![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/media/img2.png)
 
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
