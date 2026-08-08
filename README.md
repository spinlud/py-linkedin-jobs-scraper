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
>
> It's also available an equivalent [npm package](https://www.npmjs.com/package/linkedin-jobs-scraper).

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

**You do not need to install Chromedriver.** Selenium downloads one matching your Chrome
automatically. What it will *not* do is override a Chromedriver already on your `PATH`: if
that one's major version differs from your Chrome, the run fails with
`SessionNotCreatedException`, and Selenium says so — *"advised to delete the driver in PATH
and retry"*. Take that advice; a stray Chromedriver on `PATH` is the most common reason a
first run fails.

If you cannot remove it, or you need a pinned pair, an offline environment or a specific
browser build, name them explicitly instead:

```python
scraper = LinkedinScraper(
    chrome_executable_path='/path/to/chromedriver',
    chrome_binary_location='/path/to/chrome',
)
```

The test suite runs on whatever Chrome the machine provides; the latest pair it has been run
against is Chrome `151.0.7922.76` with Chromedriver `151.0.7922.71`.


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
    slow_mo=0.5,  # Slow down the scraper to avoid 'Too many requests 429' errors (in seconds)
    page_load_timeout=40,  # Page load timeout (in seconds)
    user_data_dir=None,  # Chrome profile kept across runs, so the scraper owns its own session. See 'Authentication'
    interactive_login=False  # Sign in by hand into user_data_dir when it holds no session. Needs a display and a human
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

Scraping needs a LinkedIn session. There are two ways to get one and they differ only in
whether a browser window can be opened, so pick by where the scraper runs. Both end up in the
same place: a session the scraper renews on its own, with nothing to harvest again.

That includes **while a run is in progress**, which is the case a long run actually meets.
LinkedIn retires a session cookie after roughly a hundred job loads, so a scrape asking for
more than that will lose one part way through. When that happens the scraper asks for another,
re-opens the page it was on and carries on from there — jobs it has already given you are not
repeated, and the run does not end. This needs a credential that *can* be renewed, which is
either of the two below but not the `LI_AT_COOKIE` fallback.

### On your own machine: sign in once

```python
scraper = LinkedinScraper(
    user_data_dir='~/.linkedin-jobs-scraper',
    interactive_login=True,
)
```

The first run opens a visible browser on the sign in page and waits. Sign in there, ticking
**"Keep me logged in"**, and the scrape starts by itself as soon as the session appears. Every
later run finds the session in the profile and opens no window at all.

Your password is typed into the browser: nothing in this package reads, stores or transmits
it. "Keep me logged in" is what makes the profile durable — it leaves LinkedIn's `li_rm`
cookie there, which lasts a year, and when the session cookie is retired LinkedIn issues a new
one **silently on the next request**. Verified from a deliberately revoked state: the scraper
recovered and completed the run with nothing configured. Verified mid-run too, by revoking the
session half way through a page: a new one was issued, the page was re-opened, all 60 jobs
arrived and none of them twice.

`interactive_login` requires `user_data_dir` and must stay off wherever nobody is watching, a
CI job or a server: it waits up to 10 minutes for a human. To do the sign in as a separate
step instead, and leave the scraper with no interactive path at all:

```shell script
python -m linkedin_jobs_scraper.login --user-data-dir ~/.linkedin-jobs-scraper
```

Chrome locks a profile directory, so only one browser can use it at a time and `max_workers`
is forced to `1`.

### On a server: two cookies, once a year

Where no browser can be opened — EC2, a container, CI — supply LinkedIn's remember me
credential instead. It is a pair, and both halves are needed: `li_rm` is the credential,
`bcookie` is the browser id it was issued to.

```shell script
export LI_RM_COOKIE=<li_rm value>
export LI_BCOOKIE=<bcookie value>
python your_app.py
```

The scraper asks LinkedIn for a session with them at the start of each run, and again whenever
one is retired mid-run, so there is no session cookie to keep replacing. The pair lasts a year.

This is not just a design intention: a pair issued by the sign in command on a Mac was carried
to a Linux host on a different IP — a container on a cloud VM — and LinkedIn issued it a
session there.

Get the two values by running the sign in command on a machine that has a display. It prints
them at the end, ready to export:

```shell script
python -m linkedin_jobs_scraper.login --user-data-dir ~/.linkedin-jobs-scraper
```

**Do not copy them out of your everyday browser.** Both are visible in the developer tools
cookie panel, and a pair read from there is *refused* — while the pair this command prints
works. The sharpest measurement: the everyday browser's `li_at`, `li_rm` and `bcookie` were put
into one throwaway profile, LinkedIn served the authenticated feed to it, and then deleting
`li_at` and asking `li_rm` for a replacement in that same browser, seconds later, was refused.
So it is the credential, not the machine or the browser. Why is not established: truncation,
rotation, device-bound session credentials and every cookie that can be copied alongside were
each ruled out, and the mechanism remains unknown.

Adding `user_data_dir` on the server is worth it if the host has a volume that survives:
the pair is stored in the profile, so the session is reused between runs rather than reissued,
and the two variables can be dropped from the environment afterwards.

### Fallback: a bare session cookie

`LI_AT_COOKIE` takes the `li_at` cookie on its own. It exists for accounts that never receive a
remember me cookie, two factor authentication being the usual reason. Unlike the pair, this one
*can* be copied straight out of your own browser. Sign in, then open Chrome developer tools:

![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/media/img3.png)

Go to tab `Application`, then from the left panel select `Storage` -> `Cookies` ->
`https://www.linkedin.com`, locate the row named `li_at` and copy the `Value` column.

![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/media/img4.png)

```shell script
LI_AT_COOKIE=<your li_at cookie value here> python your_app.py
```

Expect to replace it. Nothing can renew a session cookie, and LinkedIn retires them: measured
at roughly a hundred job loads per cookie, against a year for the remember me pair. There is
nothing for the scraper to recover with either, so a run that loses this cookie stops. Prefer
the pair whenever the account can produce one.

**Accounts with two factor authentication have not been tested.** That such an account receives
no remember me cookie is the stated reason this fallback exists, and it is an assumption
inherited from earlier work rather than something measured here. If you have 2FA on and the
sign in command does print `LI_RM_COOKIE` and `LI_BCOOKIE`, use them — and please open an
issue saying so, because it would mean this section is aimed at nobody.

### Two events: the session changed, and the session is gone

`SESSION_REFRESHED` carries the session the scraper ends up holding, which differs from the one
you supplied whenever LinkedIn issued a new one — at the start of a run from the remember me
pair, or after a mid-run reissue. Store it if you have nowhere else to keep a session:

```python
from linkedin_jobs_scraper.events import Events, EventSession

def on_session_refreshed(session: EventSession):
    print('store this for the next run:', session.li_at)

scraper.on(Events.SESSION_REFRESHED, on_session_refreshed)
```

`INVALID_SESSION` is the failure. It fires when every credential available was refused and no
session could be issued at all, immediately before the run aborts with
`InvalidCookieException`. It takes no arguments:

```python
def on_invalid_session():
    print('LinkedIn refused everything we have')

scraper.on(Events.INVALID_SESSION, on_invalid_session)
```

**This changed in 6.0.0.** The event used to fire whenever a missing session cookie was
*noticed*, which happened routinely an instant before a new one was issued and the run
continued. It now fires only when recovery has actually failed. If you were using it as a
"time to harvest a fresh cookie" trigger, it now means something stronger and rarer — and the
thing you probably want instead is `SESSION_REFRESHED` above.

### Without any of these

The scraper falls back to an anonymous session, which is **no longer maintained**: its
selectors are stale and it will most likely produce nothing. If you want to keep that feature
alive and become a project maintainer, please pm me.

### Why the session survives at all

LinkedIn used to end it after about one run, whatever you did. The cause was the browser
announcing itself: Chrome in headless mode puts a `HeadlessChrome` token in the `User-Agent`
of every request, and the driver also set `--enable-automation`, which turns on
`navigator.webdriver`. Both are now suppressed, with the `User-Agent` derived from the running
browser so that it stays consistent with the `Sec-CH-UA` client hints. Nothing to configure.

## Rate limiting
You may experience failing requests with the status code 429. This means you are sending too many request to the server
and they are being throttled. You can overcome this by:

- Trying a higher value for `slow_mo` parameter (this will slow down scraper execution). 
- Reducing the value of `max_workers` to limit concurrency. I recommend to use no more than one worker in authenticated
  mode.

The right value for `slow_mo` parameter largely depends on rate-limiting settings on Linkedin servers (and this can 
vary over time). For the time being, I suggest a value of at least `1.3` in anonymous mode and `0.5` in authenticated
mode.

The scraper recovering its own session is not a reason to lower `slow_mo`. Throttling and a
retired session look almost identical from the outside — a page that will not render — and only
one of the two is something the scraper can fix by asking for a new session. Being throttled
still costs you the results.

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
- ON SITE OR REMOTE (**needs an authenticated session**: with none, LinkedIn does not offer this
  filter and it is left out of the search URL rather than failing):
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
