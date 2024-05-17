from typing import NamedTuple
from urllib.parse import urljoin

from ..utils.url import get_query_params, get_location, override_query_params
from ..utils.logger import debug, info, warn, error
from ..utils.text import normalize_spaces


# from ..strategies.authenticated_strategy import Selectors

class Selectors(NamedTuple):
    container = '.jobs-search-results-list'
    chatPanel = '.msg-overlay-list-bubble'
    jobs = 'div.job-card-container'
    link = 'a.job-card-container__link'
    applyBtn = 'button.jobs-apply-button[role="link"]'
    title = '.artdeco-entity-lockup__title'
    company = '.artdeco-entity-lockup__subtitle'
    place = '.artdeco-entity-lockup__caption'
    date = 'time'
    description = '.jobs-description'
    detailsPanel = '.jobs-search__job-details--container'
    detailsTop = '.jobs-details-top-card'
    details = '.jobs-details__main-content'
    insights = '[class="mt5 mb2"] > ul > li'  # only one class
    pagination = '.jobs-search-two-pane__pagination'
    privacyAcceptBtn = 'button.artdeco-global-alert__action'
    paginationNextBtn = 'li[data-test-pagination-page-btn].selected + li'  # not used
    paginationBtn = lambda index: f'li[data-test-pagination-page-btn="{index}"] button'  # not used
    required_skills = '.job-details-how-you-match__skills-item-subtitle'
    ## Add here
    salary = '.jobs-details__salary-main-rail-card'  # class="mt4"
    location_remote_available = '.job-details-how-you-match-card__header'
    # Your location does not match country requirements. Hirer is not accepting out of country applications.
    VERIFY_LOGIN_ID = 'global-nav__primary-link'
    USERNAME = 'username'


def extract_job_main_fields(driver, tag, job_index, query):
    debug(tag, 'Evaluating selectors', [
            Selectors.jobs,
            Selectors.link,
            Selectors.company,
            Selectors.place,
            Selectors.date])
    
    job_id, job_link, job_title, job_company, job_company_link, \
    job_company_img_link, job_place, job_date, job_is_promoted = \
        driver.execute_script(
                '''
                    const index = arguments[0];
                    const job = document.querySelectorAll(arguments[1])[index];
                    const link = job.querySelector(arguments[2]);

                    // Click job link and scroll
                    link.scrollIntoView();
                    link.click();

                    // Extract job link (relative)
                    const protocol = window.location.protocol + "//";
                    const hostname = window.location.hostname;
                    const jobLink = protocol + hostname + link.getAttribute("href");


                    const jobId = job.getAttribute("data-job-id");

                    const title = job.querySelector(arguments[3]) ?
                        job.querySelector(arguments[3]).innerText : "";

                    let company = "";
                    let companyLink = "";
                    const companyElem = job.querySelector(arguments[4]);

                    if (companyElem) {
                        company = companyElem.innerText;
                        companyLink = companyElem.getAttribute("href") ?
                        `${protocol}${hostname}${companyElem.getAttribute("href")}` : "";
                    }

                    const companyImgLink = job.querySelector("img") ?
                        job.querySelector("img").getAttribute("src") : "";


                    const place = job.querySelector(arguments[5]) ?
                        job.querySelector(arguments[5]).innerText : "";

                    const date = job.querySelector(arguments[6]) ?
                        job.querySelector(arguments[6]).getAttribute('datetime') : "";

                    const isPromoted = Array.from(job.querySelectorAll('li'))
                        .find(e => e.innerText === 'Promoted') ? true : false;

                    return [
                        jobId,
                        jobLink,
                        title,
                        company,
                        companyLink,
                        companyImgLink,
                        place,
                        date,
                        isPromoted,
                    ];
                ''',
                job_index,
                Selectors.jobs,
                Selectors.link,
                Selectors.title,
                Selectors.company,
                Selectors.place,
                Selectors.date)
    
    reason = None
    job_title = job_title.split("\n")[0]
    job_title = normalize_spaces(job_title)
    if len(query.options_skip.stop_title_list):
        _their_list2filter = job_title.lower().strip()
        _their_list2filter = [_their_list2filter] + _their_list2filter.split(" ")
        if any([mystop.lower().strip() in theirstop for mystop in query.options_skip.stop_title_list
                for theirstop in _their_list2filter]):
            reason = job_title
            job_title = False
    job_company = normalize_spaces(job_company)
    if len(query.options_skip.stop_company_list):
        _their_list2filter = job_company.lower().strip()
        if any([mystop.lower().strip() in _their_list2filter for mystop in query.options_skip.stop_company_list]):
            reason = job_company
            job_company = False
    job_place = normalize_spaces(job_place)
    # Join with base location if link is relative
    job_link = urljoin(get_location(driver.current_url), job_link)
    
    return job_id, job_link, job_title, job_company, job_company_link, \
           job_company_img_link, job_place, job_date, job_is_promoted, reason


def extract_location_remote_available(driver, tag):
    debug(tag, 'Evaluating selectors', [Selectors.location_remote_available])
    location_remote_unavailable = driver.execute_script(
            '''
                const el = document.querySelector(arguments[0]);
                return el.innerText;
            ''',
            Selectors.location_remote_available)
    
    if "Your location does not match country requirements" in location_remote_unavailable:
        location_remote_unavailable = True
    else:
        location_remote_unavailable = False
    return location_remote_unavailable


def extract_job_required_skills(driver, tag, query):
    debug(tag, 'Evaluating selectors', [Selectors.required_skills])
    job_required_skills = driver.execute_script(
            r'''
                const nodes = document.querySelectorAll(arguments[0]);

                if (!nodes.length) {
                    return undefined;
                }

                return Array.from(nodes)
                    .flatMap(e => e.textContent.split(/,|and/))
                    .map(e => e.replace(/[\n\r\t ]+/g, ' ').trim())
                    .filter(e => e.length);
            ''',
            Selectors.required_skills)
    
    if len(query.options_skip.stop_skills_list):
        _their_list2filter = [t.lower().strip() for t in job_required_skills]
        _their_list2filter = _their_list2filter + \
                             [tt for t in _their_list2filter for tt in t.split(" ")]
        if any([mystop.lower().strip() in theirstop for mystop in query.options_skip.stop_skills_list
                for theirstop in _their_list2filter]):
            reason = [mystop.lower().strip() for mystop in query.options_skip.stop_skills_list
                      for theirstop in _their_list2filter if mystop.lower().strip() in theirstop]
            return False, [reason, job_required_skills]
        else:
            return job_required_skills, None


def extract_other(driver, tag, query):
    debug(tag, 'Evaluating selectors', [Selectors.description])
    
    job_description, job_description_html = driver.execute_script(
            '''
                const el = document.querySelector(arguments[0]);

                return [
                    el.innerText,
                    el.outerHTML
                ];
            ''',
            Selectors.description)
    if len(query.options_skip.stop_words_description):
        _their_list2filter = job_description.lower()
        if any([mystop.lower().strip() in _their_list2filter for mystop in query.options_skip.stop_words_description]):
            job_description = False
    
    # Extract SALARY
    debug(tag, 'Evaluating selectors', [Selectors.salary])
    job_salary_full, job_salary_html = driver.execute_script(
            '''
                const el = document.querySelector(arguments[0]);
                return [
                    el.innerText,
                    el.outerHTML
                ];
            ''',
            Selectors.salary)
    job_salary = job_salary_full.split("\n")
    if (len(job_salary) > 2) and ('salary' in job_salary_full):
        job_salary = [job_salary[i + 2] for i, t in enumerate(job_salary[:-2])
                      if 'salary' in job_salary[i].lower()][0]
    else:
        job_salary = ''
    
    return job_description, job_description_html, job_salary
