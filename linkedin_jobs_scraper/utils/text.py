import re


def normalize_spaces(text: str) -> str:
    return re.sub('[\r\n\t ]+', ' ', text)
