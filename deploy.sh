#/usr/bin/env bash

source ~/opt/anaconda3/etc/profile.d/conda.sh
conda activate linkedin-jobs-scraper

rm -fr build && rm -fr dist && rm -fr linkedin_jobs_scraper.egg-info

python setup.py sdist bdist_wheel

twine upload --repository testpypi dist/*
