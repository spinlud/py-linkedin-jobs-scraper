import re

# The applicant clause inside the tertiary description container, one of:
# "N applicants" / "Over N applicants" / "N+ applicants" /
# "N people clicked apply" / "Over N people clicked apply" (N may contain commas).
_APPLICANT_CLAUSE_RE = re.compile(r'(?i)(over\s+)?[\d,]+\+?\s+(?:applicants?|people clicked apply)')


def normalize_spaces(text: str) -> str:
    return re.sub('[\r\n\t ]+', ' ', text)


def clean_applicant_count(text: str) -> str:
    """Reduce the raw applicant segment to just the applicant clause.

    The tertiary description container is not always separated by "·" from adjacent
    badges (e.g. "Over 100 people clicked apply Promoted by hirer"), so the raw segment
    can carry trailing text. Returns the first matching applicant clause with normalized
    whitespace, or an empty string when nothing matches.
    """
    if not text:
        return ''

    match = _APPLICANT_CLAUSE_RE.search(text)

    if match:
        return normalize_spaces(match.group(0)).strip()

    return ''
