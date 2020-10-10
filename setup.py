from setuptools import setup, find_packages

with open('README.md', 'r') as fh:
    long_description = fh.read()

setup(
    name='linkedin-jobs-scraper',
    version='1.0.3',
    author='Ludovico Fabbri',
    author_email='ludovico.fabbri@gmail.com',
    description='Scrape public available job offers on Linkedin using headless browser',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/pypa/sampleproject',
    package_dir={
        'linkedin_jobs_scraper': 'linkedin_jobs_scraper',
        'linkedin_jobs_scraper.chrome_cdp': 'linkedin_jobs_scraper/chrome_cdp',
        'linkedin_jobs_scraper.strategies': 'linkedin_jobs_scraper/strategies',
        'linkedin_jobs_scraper.utils': 'linkedin_jobs_scraper/utils',
    },
    packages=[
        'linkedin_jobs_scraper',
        'linkedin_jobs_scraper.chrome_cdp',
        'linkedin_jobs_scraper.strategies',
        'linkedin_jobs_scraper.utils',
    ],
    install_requires=[
        'selenium',
        'websocket-client'
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)
