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

<span style="color:red">⚠ **DISCLAIMER** This package is meant for personal or educational use only. All the data extracted by
using this package is publicly available on the LinkedIn website and it remains owned by LinkedIn company.
I am not responsible in any way for the inappropriate use of data extracted through this library.
</span>

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
* [Sponsors](#sponsors)
* [License](#license)

<!-- toc stop -->


## Requirements
- [Chrome](https://www.google.com/intl/en_us/chrome/) or [Chromium](https://www.chromium.org/getting-involved/download-chromium)
- [Chromedriver](https://chromedriver.chromium.org/): latest version tested is `125.0.6422.141` ([Dockerfile](https://github.com/spinlud/python3-selenium-chrome/blob/master/Dockerfile))
- Python >= 3.7


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
    page_load_timeout=40  # Page load timeout (in seconds)    
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

![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/media/img3.png)

3. Go to tab `Application`, then from left panel select `Storage` -> `Cookies` -> `https://www.linkedin.com`. In the
main view locate row with name `li_at` and copy content from the column `Value`.

![](https://github.com/spinlud/py-linkedin-jobs-scraper/raw/master/media/img4.png)

4. Set the environment variable `LI_AT_COOKIE` with the value obtained in step 3, then run your application as normal.
Example:

```shell script
LI_AT_COOKIE=<your li_at cookie value here> python your_app.py
```

## Rate limiting
You may experience failing requests with the status code 429. This means you are sending too many request to the server
and they are being throttled. You can overcome this by:

- Trying a higher value for `slow_mo` parameter (this will slow down scraper execution). 
- Reducing the value of `max_workers` to limit concurrency. I recommend to use no more than one worker in authenticated
  mode.

The right value for `slow_mo` parameter largely depends on rate-limiting settings on Linkedin servers (and this can 
vary over time). For the time being, I suggest a value of at least `1.3` in anonymous mode and `0.5` in authenticated
mode.

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

## Sponsors

### [Proxycurl APIs](https://nubela.co/proxycurl?utm_campaign=influencer_marketing&utm_source=github&utm_medium=social&utm_content=spinlud_py_linkedin_jobs_scraper)
<a href="https://nubela.co/proxycurl?utm_campaign=influencer_marketing&utm_source=github&utm_medium=social&utm_content=spinlud_py_linkedin_jobs_scraper" target="_blank"><img src="media/Proxycurl_logo_2.png" width="300px"/></a>

Scrape public LinkedIn profile data at scale with Proxycurl APIs.

* Scraping Public profiles are battle tested in court in HiQ VS LinkedIn case.
* GDPR, CCPA, SOC2 compliant.
* High rate Limit - 300 requests/minute Fast APIs respond in ~2s.
* Fresh data - 88% of data is scraped real-time, other 12% are not older than 29 days.
* High accuracy.
* Tons of data points returned per profile.

Built for developers, by developers.

## License
[MIT License](http://en.wikipedia.org/wiki/MIT_License)

If you like the project and want to contribute you can [donate something here](https://paypal.me/spinlud)!
