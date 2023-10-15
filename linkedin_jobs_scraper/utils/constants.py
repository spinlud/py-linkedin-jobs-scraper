
import os

# Linkedin specific constants
HOME_URL = 'https://www.linkedin.com'
JOBS_URL = 'https://www.linkedin.com/jobs'
JOBS_SEARCH_URL = 'https://www.linkedin.com/jobs/search'
PAGINATION_SIZE = 25


def set_constant_from_environment(constant_name, default_value):
    env_var_name = 'LJS_' + constant_name
    if env_var_name in os.environ:
        globals()[constant_name] = type(default_value)(os.environ[env_var_name])
    else:
        globals()[constant_name] = default_value

# Other constants
set_constant_from_environment('WAIT_CONTAINER_TIMEOUT', 15)

