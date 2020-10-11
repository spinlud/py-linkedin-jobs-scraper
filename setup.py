from setuptools import setup

with open('README.md', 'r') as fh:
    long_description = fh.read()

setup(
    name='linkedin-jobs-scraper',
    version='1.0.0',
    author='Ludovico Fabbri',
    author_email='ludovico.fabbri@gmail.com',
    description='Scrape public available jobs on Linkedin using headless browser',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/spinlud/py-linkedin-jobs-scraper.git',
    packages=[
        'linkedin_jobs_scraper',
        'linkedin_jobs_scraper.chrome_cdp',
        'linkedin_jobs_scraper.events',
        'linkedin_jobs_scraper.exceptions',
        'linkedin_jobs_scraper.filters',
        'linkedin_jobs_scraper.query',
        'linkedin_jobs_scraper.strategies',
        'linkedin_jobs_scraper.utils',
    ],
    install_requires=[
        'selenium',
        'websocket-client'
    ],
    classifiers=[
        'Intended Audience :: Developers',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)
