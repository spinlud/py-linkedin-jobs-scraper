#!/usr/bin/env bash

docker build -f tests/Dockerfile -t test_image .

docker run -e LI_AT_COOKIE="$LI_AT_COOKIE" test_image
