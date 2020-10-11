#/usr/bin/env bash

source ~/opt/anaconda3/etc/profile.d/conda.sh
conda activate linkedin-jobs-scraper

npm run build

python setup.py sdist bdist_wheel

twine upload --repository testpypi dist/*
