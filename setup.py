from setuptools import setup

with open('README.md', 'r') as fh:
    long_description = fh.read()

setup(
    name='linkedin-jobs-scraper',
    version='7.0.2',
    author='Ludovico Fabbri',
    author_email='ludovico.fabbri@gmail.com',
    description='Scrape public available jobs on Linkedin using headless browser',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/spinlud/py-linkedin-jobs-scraper.git',
    packages=[
        'linkedin_jobs_scraper',
        'linkedin_jobs_scraper.cli',
        'linkedin_jobs_scraper.events',
        'linkedin_jobs_scraper.exceptions',
        'linkedin_jobs_scraper.filters',
        'linkedin_jobs_scraper.query',
        'linkedin_jobs_scraper.strategies',
        'linkedin_jobs_scraper.utils',
    ],
    install_requires=[
        'selenium>=4.46.0',
    ],
    entry_points={
        'console_scripts': [
            'linkedin-jobs-scraper = linkedin_jobs_scraper.cli.main:main',
            'lijs = linkedin_jobs_scraper.cli.main:main',
        ],
    },
    classifiers=[
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    # The supported range lives here and only here: python_requires is what pip enforces,
    # while classifiers can only enumerate single minor versions and go stale every October.
    python_requires='>=3.10',
)
