#!/usr/bin/env bash

conda run -n linkedin-jobs-scraper pytest --capture=no --log-cli-level=INFO &
tail -f
