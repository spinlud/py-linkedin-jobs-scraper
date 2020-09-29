from urllib.parse import urlparse, urlencode, parse_qsl

url = 'https://www.linkedin.com/jobs/search?keywords=engineer'

parsed = urlparse(url)
current_params = dict(parse_qsl(parsed.query))
new_params = {'location': 'United States'}
merged_params = urlencode({**current_params, **new_params})
parsed = parsed._replace(query=merged_params)

print(parsed.geturl())
# https://www.linkedin.com/jobs/search?keywords=engineer&location=United+States
